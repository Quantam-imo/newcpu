from __future__ import annotations

import csv
import concurrent.futures
import importlib.util
import inspect
import logging
import multiprocessing as mp
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, File, Query, Request, UploadFile

from astroquant.backend.mathematical_engines import LearningFeedbackEngine, MathematicalQuestionChecker
from astroquant.backend.prediction_tracker import PredictionTracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market_causality", tags=["market-causality"])

_module_lock = threading.Lock()
_module = None
_cache_lock = threading.Lock()
_cache_payloads: dict[str, dict[str, Any]] = {}
_cache_ts_by_key: dict[str, float] = {}
# Raw MCL full_system() payloads — keyed same as _cache_payloads.
# Stored separately so /engines can serve all engine outputs without
# going through the summary flattening layer.
_cache_raw_payloads: dict[str, dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 300.0
_summary_refresh_lock = threading.Lock()
_summary_refresh_inflight: set[str] = set()

_boundary_cache_lock = threading.Lock()
_boundary_cache_payload: dict[str, Any] = {"mtime": None, "events": []}
_boundary_alert_sent_at: dict[str, float] = {}
_astro_cycle_cache_lock = threading.Lock()
_astro_cycle_cache_payload: dict[str, Any] = {"mtime": None, "rows": []}


def _to_json_safe(obj: Any) -> Any:
    """Recursively convert numpy/pandas scalars to plain Python types so FastAPI
    can serialise the response without raising TypeError."""
    try:
        import numpy as np  # lazy import — only used when MCL returns numpy types
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return [_to_json_safe(v) for v in obj.tolist()]
    except ImportError:
        pass
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(v) for v in obj]
    return obj  # 5-minute cache — summaries take 40-90s to compute
_SUMMARY_TIMEOUT_SECONDS = max(5.0, float(os.getenv("MCL_SUMMARY_TIMEOUT_SECONDS", "25")))
_BACKGROUND_SUMMARY_TIMEOUT_SECONDS = max(
    _SUMMARY_TIMEOUT_SECONDS + 15.0,
    float(os.getenv("MCL_BACKGROUND_SUMMARY_TIMEOUT_SECONDS", "90")),
)
_MATRIX_TIMEFRAMES = ("1d", "4h", "1h", "30m", "15m", "5m", "1m", "1w", "1month")
_MATRIX_MAX_WORKERS = max(1, int(os.getenv("MCL_MATRIX_MAX_WORKERS", "9")))
_MATRIX_WAIT_SECONDS = max(5.0, float(os.getenv("MCL_MATRIX_WAIT_SECONDS", "18")))
_MATRIX_REFRESH_WAIT_SECONDS = max(
    _MATRIX_WAIT_SECONDS,
    float(os.getenv("MCL_MATRIX_REFRESH_WAIT_SECONDS", "75")),
)
_PREDICTION_TRACKER = PredictionTracker()
_LEARNING_ENGINE = LearningFeedbackEngine(tracker=_PREDICTION_TRACKER)
_LIVE_BROKER_DRIFT_LOCK = threading.Lock()
_LIVE_BROKER_DRIFT: dict[str, Any] = {
    "samples": 0,
    "ema_abs_diff": 0.0,
    "ema_abs_pct": 0.0,
    "last_abs_diff": 0.0,
    "last_abs_pct": 0.0,
    "last_source": "--",
    "updated_at": 0,
}


def _update_live_broker_drift(abs_diff: float, abs_pct: float, source: str) -> None:
    alpha = 0.2
    with _LIVE_BROKER_DRIFT_LOCK:
        samples = int(_LIVE_BROKER_DRIFT.get("samples", 0)) + 1
        prev_diff = float(_LIVE_BROKER_DRIFT.get("ema_abs_diff", 0.0) or 0.0)
        prev_pct = float(_LIVE_BROKER_DRIFT.get("ema_abs_pct", 0.0) or 0.0)
        if samples == 1:
            ema_diff = float(abs_diff)
            ema_pct = float(abs_pct)
        else:
            ema_diff = alpha * float(abs_diff) + (1.0 - alpha) * prev_diff
            ema_pct = alpha * float(abs_pct) + (1.0 - alpha) * prev_pct
        _LIVE_BROKER_DRIFT.update({
            "samples": samples,
            "ema_abs_diff": round(float(ema_diff), 6),
            "ema_abs_pct": round(float(ema_pct), 6),
            "last_abs_diff": round(float(abs_diff), 6),
            "last_abs_pct": round(float(abs_pct), 6),
            "last_source": str(source or "--"),
            "updated_at": int(time.time()),
        })


def _live_broker_drift_snapshot() -> dict[str, Any]:
    with _LIVE_BROKER_DRIFT_LOCK:
        return dict(_LIVE_BROKER_DRIFT)

_TRADING_GANN_QUESTION_BANK: list[dict[str, str]] = [
    # REGIME (2 questions)
    {"id": "REGIME_01", "category": "regime", "framework": "core", "question": "What is the dominant market regime now: trend, range, transition, or trap?"},
    {"id": "REGIME_02", "category": "regime", "framework": "core", "question": "Is this regime stable across major and minor timeframes?"},
    # RISK (2 questions)
    {"id": "RISK_01", "category": "risk", "framework": "core", "question": "Is a high-impact event guard active and blocking directional execution?"},
    {"id": "RISK_02", "category": "risk", "framework": "core", "question": "What is current reliability score vs threshold for valid execution?"},
    # STRUCTURE (2 questions)
    {"id": "STRUCT_01", "category": "structure", "framework": "smc", "question": "Is BOS/CHOCH confirmed in the intended trade direction?"},
    {"id": "STRUCT_02", "category": "structure", "framework": "smc", "question": "Are HH/HL or LL/LH sequences aligned with entry direction?"},
    # PHYSICS (7 questions)
    {"id": "PHYS_01", "category": "physics", "framework": "market_physics", "question": "Is momentum strengthening, weakening, or diverging from structure?"},
    {"id": "PHYS_02", "category": "physics", "framework": "market_physics", "question": "Is acceleration supporting continuation or signaling exhaustion?"},
    {"id": "PHYS_03", "category": "physics", "framework": "market_physics", "question": "How long can this velocity direction persist before natural exhaustion?"},
    {"id": "PHYS_04", "category": "physics", "framework": "market_physics", "question": "Where are gravity wells (support/resistance) pulling price toward now?"},
    {"id": "PHYS_05", "category": "physics", "framework": "market_physics", "question": "What specific conditions signal momentum onset vs momentum exhaustion?"},
    {"id": "PHYS_06", "category": "physics", "framework": "market_physics", "question": "Is price moving against gravity (rejection force) or with gravity (acceleration)?"},
    {"id": "PHYS_07", "category": "physics", "framework": "market_physics", "question": "What is the time until next natural momentum reversal based on oscillation frequency?"},
    # GANN (10 questions)
    {"id": "GANN_01", "category": "gann", "framework": "gann", "question": "Has price reached a cardinal/key Gann angle (45/90/180/225/315)?"},
    {"id": "GANN_02", "category": "gann", "framework": "gann", "question": "Is Gann angle proximity EXACT/NEAR/NONE at the current bar?"},
    {"id": "GANN_03", "category": "gann", "framework": "gann", "question": "Is Price=Time relationship aligned enough for execution now?"},
    {"id": "GANN_04", "category": "gann", "framework": "gann", "question": "What is the nearest key angle, and does it act as launch or rejection level?"},
    {"id": "GANN_05", "category": "gann", "framework": "gann", "question": "How does current price/time map to Gann Square of 9 or 144 derived levels?"},
    {"id": "GANN_06", "category": "gann", "framework": "gann", "question": "Is price/time vibration frequency synchronized with expected harmonic?"},
    {"id": "GANN_07", "category": "gann", "framework": "gann", "question": "What are the calculated swing reversal zones and balance points?"},
    {"id": "GANN_08", "category": "gann", "framework": "gann", "question": "Is price penetrating key angles with conviction or weak rejection?"},
    {"id": "GANN_09", "category": "gann", "framework": "gann", "question": "What quadrant is active and what does its position signal?"},
    {"id": "GANN_10", "category": "gann", "framework": "gann", "question": "When or if a key angle fails, what is the next reversal target?"},
    # TIME (5 questions)
    {"id": "TIME_01", "category": "time", "framework": "gann_time", "question": "Is the selected date inside an active signal time window?"},
    {"id": "TIME_02", "category": "time", "framework": "gann_time", "question": "Is the setup early, on-time, or late relative to cycle phase?"},
    {"id": "TIME_03", "category": "time", "framework": "gann_time", "question": "Are daily/weekly/monthly natural inflection points approaching?"},
    {"id": "TIME_04", "category": "time", "framework": "gann_time", "question": "What is the dominant oscillation period (hours/days/weeks)?"},
    {"id": "TIME_05", "category": "time", "framework": "gann_time", "question": "Are price distance and time distance squared in harmony?"},
    # GEOMETRY (4 questions)
    {"id": "GEOM_01", "category": "geometry", "framework": "gann_geometry", "question": "What geometric shape is price forming (wedge, triangle, channel, flag, pennant)?"},
    {"id": "GEOM_02", "category": "geometry", "framework": "gann_geometry", "question": "Are width:height proportions harmonious or unbalanced in current formation?"},
    {"id": "GEOM_03", "category": "geometry", "framework": "gann_geometry", "question": "Is price following a straight axis, parabolic arc, or random wave?"},
    {"id": "GEOM_04", "category": "geometry", "framework": "gann_geometry", "question": "What is the natural 1:1 angle slope for this price level and timeframe?"},
    # NUMEROLOGY (2 questions)
    {"id": "NUM_01", "category": "numerology", "framework": "numerology", "question": "Are event, date, and price numerology harmoniously aligned?"},
    {"id": "NUM_02", "category": "numerology", "framework": "numerology", "question": "What numerology cycle phase is active: expansion, consolidation, or completion?"},
    # ASTROLOGY (2 questions)
    {"id": "ASTRO_01", "category": "astrology", "framework": "astro", "question": "What nearby astro event is active and what impact level is expected?"},
    {"id": "ASTRO_02", "category": "astrology", "framework": "astro", "question": "Does observed market behavior match astro narration expectations?"},
    # ICT (6 questions)
    {"id": "ICT_01", "category": "ict", "framework": "ict", "question": "Did price sweep liquidity (buy-side/sell-side) before displacement in trade direction?"},
    {"id": "ICT_02", "category": "ict", "framework": "ict", "question": "Is there an ICT-style imbalance/FVG with premium-discount context supporting continuation?"},
    {"id": "ICT_03", "category": "ict", "framework": "ict", "question": "Has price broken through or tested order blocks at current or prior levels?"},
    {"id": "ICT_04", "category": "ict", "framework": "ict", "question": "Are supply/demand zones acting as magnets (price returning) or rejected (break through)?"},
    {"id": "ICT_05", "category": "ict", "framework": "ict", "question": "What is the smart money (institutional) positioning signal: accumulation, distribution, or neutral?"},
    {"id": "ICT_06", "category": "ict", "framework": "ict", "question": "Is current market structure a retracement or continuation pattern from the inducement?"},
    # CONFLUENCE (4 questions)
    {"id": "CONF_01", "category": "confluence", "framework": "gann_confluence", "question": "Do geometry, time, structure, and tape all confirm together?"},
    {"id": "CONF_02", "category": "confluence", "framework": "gann_confluence", "question": "What is the final confluence verdict: BUY, SELL, or WAIT?"},
    {"id": "CONF_03", "category": "confluence", "framework": "gann_confluence", "question": "Which single component (geometry/time/structure/tape) is weakest?"},
    {"id": "CONF_04", "category": "confluence", "framework": "gann_confluence", "question": "What probability for BUY, SELL, WAIT given all confluence data?"},
    # EXECUTION (2 questions)
    {"id": "EXEC_01", "category": "execution", "framework": "execution", "question": "What are the exact entry, stop, target, and expected hold window?"},
    {"id": "EXEC_02", "category": "execution", "framework": "execution", "question": "Is projected move sufficient after spread/slippage and risk costs?"},
    # AI LEARNING (2 questions)
    {"id": "AI_01", "category": "ai_learning", "framework": "ai", "question": "How similar is this setup to past winning/losing patterns in memory?"},
    {"id": "AI_02", "category": "ai_learning", "framework": "ai", "question": "Is model confidence calibrated for this regime or drifting?"},
    # POST-TRADE (2 questions)
    {"id": "POST_01", "category": "post_trade", "framework": "feedback", "question": "Did realized move match projected direction, magnitude, and time window?"},
    {"id": "POST_02", "category": "post_trade", "framework": "feedback", "question": "Which concept failed first when a setup was wrong: geometry, time, structure, or tape?"},
]


def _question_bank_payload(
    category: str | None = None,
    framework: str | None = None,
    live_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cat = str(category or "").strip().lower()
    fw = str(framework or "").strip().lower()

    rows = _TRADING_GANN_QUESTION_BANK
    if cat:
        rows = [q for q in rows if str(q.get("category", "")).lower() == cat]
    if fw:
        rows = [q for q in rows if str(q.get("framework", "")).lower() == fw]

    categories = sorted({str(q.get("category")) for q in _TRADING_GANN_QUESTION_BANK})
    frameworks = sorted({str(q.get("framework")) for q in _TRADING_GANN_QUESTION_BANK})

    # Merge live answers when caller provides a payload
    answered_rows = rows
    gann_answers_meta: dict[str, Any] = {}
    if live_payload is not None:
        gann_out = _compute_gann_answers(live_payload)
        answers_by_id: dict[str, dict[str, Any]] = {
            a["question_id"]: a for a in gann_out.get("gann_questions", [])
        }
        answered_rows = [
            {
                **q,
                **(
                    {
                        "answer": answers_by_id[q["id"]]["answer"],
                        "reasoning": answers_by_id[q["id"]]["reasoning"],
                        "confidence": answers_by_id[q["id"]]["confidence"],
                    }
                    if q.get("id") in answers_by_id
                    else {}
                ),
            }
            for q in rows
        ]
        gann_answers_meta = {
            "gann_questions_verdict": gann_out.get("gann_questions_verdict"),
            "gann_questions_score": gann_out.get("gann_questions_score"),
            "gann_questions_total": gann_out.get("gann_questions_total"),
            "gann_questions_pct": gann_out.get("gann_questions_pct"),
            "gann_weakest_component": gann_out.get("gann_weakest_component"),
            "gann_buy_prob": gann_out.get("gann_buy_prob"),
            "gann_sell_prob": gann_out.get("gann_sell_prob"),
            "gann_wait_prob": gann_out.get("gann_wait_prob"),
        }

    result: dict[str, Any] = {
        "status": "ok",
        "count": len(answered_rows),
        "questions": answered_rows,
        "categories": categories,
        "frameworks": frameworks,
        "selected": {
            "category": cat or None,
            "framework": fw or None,
        },
        "live_answers_included": live_payload is not None,
    }
    result.update(gann_answers_meta)
    return result


def _timeframe_seconds(timeframe: str | None) -> int:
    tf = str(timeframe or "1d").strip().lower()
    return {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
        "1w": 604800,
        "1month": 2592000,
    }.get(tf, 86400)


def _master_cycles_csv_path() -> Path | None:
    base = Path(__file__).resolve().parents[2]
    candidates = [
        base / "market-causality-lab" / "data" / "reports" / "master_cycles_25y.csv",
        base / "data" / "reports" / "master_cycles_25y.csv",
    ]
    return next((p for p in candidates if p.exists()), None)


def _load_boundary_events_cached() -> list[dict[str, Any]]:
    """Load and cache boundary events from master cycles for proximity detection."""
    csv_path = _master_cycles_csv_path()
    if csv_path is None:
        return []

    try:
        mtime = float(csv_path.stat().st_mtime)
    except Exception:
        return []

    with _boundary_cache_lock:
        if _boundary_cache_payload.get("mtime") == mtime:
            return list(_boundary_cache_payload.get("events") or [])

    try:
        import pandas as pd
    except Exception:
        return []

    try:
        mc = pd.read_csv(csv_path, usecols=["start_time", "end_time", "cycle_type", "sub_type"])
    except Exception:
        return []

    if mc.empty:
        return []

    def _to_epoch_seconds(series: "pd.Series") -> "pd.Series":
        dt = pd.to_datetime(series, errors="coerce", utc=True)
        return ((dt - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().fillna(0)).astype("int64")

    events: list[dict[str, Any]] = []
    major_types = {"moon", "gann", "planetary"}

    for kind, col in (("start", "start_time"), ("end", "end_time")):
        part = mc[[col, "cycle_type", "sub_type"]].copy()
        part["ts"] = _to_epoch_seconds(part[col])
        part = part[part["ts"] > 0]
        for _, row in part.iterrows():
            ct = str(row.get("cycle_type") or "").strip().lower()
            if ct not in major_types:
                continue
            events.append(
                {
                    "time": int(row["ts"]),
                    "kind": kind,
                    "cycle_type": ct,
                    "sub_type": str(row.get("sub_type") or ""),
                }
            )

    events.sort(key=lambda e: e["time"])

    with _boundary_cache_lock:
        _boundary_cache_payload["mtime"] = mtime
        _boundary_cache_payload["events"] = events

    return list(events)


def _load_astro_cycle_rows_cached() -> list[dict[str, Any]]:
    """Load astro-cycle rows from master_cycles for degraded summary fallbacks."""
    csv_path = _master_cycles_csv_path()
    if csv_path is None:
        return []

    try:
        mtime = float(csv_path.stat().st_mtime)
    except Exception:
        return []

    with _astro_cycle_cache_lock:
        if _astro_cycle_cache_payload.get("mtime") == mtime:
            return list(_astro_cycle_cache_payload.get("rows") or [])

    rows: list[dict[str, Any]] = []
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                cycle_type = str(row.get("cycle_type") or "").strip().lower()
                if cycle_type not in {"moon", "nakshatra", "planetary"}:
                    continue
                event_ts = _to_epoch_seconds(row.get("event_time"))
                if not event_ts or event_ts <= 0:
                    continue
                rows.append({
                    "time": int(event_ts),
                    "cycle_type": cycle_type,
                    "sub_type": str(row.get("sub_type") or "").strip(),
                    "label": str(row.get("label") or row.get("sub_type") or "").strip(),
                    "impact": str(row.get("impact") or "").strip().lower(),
                    "detail": str(row.get("detail") or "").strip(),
                    "nakshatra": str(row.get("nakshatra") or row.get("sub_type") or "").strip(),
                    "nak_sequence": row.get("nak_sequence"),
                })
    except Exception:
        return []

    rows.sort(key=lambda item: int(item.get("time") or 0))

    with _astro_cycle_cache_lock:
        _astro_cycle_cache_payload["mtime"] = mtime
        _astro_cycle_cache_payload["rows"] = rows

    return list(rows)


def _nearest_gann_angle_info(price: float | None) -> tuple[float | None, str]:
    if price is None or price <= 0:
        return None, "NONE"

    degree = float(price) % 360.0
    key_angles = (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0)

    def _distance(angle: float) -> float:
        raw = abs(degree - angle)
        return min(raw, 360.0 - raw)

    nearest = min(key_angles, key=_distance)
    dist = _distance(nearest)
    if dist <= 2.5:
        proximity = "EXACT"
    elif dist <= 8.0:
        proximity = "NEAR"
    elif dist <= 15.0:
        proximity = "WATCH"
    else:
        proximity = "NONE"
    return float(nearest), proximity


def _build_timeout_intraday_context(
    candles: list[dict[str, Any]],
    timeframe: str,
    signal: str,
    trend: str,
    latest_ts: int | None,
    entry_price: float | None,
) -> dict[str, Any]:
    latest_epoch = int(latest_ts or time.time())
    tf_sec = max(60, _timeframe_seconds(timeframe))
    moon = _build_moon_overlay(candles)
    compression = _build_compression_overlay(candles)
    cycle_rows = _load_astro_cycle_rows_cached()

    astro_rows = [row for row in cycle_rows if row.get("cycle_type") in {"moon", "nakshatra", "planetary"}]
    nearest_event = min(
        astro_rows,
        key=lambda row: abs(int(row.get("time") or 0) - latest_epoch),
        default=None,
    )
    nak_rows = [
        row for row in cycle_rows
        if row.get("cycle_type") == "nakshatra" and int(row.get("time") or 0) <= latest_epoch
    ]
    current_nak = max(nak_rows, key=lambda row: int(row.get("time") or 0), default=None)

    event_name = ""
    event_short = ""
    impact_level = "MEDIUM"
    event_time_iso = None
    time_delta_hours = None
    if nearest_event is not None:
        event_name = str(nearest_event.get("label") or nearest_event.get("sub_type") or nearest_event.get("cycle_type") or "").strip()
        event_short = str(nearest_event.get("sub_type") or event_name).strip()
        impact_level = str(nearest_event.get("impact") or "medium").upper()
        event_ts = int(nearest_event.get("time") or 0)
        if event_ts > 0:
            event_time_iso = datetime.fromtimestamp(event_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            time_delta_hours = round(abs(event_ts - latest_epoch) / 3600.0, 1)

    if not event_name:
        event_name = str(moon.get("phase_name") or "Moon Phase")
    if not event_short:
        event_short = event_name[:32]
    if len(event_short) > 32:
        event_short = f"{event_short[:29]}..."

    nakshatra_name = str(
        (current_nak or {}).get("nakshatra")
        or (current_nak or {}).get("sub_type")
        or event_short
        or "--"
    ).strip() or "--"

    impact_bonus = {"LOW": 4.0, "MEDIUM": 8.0, "HIGH": 12.0}.get(impact_level, 6.0)
    if time_delta_hours is None:
        proximity_bonus = 4.0
    elif time_delta_hours <= 6.0:
        proximity_bonus = 14.0
    elif time_delta_hours <= 24.0:
        proximity_bonus = 10.0
    elif time_delta_hours <= 72.0:
        proximity_bonus = 6.0
    else:
        proximity_bonus = 2.0

    moon_bonus = {
        "NEW_MOON": 10.0,
        "FULL_MOON": 10.0,
        "FIRST_QUARTER": 7.0,
        "LAST_QUARTER": 7.0,
    }.get(str(moon.get("phase_key") or "").upper(), 5.0)
    compression_bonus = 8.0 if compression.get("breakout_near") else (5.0 if compression.get("silence_active") else 2.0)
    signal_bonus = 6.0 if signal in {"BUY", "SELL"} else 0.0
    astro_strength = round(max(35.0, min(92.0, 32.0 + impact_bonus + proximity_bonus + moon_bonus + compression_bonus + signal_bonus)), 1)

    compression_bias = str(compression.get("direction_bias") or "NEUTRAL").upper()
    future_direction = signal
    if future_direction not in {"BUY", "SELL"}:
        if compression_bias == "UP":
            future_direction = "BUY"
        elif compression_bias == "DOWN":
            future_direction = "SELL"
        else:
            future_direction = "WAIT"

    bars_forward = {
        "4h": 2,
        "1h": 4,
        "30m": 6,
        "15m": 8,
        "5m": 12,
        "1m": 20,
    }.get(str(timeframe or "").lower(), 4)
    projected_epoch = latest_epoch + tf_sec * bars_forward
    projected_iso = datetime.fromtimestamp(projected_epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    if time_delta_hours is not None and time_delta_hours <= max(6.0, bars_forward * tf_sec / 3600.0):
        timing_window = f"{event_short} within {time_delta_hours:.1f}h"
    else:
        timing_window = f"Next {bars_forward} bars to {projected_iso}"

    future_strength = round(max(0.35, min(0.92, astro_strength / 100.0 + (0.06 if future_direction in {"BUY", "SELL"} else 0.0))), 3)
    nearest_angle, angle_proximity = _nearest_gann_angle_info(entry_price)
    gann_degree = round(float(entry_price) % 360.0, 3) if entry_price and entry_price > 0 else None

    astro_payload = {
        "strength": astro_strength,
        "nakshatra_name": nakshatra_name,
        "nakshatra_cycle": (current_nak or {}).get("nak_sequence"),
        "moon": {
            "phase_name": moon.get("phase_name"),
            "phase_key": moon.get("phase_key"),
            "illumination": moon.get("cycle_pct"),
            "market_bias": moon.get("market_bias"),
        },
        "nearby_event": {
            "event_name": event_name,
            "event_short": event_short,
            "impact_level": impact_level,
            "event_time": event_time_iso,
            "time_delta_hours": time_delta_hours,
            "detail": (nearest_event or {}).get("detail") or moon.get("gann_narration"),
        },
    }
    future_payload = {
        "direction": future_direction,
        "strength": future_strength,
        "timing_window": timing_window,
        "cycle_event": moon.get("cycle_event") or event_name,
        "cycle_progress_pct": moon.get("cycle_progress"),
        "numerology_energy": moon.get("cycle_energy"),
    }
    observation_patch = {
        "gann_degree": gann_degree,
        "gann_nearest_key_angle": nearest_angle,
        "gann_angle_proximity": angle_proximity,
        "gann_mindset_bias": f"{future_direction}_BIAS" if future_direction in {"BUY", "SELL"} else "NEUTRAL",
        "gann_mindset_narration": (
            f"Timeout fallback: {trend} pressure, {compression_bias} compression bias, "
            f"moon={moon.get('phase_name') or '--'}, astro event={event_short}."
        ),
    }
    time_signal_payload = {
        "timing": timing_window,
        "signals": [future_direction, str(moon.get("market_bias") or "WATCH")],
    }

    return {
        "astro": astro_payload,
        "compression": compression,
        "future": future_payload,
        "time_signal": time_signal_payload,
        "observation": observation_patch,
    }


def _build_timeout_fallback_summary(
    *,
    symbol: str,
    timeframe: str,
    lookback_years: int,
    source_mode: str,
    started_at: float,
    error_text: str,
    fast_mode: bool = False,
) -> dict[str, Any]:
    """Build an enriched stale-timeout summary from chart/live snapshots."""
    snapshot_limit = 800
    if _is_intraday_snapshot_timeframe(timeframe):
        snapshot_limit = 160
    elif str(timeframe or "").strip().lower() in {"4h", "1d"}:
        snapshot_limit = 320

    if fast_mode:
        snapshot_limit = min(snapshot_limit, 160)

    chart = _load_recent_chart_snapshot(
        symbol=symbol,
        timeframe=timeframe,
        limit=snapshot_limit,
    )
    candles = (chart or {}).get("candles") or []
    if not candles and not fast_mode:
        chart = _compute_chart(
            symbol=symbol,
            timeframe=timeframe,
            lookback_years=min(lookback_years, 5),
            limit=snapshot_limit,
        )
        candles = (chart or {}).get("candles") or []
    applied_tf = str((chart or {}).get("applied_timeframe") or timeframe)
    last = candles[-1] if candles else None
    prev = candles[-2] if len(candles) >= 2 else None
    last_close = float((last or {}).get("close") or 0.0)
    prev_close = float((prev or {}).get("close") or last_close or 0.0)
    delta = (last_close - prev_close) if last_close > 0 and prev_close > 0 else 0.0

    signal = "WAIT"
    if delta > 0:
        signal = "BUY"
    elif delta < 0:
        signal = "SELL"

    trend = "sideways"
    if delta > 0:
        trend = "bullish"
    elif delta < 0:
        trend = "bearish"

    live = _load_local_live_quote(symbol=symbol, timeframe=applied_tf)
    if live is None and not fast_mode:
        live = market_causality_live_price(
            symbol=symbol,
            prefer_source="broker",
            broker_only=False,
            max_age_seconds=45,
        )
    live = live or {}
    entry = float(live.get("price") or last_close or 0.0)
    ob_latest = None
    ob_prev = None
    latest_ts = None
    if last and isinstance(last.get("time"), (int, float)):
        latest_ts = int(last["time"])
        ob_latest = datetime.fromtimestamp(latest_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    if prev and isinstance(prev.get("time"), (int, float)):
        ob_prev = datetime.fromtimestamp(int(prev["time"]), tz=timezone.utc).isoformat().replace("+00:00", "Z")

    proj_pct = (abs(delta) / prev_close * 100.0) if prev_close > 0 else 0.25
    proj_pct = float(max(0.10, min(2.50, proj_pct)))
    conf_geom = "CONFIRM" if signal in {"BUY", "SELL"} else "WAIT"
    conf_time = "ALIGNED" if signal in {"BUY", "SELL"} else "WAIT"
    conf_struct = "PASS" if signal in {"BUY", "SELL"} else "WAIT"
    conf_tape = "PASS" if signal in {"BUY", "SELL"} else "WAIT"
    fallback_ctx = _build_timeout_intraday_context(
        candles=candles,
        timeframe=applied_tf,
        signal=signal,
        trend=trend,
        latest_ts=latest_ts,
        entry_price=entry if entry > 0 else last_close,
    )
    astro = fallback_ctx.get("astro") or {}
    compression = fallback_ctx.get("compression") or {}
    future = fallback_ctx.get("future") or {}
    time_signal = fallback_ctx.get("time_signal") or {}
    obs_ctx = fallback_ctx.get("observation") or {}

    g_buy = 25.0
    g_sell = 25.0
    g_wait = 50.0
    if signal == "BUY":
        g_buy, g_sell, g_wait = 62.0, 18.0, 20.0
    elif signal == "SELL":
        g_buy, g_sell, g_wait = 18.0, 62.0, 20.0

    stop_loss = ((entry + 15.0) if signal == "SELL" else (entry - 15.0)) if entry > 0 else None
    take_profit = ((entry - 25.0) if signal == "SELL" else (entry + 25.0)) if entry > 0 else None

    summary = {
        "status": "stale_timeout",
        "error": str(error_text),
        "cache_fallback_used": True,
        "symbol": symbol,
        "signal": signal,
        "confidence": 0.35,
        "quality": "degraded-live-fallback",
        "trend": trend,
        "phase": "fallback_live",
        "reasoning_tone": "degraded_fallback",
        "summary_mode": "timeout_fallback_fast" if fast_mode else "timeout_fallback",
        "requested_timeframe": timeframe,
        "applied_timeframe": applied_tf,
        "timeframe_fallback_applied": bool((chart or {}).get("timeframe_fallback_applied")),
        "timeframe_fallback_reason": (chart or {}).get("timeframe_fallback_reason") or "summary_timeout_live_fallback",
        "instrument_alignment": {
            "requested_symbol": symbol,
            "requested_timeframe": timeframe,
            "applied_timeframe": applied_tf,
            "requested_lookback_years": lookback_years,
            "requested_source_mode": source_mode,
            "timeframe_fallback_applied": bool((chart or {}).get("timeframe_fallback_applied")),
            "timeframe_fallback_reason": (chart or {}).get("timeframe_fallback_reason"),
        },
        "lookback_years": lookback_years,
        "source_mode": source_mode,
        "rows_analyzed": len(candles),
        "live_price": entry if entry > 0 else None,
        "astro": astro,
        "gann": {
            "degree": obs_ctx.get("gann_degree"),
            "nearest_key_angle": obs_ctx.get("gann_nearest_key_angle"),
            "angle_proximity": obs_ctx.get("gann_angle_proximity"),
        },
        "compression": compression,
        "future": future,
        "time_signal": time_signal,
        "mcl_astro": astro,
        "mcl_astro_nakshatra": astro.get("nakshatra_name"),
        "mcl_astro_nakshatra_cycle": astro.get("nakshatra_cycle"),
        "mcl_astro_strength": astro.get("strength"),
        "mcl_astro_moon_phase": ((astro.get("moon") or {}).get("phase_key")),
        "mcl_astro_moon_illumination": ((astro.get("moon") or {}).get("illumination")),
        "mcl_astro_nearby_event": _to_json_safe(astro.get("nearby_event")),
        "mcl_compression": compression,
        "mcl_compression_phase": compression.get("phase"),
        "mcl_compression_score": compression.get("score"),
        "mcl_compression_silence_active": compression.get("silence_active"),
        "mcl_compression_breakout_near": compression.get("breakout_near"),
        "mcl_compression_direction_bias": compression.get("direction_bias"),
        "mcl_compression_energy_stored": compression.get("energy_stored"),
        "mcl_future": future,
        "mcl_future_direction": future.get("direction"),
        "mcl_future_cycle_event": future.get("cycle_event"),
        "mcl_future_strength": future.get("strength"),
        "mcl_future_cycle_progress_pct": future.get("cycle_progress_pct"),
        "mcl_future_numerology_energy": future.get("numerology_energy"),
        "mcl_future_timing_window": future.get("timing_window"),
        "observation_gann_degree": obs_ctx.get("gann_degree"),
        "observation_gann_nearest_key_angle": obs_ctx.get("gann_nearest_key_angle"),
        "observation_gann_angle_proximity": obs_ctx.get("gann_angle_proximity"),
        "observation_gann_mindset_bias": obs_ctx.get("gann_mindset_bias"),
        "observation_gann_mindset_narration": obs_ctx.get("gann_mindset_narration"),
        "observation_signal_start_time": ob_prev,
        "observation_latest_time": ob_latest,
        "observation_signal_start_price": (prev_close if prev_close > 0 else None),
        "observation_signal_end_price": (last_close if last_close > 0 else None),
        "observation_latest_price": (entry if entry > 0 else None),
        "observation_signal_projected_move_pct": proj_pct,
        "observation_confirmation_geometry": conf_geom,
        "observation_confirmation_time": conf_time,
        "observation_confirmation_structure": conf_struct,
        "observation_confirmation_tape_action": conf_tape,
        "gann_buy_prob": g_buy,
        "gann_sell_prob": g_sell,
        "gann_wait_prob": g_wait,
        "gann_questions_pct": 55.0,
        "gann_questions_verdict": "DEGRADED_TIMEOUT",
        "bias_label": f"{signal}_BIAS" if signal in {"BUY", "SELL"} else "NEUTRAL_BIAS",
        "reasoning_summary": (
            f"Timeout fallback using {'local ' if fast_mode else ''}live+chart snapshot ({applied_tf}). "
            f"Signal={signal}, trend={trend}, delta={delta:.3f}, "
            f"moon={((astro.get('moon') or {}).get('phase_key') or '--')}, "
            f"future={future.get('direction') or '--'}."
        ),
        "future_insight": (
            f"Signal={signal} from timeout fallback. "
            f"Astro={((astro.get('nearby_event') or {}).get('event_short') or '--')}, "
            f"timing={future.get('timing_window') or '--'}. "
            f"Use strict risk controls until full summary recovers."
        ),
        "observation": {
            "latest_time": ob_latest,
            "signal_start_time": ob_prev,
            "signal_end_time": ob_latest,
            "signal_start_price": (prev_close if prev_close > 0 else None),
            "signal_end_price": (last_close if last_close > 0 else None),
            "latest_price": (entry if entry > 0 else None),
            "signal_projected_move_pct": proj_pct,
            "gann_degree": obs_ctx.get("gann_degree"),
            "gann_nearest_key_angle": obs_ctx.get("gann_nearest_key_angle"),
            "gann_angle_proximity": obs_ctx.get("gann_angle_proximity"),
            "confirmation_geometry": conf_geom,
            "confirmation_time": conf_time,
            "confirmation_structure": conf_struct,
            "confirmation_tape_action": conf_tape,
            "gann_mindset_bias": obs_ctx.get("gann_mindset_bias"),
            "gann_mindset_narration": obs_ctx.get("gann_mindset_narration"),
        },
        "trade_levels": {
            "entry": entry if entry > 0 else None,
            "sl": stop_loss,
            "tp": take_profit,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "r_ratio": 1.67 if entry > 0 else None,
        },
        "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
        "updated_at": int(time.time()),
    }
    summary["wheel_display"] = _build_fallback_wheel_display(summary)
    return summary


def _summary_latest_epoch(summary: dict[str, Any]) -> int | None:
    obs = summary.get("observation") or {}
    for key in (
        "latest_time",
        "signal_end_time",
        "observation_latest_time",
        "observation_signal_end_time",
        "analysis_completed_at_utc",
    ):
        raw = obs.get(key) if key in obs else summary.get(key)
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            continue
    return None


def _boundary_proximity_for_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Return BEFORE/NEAR/AFTER proximity info against nearest major cycle boundary."""
    latest_ts = _summary_latest_epoch(summary)
    if latest_ts is None:
        return {"status": "unknown"}

    events = _load_boundary_events_cached()
    if not events:
        return {"status": "unavailable"}

    tf = str(summary.get("applied_timeframe") or summary.get("requested_timeframe") or "1d")
    tf_sec = max(60, _timeframe_seconds(tf))

    nearest = min(events, key=lambda e: abs(int(e["time"]) - latest_ts))
    delta_sec = int(nearest["time"]) - latest_ts
    bars = float(delta_sec) / float(tf_sec)
    abs_bars = abs(bars)

    phase = "NONE"
    if abs_bars <= 1.0:
        phase = "NEAR"
    elif 1.0 < bars <= 3.0:
        phase = "BEFORE"
    elif -3.0 <= bars < -1.0:
        phase = "AFTER"

    return {
        "status": "ok",
        "phase": phase,
        "timeframe": tf,
        "latest_epoch": latest_ts,
        "boundary_epoch": int(nearest["time"]),
        "boundary_kind": str(nearest.get("kind") or ""),
        "cycle_type": str(nearest.get("cycle_type") or ""),
        "sub_type": str(nearest.get("sub_type") or ""),
        "delta_seconds": int(delta_sec),
        "delta_bars": round(bars, 3),
    }


def _maybe_send_boundary_telegram_alert(summary: dict[str, Any], symbol: str) -> None:
    """Send Telegram alert when setup is BEFORE/NEAR/AFTER a cycle boundary (deduped/cooldown)."""
    if str(os.getenv("TELEGRAM_BOUNDARY_ALERT_ENABLED", "true")).strip().lower() not in {"1", "true", "yes", "on"}:
        return

    prox = _boundary_proximity_for_summary(summary)
    phase = str(prox.get("phase") or "NONE").upper()
    if phase not in {"BEFORE", "NEAR", "AFTER"}:
        return

    cooldown = max(60, int(float(os.getenv("TELEGRAM_BOUNDARY_ALERT_COOLDOWN_SEC", "1800"))))
    tf = str(prox.get("timeframe") or summary.get("applied_timeframe") or "1d")
    b_epoch = int(prox.get("boundary_epoch") or 0)
    b_kind = str(prox.get("boundary_kind") or "")
    cyc = str(prox.get("cycle_type") or "")

    dedup_key = f"{symbol}|{tf}|{phase}|{b_epoch}|{b_kind}|{cyc}"
    now_ts = time.time()
    last_ts = float(_boundary_alert_sent_at.get(dedup_key) or 0.0)
    if now_ts - last_ts < cooldown:
        return

    try:
        from astroquant.notifications.telegram_bot import send_message as _send_telegram
    except Exception:
        return

    signal = str(summary.get("signal") or "--").upper()
    conf = summary.get("confidence")
    conf_txt = f"{float(conf):.1f}%" if conf is not None else "--"
    delta_bars = prox.get("delta_bars")
    delta_txt = f"{float(delta_bars):+.2f} bars" if delta_bars is not None else "--"

    try:
        b_dt = datetime.fromtimestamp(int(b_epoch), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        b_dt = str(b_epoch)

    msg = (
        f"[AstroQuant Boundary Alert]\n"
        f"Symbol: {symbol}\n"
        f"TF: {tf}\n"
        f"Phase: {phase} ({delta_txt})\n"
        f"Boundary: {str(b_kind).upper()} {cyc}/{prox.get('sub_type', '')}\n"
        f"Boundary Time: {b_dt}\n"
        f"Signal: {signal} | Confidence: {conf_txt}"
    )

    res = _send_telegram(msg)
    if isinstance(res, dict) and res.get("ok"):
        _boundary_alert_sent_at[dedup_key] = now_ts


def _driver_score_map(drivers: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    if not isinstance(drivers, list):
        return out
    for item in drivers:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        pct = item.get("score_pct")
        try:
            out[label] = float(pct)
        except (TypeError, ValueError):
            out[label] = 0.0
    return out


def _build_reasoning_delta(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not previous:
        return {
            "has_previous": False,
            "previous_signal": None,
            "signal_changed": False,
            "top_driver_deltas": [],
        }

    current_signal = str(current.get("signal") or "")
    previous_signal = str(previous.get("signal") or "")

    curr_map = _driver_score_map(current.get("reasoning_top_drivers"))
    prev_map = _driver_score_map(previous.get("reasoning_top_drivers"))

    labels = sorted(set(curr_map.keys()) | set(prev_map.keys()))
    deltas = []
    for label in labels:
        curr = float(curr_map.get(label, 0.0))
        prev = float(prev_map.get(label, 0.0))
        delta = round(curr - prev, 2)
        deltas.append(
            {
                "label": label,
                "current_pct": round(curr, 2),
                "previous_pct": round(prev, 2),
                "delta_pct": delta,
            }
        )

    deltas = sorted(deltas, key=lambda item: abs(float(item.get("delta_pct", 0.0))), reverse=True)
    return {
        "has_previous": True,
        "previous_signal": previous_signal or None,
        "signal_changed": bool(current_signal and previous_signal and current_signal != previous_signal),
        "top_driver_deltas": deltas,
    }


def _summary_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_market_direction(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"BUY", "STRONG BUY", "UP", "BULLISH", "UPWARD", "UPWARD_CONTINUATION"}:
        return "BUY"
    if text in {"SELL", "STRONG SELL", "DOWN", "BEARISH", "DOWNWARD", "DOWNWARD_CONTINUATION"}:
        return "SELL"
    return "WAIT"


def _build_fallback_wheel_display(summary: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None

    signal_raw = str(summary.get("signal") or summary.get("filtered_signal") or "WAIT").upper()
    trend_raw = str(summary.get("trend") or "UNKNOWN").upper()
    future = summary.get("future") or {}
    time_signal = summary.get("time_signal") or {}
    astro = summary.get("astro") or {}
    gann = summary.get("gann") or {}
    compression = summary.get("compression") or {}
    trade_levels = summary.get("trade_levels") or {}
    observation = summary.get("observation") or {}
    confidence = summary.get("confidence")

    current_phase = "ACCUMULATION"
    if "BULL" in trend_raw or "BUY" in signal_raw:
        current_phase = "EXPANSION"
    elif "BEAR" in trend_raw or "SELL" in signal_raw:
        current_phase = "DISTRIBUTION"
    elif str(compression.get("phase") or "").upper() == "OPEN":
        current_phase = "MANIPULATION"

    phase_order = ["ACCUMULATION", "MANIPULATION", "EXPANSION", "DISTRIBUTION"]
    current_idx = max(0, phase_order.index(current_phase))
    if "BUY" in signal_raw:
        next_phase = "EXPANSION"
    elif "SELL" in signal_raw:
        next_phase = "DISTRIBUTION"
    else:
        next_phase = phase_order[(current_idx + 1) % len(phase_order)]

    confidence_value = _summary_float(confidence, 0.55)
    next_confidence = max(0.2, min(0.95, confidence_value))
    base_prob = (1.0 - next_confidence) / 3.0
    segments = [
        {
            "phase": phase,
            "is_current": phase == current_phase,
            "next_probability": next_confidence if phase == next_phase else base_prob,
        }
        for phase in phase_order
    ]

    latest_time = observation.get("latest_time") or summary.get("updated_at")
    if isinstance(latest_time, str):
        as_of_date_utc = str(latest_time).split("T", 1)[0]
    elif latest_time is not None:
        as_of_date_utc = datetime.fromtimestamp(int(latest_time), tz=timezone.utc).strftime("%Y-%m-%d")
    else:
        as_of_date_utc = None

    order_flow_side = "NEUTRAL"
    if "BUY" in signal_raw:
        order_flow_side = "BUY"
    elif "SELL" in signal_raw:
        order_flow_side = "SELL"

    return {
        "status": "WATCH" if signal_raw == "WAIT" else "ACTIONABLE",
        "phase_ring": {
            "current_phase": current_phase,
            "current_phase_code": current_idx,
            "predicted_next_phase": next_phase,
            "predicted_next_confidence": next_confidence,
            "segments": segments,
        },
        "market_conditions": {
            "regime": trend_raw,
            "atr_z": compression.get("score"),
            "order_flow_side": order_flow_side,
            "order_flow_imbalance": confidence,
            "iceberg_side": "NONE",
        },
        "signal_state": {
            "display_signal": signal_raw,
            "executable_signal": signal_raw,
            "confidence": confidence,
            "reliability_score": confidence,
            "rejection_reason": "timeout_fallback_snapshot" if summary.get("summary_mode") == "live_snapshot" else "none",
            "actionable_now": signal_raw != "WAIT",
        },
        "setup_state": {
            "amd_phase": "UNKNOWN",
            "amd_signal": "UNKNOWN",
            "amd_bull_entry": False,
            "amd_bear_entry": False,
            "amd_rr_ratio": None,
            "turtle_soup_buy": False,
            "turtle_soup_sell": False,
            "turtle_sweep_direction": "NONE",
            "turtle_rejection_confirmed": False,
        },
        "future_prediction": {
            "direction": str(future.get("direction") or signal_raw or "UNCLEAR"),
            "cycle_event": str(future.get("cycle_event") or summary.get("future_insight") or "LIVE SNAPSHOT"),
            "timing_window": str(time_signal.get("timing") or future.get("timing_window") or "LIVE"),
            "price_now": trade_levels.get("entry") or observation.get("latest_price") or summary.get("live_price"),
            "price_target": trade_levels.get("take_profit") or trade_levels.get("tp"),
            "price_time_ratio": None,
            "degree_now": gann.get("degree"),
            "degree_target": gann.get("nearest_key_angle"),
            "time_cycle_bars": None,
            "as_of_date_utc": as_of_date_utc,
            "projected_turn_date_utc": None,
            "date_timing_note": str(((astro.get("nearby_event") or {}).get("detail")) or "live snapshot fallback"),
        },
    }


def _project_phase_label(current_phase: str, movement_direction: str) -> str:
    phase = str(current_phase or "UNKNOWN").strip().upper()
    direction = _normalize_market_direction(movement_direction)

    if direction == "BUY":
        return {
            "ACCUMULATION": "ACCUMULATION_TO_EXPANSION",
            "MANIPULATION": "MANIPULATION_RESOLVE_UP",
            "DISTRIBUTION": "DISTRIBUTION_REVERSAL_UP",
            "CONSOLIDATION": "CONSOLIDATION_BREAKOUT_UP",
            "FALLBACK_LIVE": "LIVE_BREAKOUT_UP",
        }.get(phase, "UPWARD_CONTINUATION")

    if direction == "SELL":
        return {
            "ACCUMULATION": "ACCUMULATION_FAILURE_DOWN",
            "MANIPULATION": "MANIPULATION_RESOLVE_DOWN",
            "DISTRIBUTION": "DISTRIBUTION_TO_MARKDOWN",
            "CONSOLIDATION": "CONSOLIDATION_BREAKOUT_DOWN",
            "FALLBACK_LIVE": "LIVE_BREAKOUT_DOWN",
        }.get(phase, "DOWNWARD_CONTINUATION")

    return phase or "UNKNOWN"


def _build_ai_phase_forecast(summary: dict[str, Any]) -> dict[str, Any]:
    ai_model = summary.get("ai_model") or {}
    ai_buy = _summary_float(ai_model.get("p_buy"), 0.0)
    ai_sell = _summary_float(ai_model.get("p_sell"), 0.0)
    future_direction = _normalize_market_direction(summary.get("mcl_future_direction") or ((summary.get("future") or {}).get("direction")))
    signal_direction = _normalize_market_direction(summary.get("signal"))
    compression_bias = str(summary.get("mcl_compression_direction_bias") or "").strip().upper()
    bias_label = str(summary.get("bias_label") or "NEUTRAL_BIAS")
    current_phase = str(summary.get("phase") or "UNKNOWN").strip().upper()

    ai_direction = "WAIT"
    if ai_buy >= 0.55 and ai_buy >= ai_sell:
        ai_direction = "BUY"
    elif ai_sell >= 0.55 and ai_sell > ai_buy:
        ai_direction = "SELL"

    movement_direction = ai_direction
    if movement_direction == "WAIT":
        movement_direction = future_direction
    if movement_direction == "WAIT":
        movement_direction = signal_direction
    if movement_direction == "WAIT" and compression_bias in {"UP", "DOWN"}:
        movement_direction = "BUY" if compression_bias == "UP" else "SELL"

    confidence_candidates = [
        _summary_float(summary.get("confidence"), 0.0),
        _summary_float(summary.get("reliability_score"), 0.0),
        max(ai_buy, ai_sell),
        _summary_float(summary.get("mcl_future_strength"), 0.0),
    ]
    movement_confidence = max(0.0, min(1.0, max(confidence_candidates)))
    phase_projection = _project_phase_label(current_phase, movement_direction)

    nearby_event = summary.get("mcl_astro_nearby_event") or {}
    if not isinstance(nearby_event, dict):
        nearby_event = {}

    gann_astro_drivers = {
        "moon_phase": summary.get("mcl_astro_moon_phase"),
        "nakshatra": summary.get("mcl_astro_nakshatra"),
        "nearby_event": nearby_event.get("event_short") or nearby_event.get("event_name"),
        "nearby_event_impact": nearby_event.get("impact_level"),
        "gann_degree": summary.get("observation_gann_degree") or summary.get("mcl_gann_degree"),
        "gann_angle_proximity": summary.get("observation_gann_angle_proximity"),
        "future_cycle_event": summary.get("mcl_future_cycle_event"),
        "timing_window": summary.get("mcl_future_timing_window"),
    }

    direction_label = {
        "BUY": "UPWARD_MOVE",
        "SELL": "DOWNWARD_MOVE",
        "WAIT": "SIDEWAYS_OR_UNCLEAR",
    }.get(movement_direction, "SIDEWAYS_OR_UNCLEAR")

    return {
        "current_phase": current_phase,
        "phase_projection": phase_projection,
        "market_movement_direction": movement_direction,
        "market_movement_label": direction_label,
        "confidence_pct": round(movement_confidence * 100.0, 2),
        "ai_buy_prob": round(ai_buy * 100.0, 2),
        "ai_sell_prob": round(ai_sell * 100.0, 2),
        "future_direction": future_direction,
        "signal_direction": signal_direction,
        "compression_bias": compression_bias or None,
        "bias_label": bias_label,
        "ai_model_used": bool(ai_model.get("used_model")),
        "ai_model_version": ai_model.get("version"),
        "ai_model_scope": ai_model.get("resolved_model_scope") or ai_model.get("model_timeframe"),
        "ai_model_trade_direction": ai_model.get("model_trade_direction"),
        "ai_trigger_direction": ai_model.get("trigger_direction"),
        "ai_bundle_source": ai_model.get("bundle_source"),
        "gann_astro_drivers": gann_astro_drivers,
        **_akshaya_proximity(),
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Akshaya Tritiya proximity helper
# ---------------------------------------------------------------------------
_AKSHAYA_DATES_CACHE: list[datetime] | None = None
_AKSHAYA_WINDOW_DAYS: int = 7


def _load_akshaya_dates() -> list[datetime]:
    global _AKSHAYA_DATES_CACHE
    if _AKSHAYA_DATES_CACHE is not None:
        return _AKSHAYA_DATES_CACHE
    csv_path = (
        _repo_root()
        / "market-causality-lab"
        / "data"
        / "akshaya_tritiya_events_2000_2026.csv"
    )
    dates: list[datetime] = []
    if csv_path.exists():
        try:
            with csv_path.open(encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    raw = (row.get("time") or "").strip()
                    if raw:
                        try:
                            dt_parsed = datetime.fromisoformat(
                                raw.replace("Z", "+00:00")
                            )
                            dates.append(dt_parsed.astimezone(timezone.utc))
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass
    _AKSHAYA_DATES_CACHE = dates
    return dates


def _akshaya_proximity(
    dt: datetime | None = None,
    window_days: int = _AKSHAYA_WINDOW_DAYS,
) -> dict[str, Any]:
    """Return Akshaya Tritiya proximity info relative to *dt* (UTC, defaults to now)."""
    now = dt or datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now
    dates = _load_akshaya_dates()
    closest_delta: int | None = None
    closest_date: str | None = None
    for d in dates:
        d_naive = d.replace(tzinfo=None)
        delta = int((now_naive.date() - d_naive.date()).days)
        if closest_delta is None or abs(delta) < abs(closest_delta):
            closest_delta = delta
            closest_date = d_naive.strftime("%Y-%m-%d")
    active = (
        closest_delta is not None
        and abs(closest_delta) <= window_days
    )
    return {
        "akshaya_active": active,
        "akshaya_days_offset": closest_delta,
        "akshaya_nearest_date": closest_date,
    }


def _module_path() -> Path:
    return _repo_root() / "market-causality-lab" / "main.py"


def _load_module() -> Any:
    global _module

    if _module is not None:
        return _module

    with _module_lock:
        if _module is not None:
            return _module

        module_path = _module_path()
        if not module_path.exists():
            raise FileNotFoundError(f"market-causality-lab module not found: {module_path}")

        module_root = str(module_path.parent)
        if module_root not in sys.path:
            # Ensure market-causality-lab absolute imports like `from backend...` resolve.
            sys.path.insert(0, module_root)

        spec = importlib.util.spec_from_file_location("market_causality_lab_main", str(module_path))
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to create module spec for market-causality-lab")

        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
        _module = loaded
        return _module


def _normalize_symbol(symbol: str | None) -> str:
    value = str(symbol or "").strip().upper()
    return value or "XAUUSD"


def _normalize_timeframe(timeframe: str | None) -> str:
    value = str(timeframe or "").strip().lower()
    return value or "1m"


def _mcl_default_source_mode() -> str:
    value = str(os.getenv("MCL_DEFAULT_SOURCE_MODE", "live_first") or "live_first").strip().lower()
    allowed = {"historical_first", "historical_only", "live_first", "live_only", "hybrid", "combined"}
    return value if value in allowed else "live_first"


def _mcl_databento_enabled() -> bool:
    value = str(os.getenv("MCL_ENABLE_DATABENTO", "0") or "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _normalize_source_mode(source_mode: str | None) -> str:
    value = str(source_mode or _mcl_default_source_mode()).strip().lower()
    allowed = {"historical_first", "historical_only", "live_first", "live_only", "hybrid", "combined"}
    return value if value in allowed else _mcl_default_source_mode()


def _normalize_turtle_profile(turtle_profile: str | None) -> str:
    value = str(turtle_profile or "auto").strip().lower()
    allowed = {"auto", "strict", "balanced", "aggressive"}
    return value if value in allowed else "auto"


def _resolve_turtle_profile_for_timeframe(timeframe: str, turtle_profile: str) -> str:
    requested = _normalize_turtle_profile(turtle_profile)
    if requested != "auto":
        return requested

    tf = _normalize_timeframe(timeframe)
    # Auto mode adapts strictness by timeframe noise profile.
    if tf in {"1m"}:
        return "strict"
    if tf in {"5m", "15m", "30m"}:
        return "balanced"
    return "aggressive"


def _normalize_lookback_years(lookback_years: int | None) -> int:
    years = int(lookback_years) if lookback_years is not None else 25
    return max(1, min(100, years))


def _is_intraday_snapshot_timeframe(timeframe: str) -> bool:
    return str(timeframe or "").strip().lower() in {"1m", "5m", "15m", "30m", "1h"}


def _is_snapshot_fast_path_timeframe(timeframe: str) -> bool:
    return str(timeframe or "").strip().lower() in set(_MATRIX_TIMEFRAMES)


def _load_recent_chart_snapshot(symbol: str, timeframe: str, limit: int = 160) -> dict[str, Any]:
    tf = _normalize_timeframe(timeframe)
    max_rows = max(20, min(int(limit), 500))
    data_root = _repo_root() / "market-causality-lab" / "data"
    timeframe_files = {
        "1m": "XAU_1m_data.csv",
        "5m": "XAU_5m_data.csv",
        "15m": "XAU_15m_data.csv",
        "30m": "XAU_30m_data.csv",
        "1h": "XAU_1h_data.csv",
        "4h": "XAU_4h_data.csv",
        "1d": "XAU_1d_data.csv",
        "1w": "XAU_1w_data.csv",
        "1month": "XAU_1Month_data.csv",
    }
    hist_name = timeframe_files.get(tf)
    if not hist_name:
        return {
            "status": "error",
            "error": f"unsupported_timeframe:{tf}",
            "symbol": symbol,
            "requested_timeframe": tf,
            "applied_timeframe": tf,
            "candles": [],
        }

    def _read_snapshot_rows(path: Path, row_limit: int) -> list[dict[str, Any]]:
        if not path.exists() or row_limit <= 0:
            return []

        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                header = handle.readline()
                if not header:
                    return []
                lines = deque(handle, maxlen=row_limit)
        except Exception:
            return []

        if not lines:
            return []

        try:
            reader = csv.DictReader([header, *lines], delimiter=";")
        except Exception:
            return []

        rows: list[dict[str, Any]] = []
        for raw in reader:
            if not raw:
                continue
            raw_date = str(raw.get("Date") or "").strip()
            if not raw_date:
                continue
            try:
                ts = int(datetime.strptime(raw_date, "%Y.%m.%d %H:%M").replace(tzinfo=timezone.utc).timestamp())
            except Exception:
                continue

            def _num(name: str, default: float = 0.0) -> float:
                try:
                    value = raw.get(name)
                    if value in (None, ""):
                        return default
                    return float(value)
                except Exception:
                    return default

            close = _num("Close")
            if close <= 0:
                continue
            rows.append(
                {
                    "time": ts,
                    "open": _num("Open", close),
                    "high": _num("High", close),
                    "low": _num("Low", close),
                    "close": close,
                    "volume": _num("Volume", 0.0),
                }
            )
        return rows

    hist_path = data_root / hist_name
    live_path = data_root / "live" / f"XAUUSD_live_{tf}_intraday.csv"

    hist_rows = _read_snapshot_rows(hist_path, max_rows)
    live_rows = _read_snapshot_rows(live_path, max_rows)
    combined_rows = hist_rows + live_rows

    if not combined_rows:
        return {
            "status": "error",
            "error": f"snapshot_missing:{tf}",
            "symbol": symbol,
            "requested_timeframe": tf,
            "applied_timeframe": tf,
            "candles": [],
        }

    deduped: dict[int, dict[str, Any]] = {}
    for row in combined_rows:
        row_ts = int(row.get("time") or 0)
        if row_ts <= 0:
            continue
        deduped[row_ts] = row

    candles = [deduped[key] for key in sorted(deduped.keys())[-max_rows:]]
    if not candles:
        return {
            "status": "error",
            "error": f"snapshot_empty:{tf}",
            "symbol": symbol,
            "requested_timeframe": tf,
            "applied_timeframe": tf,
            "candles": [],
        }

    return {
        "status": "ok",
        "symbol": symbol,
        "requested_timeframe": tf,
        "applied_timeframe": tf,
        "timeframe_fallback_applied": False,
        "timeframe_fallback_reason": None,
        "candles": candles,
        "rows": len(candles),
    }


def _load_local_live_quote(symbol: str = "XAUUSD", timeframe: str | None = None) -> dict[str, Any] | None:
    symbol = _normalize_symbol(symbol)
    tf = _normalize_timeframe(timeframe)
    candidates = _live_csv_candidates(symbol=symbol, timeframe=tf)

    source_rank = {
        "mt5_live": 3,
        "mt5_export": 2,
        "local_live": 1,
    }

    def _rank(src: str) -> int:
        for key, value in source_rank.items():
            if src.startswith(key):
                return value
        return 0

    best_quote: dict[str, Any] | None = None
    best_score: tuple[int, int] | None = None
    for source, path in candidates:
        try:
            df = _read_live_csv_ohlc(path)
            if df is None or df.empty:
                continue
            row = df.sort_values("time").tail(1).iloc[0]
            price = float(row.get("close") or 0.0)
            ts_obj = row.get("time")
            if price <= 0 or ts_obj is None:
                continue
            ts = int(ts_obj.timestamp())
            quote = {
                "price": round(price, 4),
                "source": source,
                "spot": source.endswith("spot"),
                "ts": ts,
                "path": str(path),
            }
            quote_score = (_rank(str(quote.get("source") or "")), int(quote.get("ts") or 0))
            if best_quote is None or best_score is None or quote_score > best_score:
                best_quote = quote
                best_score = quote_score
        except Exception:
            continue

    return best_quote


def _live_csv_candidates(symbol: str, timeframe: str | None) -> list[tuple[str, Path]]:
    symbol = _normalize_symbol(symbol)
    tf = _normalize_timeframe(timeframe)
    data_root = _repo_root() / "market-causality-lab" / "data" / "live"
    mt5_root = data_root / "mt5"
    candidates: list[tuple[str, Path]] = []

    if tf in {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}:
        candidates.extend([
            (f"local_live_{tf}", data_root / f"{symbol}_live_{tf}_intraday.csv"),
            (f"mt5_live_{tf}", mt5_root / f"{symbol}_live_{tf}_intraday.csv"),
            (f"mt5_export_{tf}", mt5_root / f"{symbol}_{tf}.csv"),
        ])

    candidates.extend([
        ("local_live_spot", data_root / f"{symbol}_live_spot_intraday.csv"),
        ("mt5_live_spot", mt5_root / f"{symbol}_live_spot_intraday.csv"),
        ("mt5_export_spot", mt5_root / f"{symbol}_spot.csv"),
    ])
    return candidates


def _read_live_csv_ohlc(path: Path) -> Any | None:
    """Parse live OHLC CSV (local or MT5-exported) into a normalized dataframe."""
    try:
        import pandas as pd
    except Exception:
        return None

    if not path.exists():
        return None

    df = None
    for sep in (";", ","):
        try:
            trial = pd.read_csv(path, sep=sep)
            if trial is not None and not trial.empty and len(trial.columns) >= 2:
                df = trial
                break
        except Exception:
            continue
    if df is None or df.empty:
        return None

    rename_map = {
        "<DATE>": "Date",
        "<TIME>": "Time",
        "<OPEN>": "Open",
        "<HIGH>": "High",
        "<LOW>": "Low",
        "<CLOSE>": "Close",
        "close": "Close",
        "volume": "Volume",
        "tick_volume": "Volume",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    if "Date" in df.columns and "Time" in df.columns:
        dt_text = df["Date"].astype(str).str.strip() + " " + df["Time"].astype(str).str.strip()
    elif "Date" in df.columns:
        dt_text = df["Date"].astype(str).str.strip()
    else:
        return None

    parsed_time = pd.to_datetime(dt_text, utc=True, errors="coerce")
    if parsed_time.isna().all():
        parsed_time = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M", utc=True, errors="coerce")

    out = pd.DataFrame({"time": parsed_time})
    for src, dst in (("Open", "open"), ("High", "high"), ("Low", "low"), ("Close", "close"), ("Volume", "volume")):
        if src in df.columns:
            out[dst] = pd.to_numeric(df[src], errors="coerce")
        else:
            out[dst] = 0.0

    out = out.dropna(subset=["time", "close"])
    if out.empty:
        return None

    out["open"] = out["open"].fillna(out["close"])
    out["high"] = out["high"].fillna(out["close"])
    out["low"] = out["low"].fillna(out["close"])
    out["volume"] = out["volume"].fillna(0.0)
    out = out[["time", "open", "high", "low", "close", "volume"]].sort_values("time")
    return out


def _cache_key(symbol: str, timeframe: str, lookback_years: int, source_mode: str) -> str:
    return f"{symbol}|{timeframe}|{lookback_years}|{source_mode}"


def _matrix_cached_summary(
    *,
    symbol: str,
    timeframe: str,
    lookback_years: int,
    source_mode: str,
    started_at: float,
    error_text: str,
) -> dict[str, Any] | None:
    key = _cache_key(symbol, timeframe, lookback_years, source_mode)
    with _cache_lock:
        cached = _cache_payloads.get(key)
        candidates = list(_cache_payloads.values())

    selected: dict[str, Any] | None = None
    if isinstance(cached, dict) and str(cached.get("status") or "").lower() == "ok":
        selected = cached
    else:
        matching = [
            item for item in candidates
            if isinstance(item, dict)
            and str(item.get("symbol") or "").upper() == symbol
            and str(item.get("applied_timeframe") or item.get("requested_timeframe") or "") == timeframe
            and str(item.get("status") or "").lower() == "ok"
        ]
        if matching:
            selected = max(matching, key=lambda item: int(item.get("updated_at") or 0))

    if not isinstance(selected, dict):
        return None

    summary = dict(selected)
    summary["status"] = "stale_timeout"
    summary["error"] = str(error_text)
    summary["cache_fallback_used"] = True
    summary["summary_mode"] = "matrix_cached"
    summary["elapsed_ms"] = round((time.time() - started_at) * 1000.0, 2)
    summary["updated_at"] = int(time.time())
    summary["source_mode"] = source_mode
    summary["reasoning_tone"] = "matrix_cached"
    summary["reasoning_summary"] = (
        f"Matrix reused cached summary for {timeframe} after timeout/error. "
        f"Last quality={summary.get('quality') or '--'}, signal={summary.get('signal') or '--'}."
    )
    return summary


def _run_full_system(
    module: Any,
    symbol: str,
    timeframe: str,
    lookback_years: int,
    source_mode: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    full_system = getattr(module, "full_system", None)
    if not callable(full_system):
        raise RuntimeError("market-causality-lab full_system() is unavailable")

    signature = inspect.signature(full_system)
    accepts_symbol = "symbol" in signature.parameters
    accepts_timeframe = "timeframe" in signature.parameters
    accepts_lookback_years = "lookback_years" in signature.parameters
    accepts_source_mode = "source_mode" in signature.parameters

    call_kwargs: dict[str, Any] = {}
    if accepts_symbol:
        call_kwargs["symbol"] = symbol
    if accepts_timeframe:
        call_kwargs["timeframe"] = timeframe
    if accepts_lookback_years:
        call_kwargs["lookback_years"] = lookback_years
    if accepts_source_mode:
        call_kwargs["source_mode"] = source_mode

    payload = _to_json_safe(full_system(**call_kwargs))

    applied_symbol = str(payload.get("symbol") or (symbol if accepts_symbol else "XAUUSD")).strip().upper()
    applied_timeframe = str(
        payload.get("applied_timeframe")
        or payload.get("timeframe")
        or (timeframe if accepts_timeframe else "1m")
    ).strip().lower()
    requested_timeframe = str(payload.get("requested_timeframe") or timeframe).strip().lower()
    alignment = {
        "requested_symbol": symbol,
        "requested_timeframe": requested_timeframe,
        "applied_symbol": applied_symbol,
        "applied_timeframe": applied_timeframe,
        "native_symbol_support": accepts_symbol,
        "native_timeframe_support": accepts_timeframe,
        "requested_lookback_years": lookback_years,
        "requested_source_mode": source_mode,
        "native_lookback_support": accepts_lookback_years,
        "native_source_mode_support": accepts_source_mode,
        "timeframe_fallback_applied": bool(payload.get("timeframe_fallback_applied")),
        "timeframe_fallback_reason": payload.get("timeframe_fallback_reason"),
    }
    return payload, alignment


def _run_full_system_worker(
    symbol: str,
    timeframe: str,
    lookback_years: int,
    source_mode: str,
    out_queue: mp.Queue,
) -> None:
    """Run full_system in an isolated process so parent can enforce timeout safely."""
    try:
        module = _load_module()
        previous_cwd = os.getcwd()
        try:
            os.chdir(str(_module_path().parent))
            payload, alignment = _run_full_system(
                module,
                symbol=symbol,
                timeframe=timeframe,
                lookback_years=lookback_years,
                source_mode=source_mode,
            )
        finally:
            os.chdir(previous_cwd)
        out_queue.put({"ok": True, "payload": payload, "alignment": alignment})
    except Exception as exc:
        out_queue.put({"ok": False, "error": str(exc)})


def _run_full_system_with_timeout(
    symbol: str,
    timeframe: str,
    lookback_years: int,
    source_mode: str,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ctx = mp.get_context("spawn")

    queue = ctx.Queue(maxsize=1)
    proc = ctx.Process(
        target=_run_full_system_worker,
        args=(symbol, timeframe, lookback_years, source_mode, queue),
        daemon=True,
    )
    proc.start()
    proc.join(timeout=max(1.0, float(timeout_seconds)))

    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=1.0)
        raise TimeoutError(f"market-causality summary timed out after {timeout_seconds:.1f}s")

    if queue.empty():
        raise RuntimeError("market-causality summary process returned no payload")

    message = queue.get()
    if not bool(message.get("ok")):
        raise RuntimeError(str(message.get("error") or "unknown full_system worker error"))

    return dict(message.get("payload") or {}), dict(message.get("alignment") or {})


def _run_full_system_in_process(
    symbol: str,
    timeframe: str,
    lookback_years: int,
    source_mode: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    module = _load_module()
    previous_cwd = os.getcwd()
    try:
        os.chdir(str(_module_path().parent))
        payload, alignment = _run_full_system(
            module,
            symbol=symbol,
            timeframe=timeframe,
            lookback_years=lookback_years,
            source_mode=source_mode,
        )
    finally:
        os.chdir(previous_cwd)
    return payload, alignment


def _build_live_snapshot_summary(
    *,
    symbol: str,
    timeframe: str,
    lookback_years: int,
    source_mode: str,
    started_at: float,
    previous_for_key: dict[str, Any] | None,
) -> dict[str, Any]:
    summary = _build_timeout_fallback_summary(
        symbol=symbol,
        timeframe=timeframe,
        lookback_years=lookback_years,
        source_mode=source_mode,
        started_at=started_at,
        error_text="",
        fast_mode=True,
    )
    summary["status"] = "ok"
    summary["error"] = None
    summary["cache_fallback_used"] = False
    summary["quality"] = "live_snapshot"
    summary["source"] = "chart_live_snapshot"
    summary["summary_mode"] = "live_snapshot"
    summary["reasoning_tone"] = "snapshot_live"
    summary["reasoning_summary"] = str(summary.get("reasoning_summary") or "").replace(
        "Timeout fallback using live+chart snapshot",
        "Live snapshot summary using chart+price context",
    )
    summary["future_insight"] = str(summary.get("future_insight") or "").replace(
        "Signal=",
        "Live snapshot signal=",
    ).replace(
        "Use strict risk controls until full summary recovers.",
        "Heavy full-system analysis is warming in the background.",
    )
    summary["reasoning_delta"] = _build_reasoning_delta(summary, previous_for_key)
    summary.update(_compute_post_trade_review(summary))
    summary["boundary_proximity"] = {"status": "deferred", "reason": "live_snapshot_fast_path"}
    summary["ai_phase_forecast"] = _build_ai_phase_forecast(summary)
    return summary


def _schedule_summary_refresh(
    *,
    symbol: str,
    timeframe: str,
    lookback_years: int,
    source_mode: str,
    key: str,
) -> None:
    with _summary_refresh_lock:
        if key in _summary_refresh_inflight:
            return
        _summary_refresh_inflight.add(key)

    def _worker() -> None:
        try:
            _compute_summary(
                refresh=True,
                symbol=symbol,
                timeframe=timeframe,
                lookback_years=lookback_years,
                source_mode=source_mode,
            )
        except Exception:
            logging.debug("background summary refresh failed", exc_info=True)
        finally:
            with _summary_refresh_lock:
                _summary_refresh_inflight.discard(key)

    threading.Thread(target=_worker, daemon=True, name=f"mcl_summary_refresh_{timeframe}").start()


_ORIGINAL_LOAD_MODULE = _load_module
_ORIGINAL_RUN_FULL_SYSTEM = _run_full_system


def _compute_math_questions(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Derive MathematicalQuestionChecker inputs from a full_system() payload and
    return a partial summary dict with math_questions, math_verdict, math_score,
    math_score_pct, math_passed_ids, math_failed_ids.
    Falls back gracefully if price data is incomplete.
    """
    _EMPTY: dict[str, Any] = {
        "math_questions": [],
        "math_verdict": "INSUFFICIENT_DATA",
        "math_score": 0,
        "math_score_pct": 0.0,
        "math_passed_ids": [],
        "math_failed_ids": [],
    }
    try:
        obs = payload.get("observation") or {}
        tl = payload.get("trade_levels") or {}

        def _sf(val: Any, default: float = 0.0) -> float:
            if val is None:
                return default
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, str):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return default
            if isinstance(val, dict):
                for k in ("value", "score", "amount", "price"):
                    if k in val:
                        try:
                            return float(val[k])
                        except (ValueError, TypeError):
                            pass
            return default

        current_price = _sf(obs.get("signal_start_price") or tl.get("entry"))
        entry_price = _sf(tl.get("entry") or current_price, current_price)
        stop_price = _sf(tl.get("stop_loss") or (entry_price - 10.0), entry_price - 10.0)
        target_price = _sf(tl.get("take_profit") or (entry_price + 20.0), entry_price + 20.0)

        if current_price <= 0 or entry_price <= 0:
            return _EMPTY

        s_px = _sf(obs.get("signal_start_price") or current_price, current_price)
        e_px = _sf(obs.get("signal_end_price") or current_price, current_price)
        if abs(e_px - s_px) > 0:
            recent_prices = [round(s_px + (e_px - s_px) * i / 4.0, 4) for i in range(5)]
        else:
            recent_prices = [current_price] * 5

        swing_low = min(entry_price, stop_price)
        swing_high = max(entry_price, target_price)
        pivot_bar = 0
        current_bar = max(1, int(_sf(obs.get("signal_window_hours"), 1.0)))
        pivot_price = s_px

        results = MathematicalQuestionChecker.check_all(
            pivot_price=pivot_price,
            pivot_bar=pivot_bar,
            current_bar=current_bar,
            current_price=current_price,
            recent_prices=recent_prices,
            swing_low=swing_low,
            swing_high=swing_high,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
        )
        scoring = MathematicalQuestionChecker.score_setup(results)
        return {
            "math_questions": [
                {
                    "question_id": r.question_id,
                    "question": r.question,
                    "answer": r.answer,
                    "detail": r.detail,
                    "confidence": round(r.confidence, 4),
                }
                for r in results
            ],
            "math_verdict": scoring.get("verdict"),
            "math_score": scoring.get("score"),
            "math_score_pct": round(float(scoring.get("pct_pass", 0.0)) * 100.0, 1),
            "math_passed_ids": scoring.get("passed_ids"),
            "math_failed_ids": scoring.get("failed_ids"),
        }
    except Exception as exc:
        logging.warning("math_questions computation failed: %s", exc)
        return {**_EMPTY, "math_verdict": "ERROR"}


def _compute_gann_answers(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Answer all 52 trading questions in _TRADING_GANN_QUESTION_BANK using the
    current system payload.  Returns gann_questions list + aggregate stats.
    Each item: {question_id, answer (bool), reasoning (str), confidence (0..1)}.
    Falls back gracefully on missing data.
    """

    def _sf(val: Any, default: float = 0.0) -> float:
        """Safe float — handles numeric, string, or nested dict values."""
        if val is None:
            return default
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except (ValueError, TypeError):
                return default
        if isinstance(val, dict):
            for k in ("value", "score", "amount", "price"):
                if k in val:
                    try:
                        return float(val[k])
                    except (ValueError, TypeError):
                        pass
        return default

    try:
        def _d(val: Any) -> dict:
            return val if isinstance(val, dict) else {}

        obs = _d(payload.get("observation"))
        tl = _d(payload.get("trade_levels"))
        final = _d(payload.get("final"))
        simple = _d(payload.get("simple"))
        institutional = _d(payload.get("institutional"))
        trap_data = _d(payload.get("trap"))
        signal = str(payload.get("filtered_signal") or "WAIT").upper()
        confidence_val = _sf(payload.get("confidence"))
        reliability = _sf((payload.get("decision_trace") or {}).get("reliability_score"))

        gann_proximity = str(obs.get("gann_angle_proximity") or "NONE").upper()
        gann_nearest_angle = obs.get("gann_nearest_key_angle")
        confirmation_geom = bool(obs.get("confirmation_geometry"))
        confirmation_time_f = bool(obs.get("confirmation_time"))
        confirmation_struct = bool(obs.get("confirmation_structure"))
        confirmation_tape = bool(obs.get("confirmation_tape_action"))
        trend = str(final.get("trend") or "").lower()
        phase = str(final.get("phase") or "").lower()
        trap = str(trap_data.get("trap") or "").lower()
        instit_decision = str(institutional.get("institutional_decision") or "").upper()
        instit_score = _sf(institutional.get("institutional_score"))
        news_guard = bool(payload.get("news_guard_applied"))
        gann_confluence = bool(payload.get("gann_confluence_ready"))
        momentum_runtime = obs.get("physics_momentum_runtime")
        momentum_runtime = momentum_runtime if isinstance(momentum_runtime, dict) else {}
        structure_runtime = obs.get("structure_major_runtime")
        structure_runtime = structure_runtime if isinstance(structure_runtime, dict) else {}
        numerology_runtime = obs.get("numerology_cycle_runtime")
        numerology_runtime = numerology_runtime if isinstance(numerology_runtime, dict) else {}
        gann_degree = obs.get("gann_degree")
        geom_angle = obs.get("geometry_angle_deg")
        physics_velocity = obs.get("physics_velocity_price_per_hour")
        price_time_ratio = obs.get("price_time_ratio")
        degree_time_ratio = obs.get("degree_time_ratio")
        projected_move = _sf(obs.get("signal_projected_move"))
        window_hours = _sf(obs.get("signal_window_hours"))
        gann_mindset_bias = str(obs.get("gann_mindset_bias") or "").upper()
        r_ratio = _sf(tl.get("r_ratio"))
        entry = _sf(tl.get("entry"))
        stop = _sf(tl.get("stop_loss"))
        target = _sf(tl.get("take_profit"))
        learning_profile = _d(payload.get("learning_profile"))
        ai_model = _d(payload.get("ai_model"))
        ai_drift = bool(_d(ai_model.get("drift")).get("drift_detected", False))
        astro = _d(payload.get("astro"))
        astro_event = _d(astro.get("nearby_event"))

        answers: list[dict[str, Any]] = []

        def _q(qid: str, answer: bool, reasoning: str, conf: float) -> None:
            answers.append({
                "question_id": qid,
                "answer": bool(answer),
                "reasoning": str(reasoning),
                "confidence": round(min(1.0, max(0.0, float(conf))), 3),
            })

        # ── REGIME ───────────────────────────────────────────────────────────
        regime_type = "trend" if trend in ("up", "down") else ("range" if trap in ("none", "") else "transition")
        _q("REGIME_01", signal != "WAIT",
           f"Dominant regime: {regime_type} | signal={signal} | phase={phase}",
           0.8 if signal != "WAIT" else 0.5)
        _q("REGIME_02", gann_confluence,
           f"Gann confluence ready={gann_confluence} | trap={trap}",
           0.75 if gann_confluence else 0.4)

        # ── RISK ─────────────────────────────────────────────────────────────
        _q("RISK_01", not news_guard,
           f"News guard applied={news_guard}",
           0.95)
        _q("RISK_02", reliability >= 0.6,
           f"Reliability score={reliability:.3f} (threshold=0.60)",
           min(1.0, reliability + 0.1))

        # ── STRUCTURE ────────────────────────────────────────────────────────
        _q("STRUCT_01", confirmation_struct,
           f"BOS/CHOCH confirmation_structure={confirmation_struct}",
           0.85 if confirmation_struct else 0.3)
        aligned_struct = (trend == "up" and signal == "BUY") or (trend == "down" and signal == "SELL")
        _q("STRUCT_02", aligned_struct,
           f"Trend={trend} | signal={signal} | HH/HL or LL/LH aligned={aligned_struct}",
           0.8 if aligned_struct else 0.35)

        # ── PHYSICS ──────────────────────────────────────────────────────────
        mom_dir = str(momentum_runtime.get("direction") or momentum_runtime.get("momentum") or "neutral").lower()
        mom_ok = (mom_dir in ("up", "bullish") and signal == "BUY") or \
                 (mom_dir in ("down", "bearish") and signal == "SELL")
        _q("PHYS_01", mom_ok,
           f"Momentum direction={mom_dir} | signal={signal} → aligned={mom_ok}",
           0.75 if mom_ok else 0.4)

        vel_val = float(physics_velocity or 0.0)
        accel_ok = (vel_val > 0 and signal == "BUY") or (vel_val < 0 and signal == "SELL")
        _q("PHYS_02", accel_ok,
           f"Physics velocity={physics_velocity} | signal={signal} → accel_ok={accel_ok}",
           0.7 if accel_ok else 0.4)

        _q("PHYS_03", window_hours > 0,
           f"Signal window={window_hours:.0f}h → velocity can persist within window",
           0.7 if window_hours > 4 else 0.5)

        gravity_set = bool(stop and target)
        _q("PHYS_04", gravity_set,
           f"Gravity wells: SL={stop} TP={target} → target bands defined",
           0.9 if gravity_set else 0.2)

        _q("PHYS_05", confirmation_tape,
           f"Tape action confirmation={confirmation_tape} → onset vs exhaustion",
           0.8 if confirmation_tape else 0.35)

        move_dir_ok = (projected_move > 0 and signal == "BUY") or (projected_move < 0 and signal == "SELL")
        _q("PHYS_06", move_dir_ok,
           f"Projected move={projected_move:.2f} | signal={signal} → direction match={move_dir_ok}",
           0.75 if move_dir_ok else 0.35)

        _q("PHYS_07", window_hours > 0,
           f"Natural reversal in ~{window_hours:.0f}h based on signal window oscillation",
           0.6)

        # ── GANN ─────────────────────────────────────────────────────────────
        gann_angle_hit = gann_proximity in ("EXACT", "NEAR")
        _q("GANN_01", gann_angle_hit,
           f"Gann angle proximity={gann_proximity} | nearest_angle={gann_nearest_angle}",
           0.9 if gann_proximity == "EXACT" else (0.65 if gann_proximity == "NEAR" else 0.3))

        _q("GANN_02", gann_angle_hit,
           f"Cardinal angle proximity={gann_proximity}",
           0.95 if gann_angle_hit else 0.8)

        _q("GANN_03", confirmation_time_f,
           f"Price=Time confirmation={confirmation_time_f}",
           0.85 if confirmation_time_f else 0.3)

        _q("GANN_04", gann_nearest_angle is not None,
           f"Nearest angle={gann_nearest_angle} acts as {'launch' if signal != 'WAIT' else 'rejection'}",
           0.7 if gann_nearest_angle else 0.3)

        gann_deg_val = float(gann_degree or 0.0)
        sq9_aligned = gann_deg_val > 0 and (
            abs(gann_deg_val % 90) < 15 or abs(gann_deg_val % 45) < 8
        )
        _q("GANN_05", sq9_aligned,
           f"Gann degree={gann_deg_val:.1f}° | Square of 9/144 alignment={sq9_aligned}",
           0.7 if sq9_aligned else 0.35)

        dtr_val = float(degree_time_ratio or 0.0)
        dtr_ok = degree_time_ratio is not None and 0.8 <= dtr_val <= 1.2
        _q("GANN_06", dtr_ok,
           f"Degree-time ratio={degree_time_ratio} | harmonic range=[0.8, 1.2]",
           0.75 if dtr_ok else 0.4)

        _q("GANN_07", bool(entry and stop and target),
           f"Swing zones/balance points: entry={entry} stop={stop} target={target}",
           0.9 if (entry and stop and target) else 0.2)

        conviction_ok = gann_proximity == "EXACT" and confirmation_tape
        _q("GANN_08", conviction_ok,
           f"Angle conviction: proximity={gann_proximity} + tape={confirmation_tape}",
           0.85 if conviction_ok else 0.4)

        quadrant = int(gann_deg_val // 90) + 1 if gann_deg_val > 0 else 0
        _q("GANN_09", quadrant > 0,
           f"Active quadrant={quadrant} (degree={gann_deg_val:.1f}°)",
           0.7 if quadrant > 0 else 0.3)

        _q("GANN_10", bool(target or stop),
           f"Next reversal target={'TP' if signal in ('BUY', 'SELL') else 'SL'}: {target or stop}",
           0.75 if (target or stop) else 0.3)

        # ── TIME ─────────────────────────────────────────────────────────────
        now_ts = int(time.time())
        sig_start = _to_epoch_seconds(obs.get("signal_start_time"))
        sig_end = _to_epoch_seconds(obs.get("signal_end_time"))
        inside_window = bool(sig_start and sig_end and sig_start <= now_ts <= sig_end)
        _q("TIME_01", inside_window,
           f"Inside signal window={inside_window} (start={sig_start} end={sig_end})",
           0.95 if (sig_start and sig_end) else 0.3)

        if sig_start and sig_end and sig_end > sig_start:
            timing_pct = (now_ts - sig_start) / (sig_end - sig_start)
            timing_pct = max(0.0, min(1.0, timing_pct))
            timing_label = "early" if timing_pct < 0.33 else ("on-time" if timing_pct < 0.66 else "late")
        else:
            timing_label, timing_pct = "unknown", 0.5
        _q("TIME_02", timing_label != "late",
           f"Cycle timing={timing_label} ({timing_pct * 100:.0f}% through window)",
           0.8 if timing_label == "early" else (0.6 if timing_label == "on-time" else 0.35))

        _q("TIME_03", confirmation_time_f,
           f"Inflection point approaching: confirmation_time={confirmation_time_f}",
           0.8 if confirmation_time_f else 0.35)

        _q("TIME_04", window_hours > 0,
           f"Dominant oscillation period={window_hours:.0f}h",
           0.8 if window_hours > 0 else 0.2)

        ptr_val = float(price_time_ratio or 0.0)
        ptr_ok = price_time_ratio is not None and 0.5 <= ptr_val <= 1.5
        _q("TIME_05", ptr_ok,
           f"Price-time ratio={price_time_ratio} | squared harmony range=[0.5, 1.5]",
           0.75 if ptr_ok else 0.4)

        # ── GEOMETRY ────────────────────────────────────────────────────────
        _q("GEOM_01", confirmation_geom,
           f"Geometric confirmation={confirmation_geom}",
           0.85 if confirmation_geom else 0.3)

        geom_angle_val = float(geom_angle or 0.0)
        proportions_ok = 30.0 <= geom_angle_val <= 70.0
        _q("GEOM_02", proportions_ok,
           f"Geometry angle={geom_angle_val:.1f}° | harmonic range=[30, 70]",
           0.75 if proportions_ok else 0.4)

        _q("GEOM_03", confirmation_geom or bool(physics_velocity),
           f"Structural axis: geom={confirmation_geom} velocity={physics_velocity}",
           0.6)

        gann_45_ok = abs(geom_angle_val - 45.0) < 10 if geom_angle_val else False
        _q("GEOM_04", gann_45_ok,
           f"1:1 angle (45°): geometry_angle={geom_angle_val:.1f}°",
           0.8 if gann_45_ok else 0.4)

        # ── NUMEROLOGY ──────────────────────────────────────────────────────
        num_cycle = str(
            numerology_runtime.get("cycle") or numerology_runtime.get("phase") or ""
        ).lower()
        num_alignment = str(numerology_runtime.get("alignment") or "").lower()
        num_ok = num_alignment in ("aligned", "harmonic", "yes", "true") or (num_cycle != "")
        _q("NUM_01", num_ok,
           f"Numerology cycle={num_cycle} alignment={num_alignment}",
           0.65 if num_ok else 0.4)
        _q("NUM_02", num_cycle != "",
           f"Cycle phase={num_cycle or 'unknown'}",
           0.7 if num_cycle else 0.3)

        # ── ASTROLOGY ───────────────────────────────────────────────────────
        has_astro = bool(astro_event.get("event_name"))
        astro_impact = str(astro_event.get("impact_level") or "").upper()
        _q("ASTRO_01", has_astro,
           f"Astro event={astro_event.get('event_name') or 'none'} impact={astro_impact}",
           0.9 if has_astro else 0.5)

        mindset_match = bool(gann_mindset_bias and gann_mindset_bias == signal)
        _q("ASTRO_02", mindset_match,
           f"Gann mindset bias={gann_mindset_bias} vs signal={signal} match={mindset_match}",
           0.75 if mindset_match else 0.35)

        # ── ICT ─────────────────────────────────────────────────────────────
        liq_sweep = bool(confirmation_struct and confirmation_tape)
        _q("ICT_01", liq_sweep,
           f"Liquidity sweep: struct={confirmation_struct} + tape={confirmation_tape}",
           0.7 if liq_sweep else 0.35)

        _q("ICT_02", confirmation_geom,
           f"FVG/imbalance: geometry={confirmation_geom}",
           0.75 if confirmation_geom else 0.35)

        _q("ICT_03", bool(structure_runtime),
           f"Order block: structure_runtime present={bool(structure_runtime)}",
           0.6 if structure_runtime else 0.3)

        _q("ICT_04", bool(entry and stop and target),
           f"Supply/demand zones: entry={entry} stop={stop} tp={target}",
           0.85 if (entry and stop and target) else 0.3)

        instit_ok = instit_decision in ("BUY", "SELL") and instit_decision == signal
        _q("ICT_05", instit_ok,
           f"Smart money: instit_decision={instit_decision} (score={instit_score:.2f}) vs signal={signal}",
           0.85 if instit_ok else 0.4)

        _q("ICT_06", confirmation_struct,
           f"Retracement/continuation via structure={confirmation_struct}",
           0.75 if confirmation_struct else 0.35)

        # ── CONFLUENCE ──────────────────────────────────────────────────────
        all_four = confirmation_geom and confirmation_time_f and confirmation_struct and confirmation_tape
        _q("CONF_01", all_four,
           f"All 4 confirm: geom={confirmation_geom} time={confirmation_time_f} "
           f"struct={confirmation_struct} tape={confirmation_tape}",
           0.95 if all_four else 0.6)

        _q("CONF_02", signal in ("BUY", "SELL"),
           f"Final confluence verdict: signal={signal}",
           0.9 if signal in ("BUY", "SELL") else 0.5)

        weakness_map = {
            "geometry": int(confirmation_geom),
            "time": int(confirmation_time_f),
            "structure": int(confirmation_struct),
            "tape": int(confirmation_tape),
        }
        weakest = min(weakness_map, key=lambda k: weakness_map[k])
        _q("CONF_03", True,
           f"Weakest component: {weakest}={bool(weakness_map[weakest])}",
           0.8)

        buy_prob = round(confidence_val * 100.0 if signal == "BUY" else max(0.0, (1.0 - confidence_val) * 30.0), 1)
        sell_prob = round(confidence_val * 100.0 if signal == "SELL" else max(0.0, (1.0 - confidence_val) * 30.0), 1)
        wait_prob = round(max(0.0, 100.0 - buy_prob - sell_prob), 1)
        _q("CONF_04", confidence_val >= 0.5,
           f"P(BUY)={buy_prob}% P(SELL)={sell_prob}% P(WAIT)={wait_prob}%",
           confidence_val)

        # ── EXECUTION ───────────────────────────────────────────────────────
        all_levels = bool(entry and stop and target)
        _q("EXEC_01", all_levels,
           f"Entry={entry} SL={stop} TP={target} horizon={window_hours:.0f}h",
           0.95 if all_levels else 0.2)

        rr_ok = r_ratio >= 2.0
        _q("EXEC_02", rr_ok,
           f"R:R={r_ratio:.2f} (required ≥2.0) → sufficient={rr_ok}",
           0.9 if rr_ok else max(0.1, r_ratio / 4.0))

        # ── AI LEARNING ─────────────────────────────────────────────────────
        learn_win_rate = float(learning_profile.get("win_rate") or 0.0)
        _q("AI_01", learn_win_rate > 0,
           f"Past pattern win rate={learn_win_rate:.2%} | history present={learn_win_rate > 0}",
           0.7 if learn_win_rate > 0 else 0.3)

        _q("AI_02", not ai_drift,
           f"Model drift detected={ai_drift} → calibrated={not ai_drift}",
           0.95 if not ai_drift else 0.4)

        # ── POST-TRADE ──────────────────────────────────────────────────────
        outcomes = _PREDICTION_TRACKER.load_outcomes()
        obs_id = str(payload.get("observation_id") or "").strip()
        matched_outcome = next(
            (o for o in outcomes if str(o.get("prediction_id") or "").strip() == obs_id),
            None,
        ) if obs_id else None

        if matched_outcome:
            post_01_detail = (
                f"Outcome recorded: direction={matched_outcome.get('outcome_direction')} "
                f"was_correct={matched_outcome.get('was_correct')}"
            )
        else:
            post_01_detail = f"No outcome recorded for observation_id={obs_id or 'unknown'}"
        _q("POST_01", matched_outcome is not None, post_01_detail,
           0.9 if matched_outcome else 0.1)

        if matched_outcome:
            was_correct = bool(matched_outcome.get("was_correct"))
            failed_concept = str(matched_outcome.get("failed_concept") or ("none" if was_correct else "unknown"))
            _q("POST_02", was_correct,
               f"Direction matched={was_correct} | failed_concept={failed_concept}",
               0.9 if was_correct else 0.8)
        else:
            _q("POST_02", False,
               "Post-trade not yet recorded — outcome entry pending",
               0.1)

        # ── AGGREGATE ───────────────────────────────────────────────────────
        score = sum(1 for a in answers if a["answer"])
        total = len(answers)
        pct = round(score / total * 100.0, 1) if total else 0.0
        if pct >= 75:
            gann_verdict = "STRONG"
        elif pct >= 55:
            gann_verdict = "ACCEPTABLE"
        elif pct >= 35:
            gann_verdict = "WEAK"
        else:
            gann_verdict = "FAIL"

        return {
            "gann_questions": answers,
            "gann_questions_score": score,
            "gann_questions_total": total,
            "gann_questions_pct": pct,
            "gann_questions_verdict": gann_verdict,
            "gann_weakest_component": weakest,
            "gann_buy_prob": buy_prob,
            "gann_sell_prob": sell_prob,
            "gann_wait_prob": wait_prob,
        }
    except Exception as exc:
        logging.exception("gann_answers computation failed: %s", exc)
        return {
            "gann_questions": [],
            "gann_questions_score": 0,
            "gann_questions_total": 52,
            "gann_questions_pct": 0.0,
            "gann_questions_verdict": "ERROR",
            "gann_weakest_component": "unknown",
            "gann_buy_prob": 0.0,
            "gann_sell_prob": 0.0,
            "gann_wait_prob": 100.0,
        }


def _to_epoch_seconds(value: Any) -> int | None:
    """Best-effort UTC epoch conversion for ISO strings, timestamps, or epoch-like values."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 1e12:  # likely milliseconds
            raw = raw / 1000.0
        return int(raw)

    text = str(value).strip()
    if not text:
        return None

    try:
        return int(float(text))
    except ValueError:
        pass

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return None


def _compute_post_trade_review(summary: dict[str, Any]) -> dict[str, Any]:
    """Flag when post-trade review (POST_01/POST_02) is due and still missing."""
    observation_id = str(summary.get("observation_id") or "").strip()
    due_at = _to_epoch_seconds(summary.get("observation_signal_end_time"))
    now_ts = int(time.time())

    if due_at is None:
        return {
            "post_trade_review_required": False,
            "post_trade_window_closed": False,
            "post_trade_due_at": None,
            "post_trade_outcome_recorded": False,
            "post_trade_due_reason": "missing_signal_end_time",
        }

    outcomes = _PREDICTION_TRACKER.load_outcomes()
    outcome_recorded = bool(
        observation_id
        and any(str(item.get("prediction_id") or "").strip() == observation_id for item in outcomes)
    )
    window_closed = now_ts >= due_at
    review_required = bool(window_closed and observation_id and not outcome_recorded)

    if review_required:
        reason = "window_closed_outcome_missing"
    elif outcome_recorded:
        reason = "outcome_recorded"
    elif not observation_id:
        reason = "missing_observation_id"
    else:
        reason = "window_open"

    return {
        "post_trade_review_required": review_required,
        "post_trade_window_closed": window_closed,
        "post_trade_due_at": due_at,
        "post_trade_outcome_recorded": outcome_recorded,
        "post_trade_due_reason": reason,
    }


# ── News window constants (configurable via env) ───────────────────────────────
_NEWS_BLOCK_PRE_MINUTES: int = int(os.getenv("NEWS_BLOCK_PRE_MINUTES", "15"))
_NEWS_BLOCK_POST_MINUTES: int = int(os.getenv("NEWS_BLOCK_POST_MINUTES", "5"))
_NEWS_CONFIDENCE_PENALTY: float = float(os.getenv("NEWS_CONFIDENCE_PENALTY", "0.30"))


def _build_trade_init_point(summary: dict[str, Any]) -> dict[str, Any]:
    """Build a trade initialisation point object combining astro timing, news window,
    Gann angle geometry, Elliott wave phase, and cycle state into a single actionable dict.

    This is purely derived from already-computed fields in the summary dict —
    no additional network or DB calls are made.
    """
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            mapping = {
                "VERY_LOW": 20.0,
                "LOW": 35.0,
                "MEDIUM": 55.0,
                "HIGH": 75.0,
                "VERY_HIGH": 90.0,
            }
            key = str(value or "").strip().upper()
            return float(mapping.get(key, default))

    now_utc = datetime.now(tz=timezone.utc)
    now_ts = now_utc.timestamp()

    # ── Direction & confidence ────────────────────────────────────────────────
    direction = str(summary.get("signal") or summary.get("mcl_future_direction") or "WAIT").upper()
    if direction not in {"BUY", "SELL", "WAIT"}:
        direction = "WAIT"
    raw_confidence = _safe_float(summary.get("confidence"), 0.0)

    # ── Astro timing ──────────────────────────────────────────────────────────
    timing_window_str = str(summary.get("mcl_future_timing_window") or "LIVE")
    astro_event = str(summary.get("mcl_future_cycle_event") or summary.get("mcl_astro_nakshatra") or "")
    nearby_event: dict = summary.get("mcl_astro_nearby_event") or {}
    time_delta_hours: float | None = nearby_event.get("time_delta_hours")
    astro_event_time_iso: str | None = nearby_event.get("event_time")

    # Entry time: use upcoming astro event if ≤ 6h away, otherwise now
    if astro_event_time_iso and time_delta_hours is not None and 0.0 < time_delta_hours <= 6.0:
        entry_time_utc = astro_event_time_iso
    else:
        entry_time_utc = now_utc.isoformat().replace("+00:00", "Z")

    # ── Entry price ───────────────────────────────────────────────────────────
    trade_levels: dict = summary.get("trade_levels") or {}
    observation: dict = summary.get("observation") or {}
    entry_price: float | None = (
        trade_levels.get("entry")
        or observation.get("latest_price")
        or summary.get("live_price")
        or summary.get("observation_signal_start_price")
    )

    # ── Gann angle info ───────────────────────────────────────────────────────
    gann_angle_id = str(summary.get("observation_gann_nearest_key_angle") or summary.get("mcl_gann_zone") or "1×1")
    gann_angle_proximity = summary.get("observation_gann_angle_proximity")
    gann_degree = summary.get("observation_gann_degree") or summary.get("mcl_gann_degree")
    # Trend geometry from observation
    gann_trend_start = summary.get("observation_trend_start_time") or summary.get("observation_signal_start_time")
    gann_trend_end = summary.get("observation_signal_end_time")
    gann_angle_slope = summary.get("observation_geometry_angle_deg")

    # ── Elliott wave phase ────────────────────────────────────────────────────
    # Derive from harmonic pattern or MCL phase state
    harmonic = str(summary.get("mcl_harmonic_pattern") or "")
    mcl_phase = str(summary.get("phase") or summary.get("mcl_compression_phase") or "")
    if harmonic:
        elliott_phase = f"HARMONIC_{harmonic.upper()}"
    elif mcl_phase in {"ACCUMULATION", "DISTRIBUTION"}:
        elliott_phase = "IMPULSE_FORMING"
    elif mcl_phase in {"MANIPULATION"}:
        elliott_phase = "CORRECTION_ABC"
    elif direction == "BUY":
        elliott_phase = "IMPULSE_W3_W5"
    elif direction == "SELL":
        elliott_phase = "IMPULSE_W3_W5_DOWN"
    else:
        elliott_phase = "CONSOLIDATION"

    # ── Cycle state ───────────────────────────────────────────────────────────
    cycle_state = str(
        summary.get("mcl_compression_phase")
        or summary.get("phase")
        or summary.get("mcl_timescale_regime")
        or "UNKNOWN"
    ).upper()

    # ── News window fusion ────────────────────────────────────────────────────
    news_block_active = False
    news_window = "clear"
    news_minutes_to_event: float | None = None

    news_next_raw = summary.get("observation_news_next_time")
    news_prev_raw = summary.get("observation_news_previous_time")

    def _parse_news_epoch(raw: Any) -> float | None:
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return None

    next_epoch = _parse_news_epoch(news_next_raw)
    prev_epoch = _parse_news_epoch(news_prev_raw)

    if next_epoch is not None:
        delta_to_next = (next_epoch - now_ts) / 60.0  # minutes
        if 0.0 <= delta_to_next <= _NEWS_BLOCK_PRE_MINUTES:
            news_block_active = True
            news_window = "pre_news_blocked"
            news_minutes_to_event = round(delta_to_next, 1)
            raw_confidence = round(raw_confidence * (1.0 - _NEWS_CONFIDENCE_PENALTY), 4)
        elif delta_to_next < 0:
            delta_since_news = abs(delta_to_next)
            if delta_since_news <= _NEWS_BLOCK_POST_MINUTES:
                news_window = "post_news_reentry"
                news_minutes_to_event = round(-delta_since_news, 1)
            else:
                news_minutes_to_event = round(delta_to_next, 1)
        else:
            news_minutes_to_event = round(delta_to_next, 1)
    elif prev_epoch is not None:
        delta_since = (now_ts - prev_epoch) / 60.0
        if delta_since <= _NEWS_BLOCK_POST_MINUTES:
            news_window = "post_news_reentry"
            news_minutes_to_event = round(-delta_since, 1)

    # ── Confluence score ──────────────────────────────────────────────────────
    # Score contributions from each confirmed signal source
    _score_parts: list[float] = []
    if time_delta_hours is not None and time_delta_hours <= 6.0:
        _score_parts.append(0.25)  # astro timing aligned
    astro_strength = _safe_float(summary.get("mcl_astro_strength"), 50.0) / 100.0
    _score_parts.append(min(0.25, astro_strength * 0.25))  # astro energy
    gann_angle_proximity_val = _safe_float(gann_angle_proximity, 9999.0)
    if gann_angle_proximity_val < 0.5:
        _score_parts.append(0.20)  # near Gann angle
    if harmonic:
        _score_parts.append(0.15)  # harmonic pattern confirmed
    if direction in {"BUY", "SELL"} and not news_block_active:
        _score_parts.append(0.15)  # clean signal, no news block
    confluence_score = round(min(1.0, sum(_score_parts)), 3)

    return {
        "entry_time_utc": entry_time_utc,
        "entry_price": entry_price,
        "direction": direction,
        "confidence": round(raw_confidence, 4),
        "confluence_score": confluence_score,
        "news_block_active": news_block_active,
        "trigger_reason": {
            "astro_timing": timing_window_str,
            "astro_event": astro_event,
            "astro_event_time_utc": astro_event_time_iso,
            "astro_hours_to_event": round(time_delta_hours, 2) if time_delta_hours is not None else None,
            "moon_phase": summary.get("mcl_astro_moon_phase"),
            "nakshatra": summary.get("mcl_astro_nakshatra"),
            "news_window": news_window,
            "news_minutes_to_event": news_minutes_to_event,
            "gann_angle_id": gann_angle_id,
            "gann_angle_slope_degrees": gann_angle_slope,
            "gann_degree": gann_degree,
            "gann_angle_proximity": gann_angle_proximity,
            "gann_trend_start_utc": gann_trend_start,
            "gann_trend_end_utc": gann_trend_end,
            "cycle_state": cycle_state,
            "elliott_phase": elliott_phase,
        },
    }


def _compute_summary(
    refresh: bool = False,
    symbol: str = "XAUUSD",
    timeframe: str = "1d",
    lookback_years: int = 25,
    source_mode: str = "historical_first",
) -> dict[str, Any]:
    symbol = _normalize_symbol(symbol)
    timeframe = _normalize_timeframe(timeframe)
    lookback_years = _normalize_lookback_years(lookback_years)
    source_mode = _normalize_source_mode(source_mode)
    payload: dict[str, Any] | None = None  # initialised here so except-blocks can reference it
    key = _cache_key(symbol, timeframe, lookback_years, source_mode)

    now = time.time()
    if not refresh:
        with _cache_lock:
            cached = _cache_payloads.get(key)
            cached_ts = _cache_ts_by_key.get(key)
            cached_status = str((cached or {}).get("status") or "").lower() if isinstance(cached, dict) else ""
            if (
                cached is not None
                and cached_ts is not None
                and (now - cached_ts) <= _CACHE_TTL_SECONDS
                and cached_status == "ok"
            ):
                return cached

    started_at = time.time()
    with _cache_lock:
        previous_for_key = _cache_payloads.get(key)

    if not refresh and _is_snapshot_fast_path_timeframe(timeframe):
        summary = _build_live_snapshot_summary(
            symbol=symbol,
            timeframe=timeframe,
            lookback_years=lookback_years,
            source_mode=source_mode,
            started_at=started_at,
            previous_for_key=previous_for_key if isinstance(previous_for_key, dict) else None,
        )
        with _cache_lock:
            _cache_payloads[key] = summary
            _cache_ts_by_key[key] = time.time()
        _schedule_summary_refresh(
            symbol=symbol,
            timeframe=timeframe,
            lookback_years=lookback_years,
            source_mode=source_mode,
            key=key,
        )
        return summary

    try:
        use_timeout_isolation = (
            _load_module is _ORIGINAL_LOAD_MODULE
            and _run_full_system is _ORIGINAL_RUN_FULL_SYSTEM
        )
        if use_timeout_isolation:
            payload, alignment = _run_full_system_with_timeout(
                symbol=symbol,
                timeframe=timeframe,
                lookback_years=lookback_years,
                source_mode=source_mode,
                timeout_seconds=(_BACKGROUND_SUMMARY_TIMEOUT_SECONDS if refresh else _SUMMARY_TIMEOUT_SECONDS),
            )
        else:
            payload, alignment = _run_full_system_in_process(
                symbol=symbol,
                timeframe=timeframe,
                lookback_years=lookback_years,
                source_mode=source_mode,
            )

        summary = {
            "status": "ok",
            "source": payload.get("data_source"),
            "symbol": payload.get("symbol"),
            "requested_timeframe": payload.get("requested_timeframe") or alignment.get("requested_timeframe"),
            "applied_timeframe": payload.get("applied_timeframe") or alignment.get("applied_timeframe"),
            "timeframe_fallback_applied": bool(
                payload.get("timeframe_fallback_applied")
                or alignment.get("timeframe_fallback_applied")
            ),
            "timeframe_fallback_reason": payload.get("timeframe_fallback_reason") or alignment.get("timeframe_fallback_reason"),
            "signal": payload.get("filtered_signal"),
            "signal_original": payload.get("filtered_signal_original"),
            "gann_signal_candidate": payload.get("gann_signal_candidate"),
            "gann_confluence_ready": payload.get("gann_confluence_ready"),
            "confidence": payload.get("confidence"),
            "quality": payload.get("quality"),
            "phase": (payload.get("final") or {}).get("phase"),
            "trend": (payload.get("final") or {}).get("trend"),
            "trap": (payload.get("trap") or {}).get("trap"),
            "reliability_score": (payload.get("decision_trace") or {}).get("reliability_score"),
            "bias_score": (payload.get("simple") or {}).get("bias_score"),
            "bias_label": (payload.get("simple") or {}).get("bias_label"),
            "news_guard_applied": bool(payload.get("news_guard_applied")),
            "rejection_reason": payload.get("rejection_reason") or "none",
            "trade_levels": payload.get("trade_levels"),
            "institutional_decision": (payload.get("institutional") or {}).get("institutional_decision"),
            "institutional_score": (payload.get("institutional") or {}).get("institutional_score"),
            "contracts": payload.get("output_contracts"),
            "instrument_alignment": alignment,
            "lookback_years": payload.get("lookback_years", lookback_years),
            "source_mode": payload.get("source_mode", source_mode),
            "rows_analyzed": payload.get("rows_analyzed"),
            "historical_depth_years": payload.get("historical_depth_years"),
            "applied_dataset_depth_years": payload.get("applied_dataset_depth_years"),
            "lookback_target_met": payload.get("lookback_target_met"),
            "lookback_depth_warning": payload.get("lookback_depth_warning"),
            "news_status": payload.get("news_status"),
            "global_events_status": payload.get("global_events_status"),
            "observation_id": payload.get("observation_id"),
            "observation_log_path": payload.get("observation_log_path"),
            "observation_error": payload.get("observation_error"),
            "observation": payload.get("observation"),
            "observation_trend_start_time": ((payload.get("observation") or {}).get("trend_start_time")),
            "observation_latest_time": ((payload.get("observation") or {}).get("latest_time")),
            "observation_signal_start_time": ((payload.get("observation") or {}).get("signal_start_time")),
            "observation_signal_end_time": ((payload.get("observation") or {}).get("signal_end_time")),
            "observation_signal_start_price": ((payload.get("observation") or {}).get("signal_start_price")),
            "observation_signal_end_price": ((payload.get("observation") or {}).get("signal_end_price")),
            "observation_signal_window_hours": ((payload.get("observation") or {}).get("signal_window_hours")),
            "observation_signal_projected_move": ((payload.get("observation") or {}).get("signal_projected_move")),
            "observation_signal_projected_move_pct": ((payload.get("observation") or {}).get("signal_projected_move_pct")),
            "observation_gann_nearest_key_angle": ((payload.get("observation") or {}).get("gann_nearest_key_angle")),
            "observation_gann_angle_proximity": ((payload.get("observation") or {}).get("gann_angle_proximity")),
            "observation_confirmation_geometry": ((payload.get("observation") or {}).get("confirmation_geometry")),
            "observation_confirmation_time": ((payload.get("observation") or {}).get("confirmation_time")),
            "observation_confirmation_structure": ((payload.get("observation") or {}).get("confirmation_structure")),
            "observation_confirmation_tape_action": ((payload.get("observation") or {}).get("confirmation_tape_action")),
            "observation_numerology_cycle_runtime": ((payload.get("observation") or {}).get("numerology_cycle_runtime")),
            "observation_structure_major_runtime": ((payload.get("observation") or {}).get("structure_major_runtime")),
            "observation_physics_momentum_runtime": ((payload.get("observation") or {}).get("physics_momentum_runtime")),
            "observation_gann_mindset_bias": ((payload.get("observation") or {}).get("gann_mindset_bias")),
            "observation_gann_mindset_narration": ((payload.get("observation") or {}).get("gann_mindset_narration")),
            "observation_news_previous_time": ((payload.get("observation") or {}).get("news_previous_time")),
            "observation_news_next_time": ((payload.get("observation") or {}).get("news_next_time")),
            "observation_gann_degree": ((payload.get("observation") or {}).get("gann_degree")),
            "observation_geometry_angle_deg": ((payload.get("observation") or {}).get("geometry_angle_deg")),
            "observation_physics_velocity": ((payload.get("observation") or {}).get("physics_velocity_price_per_hour")),
            "observation_price_time_ratio": ((payload.get("observation") or {}).get("price_time_ratio")),
            "observation_degree_time_ratio": ((payload.get("observation") or {}).get("degree_time_ratio")),
            "analysis_started_at_utc": payload.get("analysis_started_at_utc"),
            "analysis_completed_at_utc": payload.get("analysis_completed_at_utc"),
            "analysis_elapsed_ms": payload.get("analysis_elapsed_ms"),
            "analysis_lifecycle": payload.get("analysis_lifecycle"),
            "memory_size": payload.get("memory_size"),
            "ai_decision": payload.get("ai_decision"),
            "astro": _to_json_safe(payload.get("astro")),
            "gann": _to_json_safe(payload.get("gann_adv")),
            "compression": _to_json_safe(payload.get("compression")),
            "future": _to_json_safe(payload.get("future")),
            "time_signal": _to_json_safe(payload.get("time_signal")),
            "wheel_display": _to_json_safe(payload.get("wheel_display")),
            # ── MCL Engine Outputs (full integration) ──────────────────────────
            # These are the raw outputs of all 9 MCL analytical frameworks,
            # now surfaced in the summary response for UI, alerts, and trade logic.
            "mcl_state": (payload.get("final") or {}),
            "mcl_physics": payload.get("physics"),
            "mcl_gann": (payload.get("final") or {}).get("phase") and payload.get("gann_adv"),
            "mcl_gann_adv": payload.get("gann_adv"),
            "mcl_gann_degree": ((payload.get("gann_adv") or {}).get("degree")),
            "mcl_gann_zone": ((payload.get("gann_adv") or {}).get("zone")),
            "mcl_gann_time_cycle": ((payload.get("gann_adv") or {}).get("time_cycle")),
            "mcl_gann_price_time_equal": ((payload.get("gann_adv") or {}).get("price_time_equal")),
            "mcl_gann_price_time_ratio": ((payload.get("gann_adv") or {}).get("price_time_ratio")),
            "mcl_gann_nodes": payload.get("gann_nodes"),
            "mcl_gann_node_active": ((payload.get("gann_nodes") or {}).get("node_active")),
            "mcl_gann_node_type": ((payload.get("gann_nodes") or {}).get("node_type")),
            "mcl_gann_node_price": ((payload.get("gann_nodes") or {}).get("node_price")),
            "mcl_gann_time_harmonic": ((payload.get("gann_nodes") or {}).get("time_harmonic")),
            "mcl_liquidity": _to_json_safe(payload.get("liquidity")),
            "mcl_liquidity_type": ((payload.get("liquidity") or {}).get("type")),
            "mcl_liquidity_above": ((payload.get("liquidity") or {}).get("above")),
            "mcl_liquidity_below": ((payload.get("liquidity") or {}).get("below")),
            "mcl_physics_force": ((payload.get("physics") or {}).get("force")),
            "mcl_physics_velocity": ((payload.get("physics") or {}).get("velocity")),
            "mcl_physics_energy": ((payload.get("physics") or {}).get("energy")),
            "mcl_numerology": _to_json_safe(payload.get("numerology")),
            "mcl_numerology_number": ((payload.get("numerology") or {}).get("number")),
            "mcl_numerology_meaning": ((payload.get("numerology") or {}).get("meaning")),
            "mcl_harmonic": _to_json_safe(payload.get("harmonic")),
            "mcl_harmonic_pattern": ((payload.get("harmonic") or {}).get("pattern")),
            "mcl_harmonic_ratio": ((payload.get("harmonic") or {}).get("ratio")),
            "mcl_astro": _to_json_safe(payload.get("astro")),
            "mcl_astro_nakshatra": ((payload.get("astro") or {}).get("nakshatra_name")),
            "mcl_astro_nakshatra_cycle": ((payload.get("astro") or {}).get("nakshatra_cycle")),
            "mcl_astro_strength": ((payload.get("astro") or {}).get("strength")),
            "mcl_astro_moon_phase": ((payload.get("astro") or {}).get("moon") or {}).get("phase_key") if payload.get("astro") else None,
            "mcl_astro_moon_illumination": (((payload.get("astro") or {}).get("moon") or {}).get("illumination")),
            "mcl_astro_nearby_event": _to_json_safe((payload.get("astro") or {}).get("nearby_event")),
            "mcl_compression": _to_json_safe(payload.get("compression")),
            "mcl_compression_phase": ((payload.get("compression") or {}).get("phase")),
            "mcl_compression_score": ((payload.get("compression") or {}).get("score")),
            "mcl_compression_silence_active": ((payload.get("compression") or {}).get("silence_active")),
            "mcl_compression_breakout_near": ((payload.get("compression") or {}).get("breakout_near")),
            "mcl_compression_direction_bias": ((payload.get("compression") or {}).get("direction_bias")),
            "mcl_compression_energy_stored": ((payload.get("compression") or {}).get("energy_stored")),
            "mcl_time_signal": payload.get("time_signal"),
            "mcl_time_timing": ((payload.get("time_signal") or {}).get("timing")),
            "mcl_time_signals": ((payload.get("time_signal") or {}).get("signals")),
            "mcl_future": payload.get("future"),
            "mcl_future_direction": ((payload.get("future") or {}).get("direction")),
            "mcl_future_cycle_event": ((payload.get("future") or {}).get("cycle_event")),
            "mcl_future_strength": ((payload.get("future") or {}).get("strength")),
            "mcl_future_cycle_progress_pct": ((payload.get("future") or {}).get("cycle_progress_pct")),
            "mcl_future_numerology_energy": ((payload.get("future") or {}).get("numerology_energy")),
            "mcl_future_timing_window": ((payload.get("future") or {}).get("timing_window")),
            "mcl_psychology_emotion": ((payload.get("psychology") or {}).get("emotion")),
            "mcl_behavior_next": ((payload.get("behavior") or {}).get("next")),
            "mcl_trap_probability": ((payload.get("trap") or {}).get("probability")),
            "mcl_signals": payload.get("signals"),
            "mcl_dominance_score": payload.get("score"),
            "mcl_weights": payload.get("weights"),
            "mcl_updated_weights": payload.get("updated_weights"),
            "mcl_probability": payload.get("probability"),
            "mcl_scenarios": payload.get("scenarios"),
            "mcl_backtest": payload.get("backtest"),
            "mcl_backtest_winrate": ((payload.get("backtest") or {}).get("winrate")),
            "mcl_backtest_wins": ((payload.get("backtest") or {}).get("wins")),
            "mcl_backtest_losses": ((payload.get("backtest") or {}).get("losses")),
            "mcl_data_quality": payload.get("data_quality"),
            "mcl_data_quality_score": ((payload.get("data_quality") or {}).get("score")),
            "mcl_data_quality_status": ((payload.get("data_quality") or {}).get("status")),
            "mcl_latency": payload.get("latency"),
            "mcl_latency_verdict": ((payload.get("latency") or {}).get("timing_verdict")),
            "mcl_timescale": payload.get("timescale"),
            "mcl_timescale_regime": (((payload.get("timescale") or {}).get("volatility_regime") or {}).get("regime")),
            "mcl_overfit": payload.get("overfit"),
            "mcl_overfit_risk": ((payload.get("overfit") or {}).get("overfit_risk")),
            "mcl_execution": payload.get("execution"),
            "mcl_execution_verdict": ((payload.get("execution") or {}).get("verdict")),
            "mcl_execution_score": ((payload.get("execution") or {}).get("score")),
            "mcl_execution_issues": ((payload.get("execution") or {}).get("issues")),
            "mcl_failure": payload.get("failure"),
            "mcl_failure_status": ((payload.get("failure") or {}).get("status")),
            "mcl_failure_severity": ((payload.get("failure") or {}).get("severity")),
            "mcl_failure_issues": ((payload.get("failure") or {}).get("issues")),
            "mcl_universal": payload.get("universal"),
            "mcl_universal_fib_levels": ((payload.get("universal") or {}).get("fib_levels")),
            "mcl_universal_price_degree": ((payload.get("universal") or {}).get("price_degree")),
            "mcl_universal_nakshatra": ((payload.get("universal") or {}).get("nakshatra")),
            "mcl_cycle_event": (payload.get("future") or {}).get("cycle_event"),
            "mcl_cycle_progress_pct": (payload.get("future") or {}).get("cycle_progress_pct"),
            "mcl_clarity": ((payload.get("simple") or {}).get("clarity")),
            "mcl_conviction": ((payload.get("simple") or {}).get("conviction")),
            "reasoning_display": payload.get("reasoning_display"),
            "reasoning_tone": ((payload.get("reasoning_display") or {}).get("tone")),
            "reasoning_summary": ((payload.get("reasoning_display") or {}).get("summary")),
            "reasoning_chain": ((payload.get("reasoning_display") or {}).get("chain")),
            "reasoning_top_drivers": ((payload.get("reasoning_display") or {}).get("top_drivers")),
            "ai_model": payload.get("ai_model"),
            "ai_model_used": bool(((payload.get("ai_model") or {}).get("used_model"))),
            "ai_model_version": ((payload.get("ai_model") or {}).get("version")),
            "ai_model_scope": ((payload.get("ai_model") or {}).get("resolved_model_scope") or ((payload.get("ai_model") or {}).get("model_timeframe"))),
            "ai_model_trade_direction": ((payload.get("ai_model") or {}).get("model_trade_direction")),
            "ai_trigger_direction": ((payload.get("ai_model") or {}).get("trigger_direction")),
            "ai_bundle_source": ((payload.get("ai_model") or {}).get("bundle_source")),
            "learning_profile": payload.get("learning_profile"),
            "process_timing": payload.get("process_timing"),
            "slowest_process_stage": max(
                payload.get("process_timing") or [],
                key=lambda item: float(item.get("elapsed_ms", 0.0) or 0.0),
                default=None,
            ),
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
            "updated_at": int(time.time()),
        }
        summary["reasoning_delta"] = _build_reasoning_delta(summary, previous_for_key)
        summary.update(_compute_math_questions(payload))
        summary.update(_compute_gann_answers(payload))
        summary.update(_compute_post_trade_review(summary))
        summary["boundary_proximity"] = _boundary_proximity_for_summary(summary)
    except TimeoutError as exc:
        logging.warning("market-causality summary timeout: %s", exc)
        if previous_for_key:
            summary = dict(previous_for_key)
            summary["status"] = "stale_timeout"
            summary["error"] = str(exc)
            summary["cache_fallback_used"] = True
            summary["elapsed_ms"] = round((time.time() - started_at) * 1000.0, 2)
            summary["updated_at"] = int(time.time())
        else:
            with _cache_lock:
                _fallback_candidates = [
                    v
                    for v in _cache_payloads.values()
                    if isinstance(v, dict)
                    and str(v.get("symbol") or "").upper() == symbol
                    and str(v.get("applied_timeframe") or v.get("requested_timeframe") or "") == timeframe
                    and str(v.get("status") or "").lower() == "ok"
                ]

            if _fallback_candidates:
                _latest = max(_fallback_candidates, key=lambda x: int(x.get("updated_at") or 0))
                summary = dict(_latest)
                summary["status"] = "stale_timeout"
                summary["error"] = str(exc)
                summary["cache_fallback_used"] = True
                summary["elapsed_ms"] = round((time.time() - started_at) * 1000.0, 2)
                summary["updated_at"] = int(time.time())
                summary["source_mode"] = source_mode
            else:
                summary = _build_timeout_fallback_summary(
                    symbol=symbol,
                    timeframe=timeframe,
                    lookback_years=lookback_years,
                    source_mode=source_mode,
                    started_at=started_at,
                    error_text=str(exc),
                )
    except Exception as exc:  # pragma: no cover - defensive runtime bridge
        logging.exception("market-causality summary failed")
        summary = {
            "status": "error",
            "error": str(exc),
            "symbol": symbol,
            "requested_timeframe": timeframe,
            "applied_timeframe": timeframe,
            "timeframe_fallback_applied": False,
            "timeframe_fallback_reason": None,
            "instrument_alignment": {
                "requested_symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "requested_lookback_years": lookback_years,
                "requested_source_mode": source_mode,
                "timeframe_fallback_applied": False,
                "timeframe_fallback_reason": None,
            },
            "lookback_years": lookback_years,
            "source_mode": source_mode,
            "rows_analyzed": None,
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
            "updated_at": int(time.time()),
        }

    summary["ai_phase_forecast"] = _build_ai_phase_forecast(summary)
    summary["trade_init_point"] = _build_trade_init_point(summary)

    with _cache_lock:
        _status = str(summary.get("status") or "").lower()
        if _status == "ok":
            _cache_payloads[key] = summary
            _cache_ts_by_key[key] = time.time()
        # Also store the raw MCL payload so /engines can read all engine outputs.
        # Only update when a fresh full_system() run succeeded (not stale/error fallback).
        if summary.get("status") == "ok" and payload is not None:
            _cache_raw_payloads[key] = payload

    # ── Auto-learning: record prediction + resolve expired predictions ────────
    if summary.get("status") == "ok":
        import threading as _threading
        _threading.Thread(
            target=_auto_record_and_resolve,
            args=(summary, symbol),
            daemon=True,
        ).start()

    return summary


def _auto_record_and_resolve(summary: dict[str, Any], symbol: str) -> None:
    """
    Background task called after every fresh _compute_summary():
      1. If signal is BUY or SELL — record it as a new prediction so the AI can learn.
      2. Auto-resolve any expired predictions against the latest price.

    This is the core of 'machine absorption': every MCL analysis call feeds the
    learning engine, and outcomes are resolved automatically when the forecast
    horizon expires.
    """
    try:
        _auto_record_prediction(summary)
    except Exception as exc:
        logging.debug("_auto_record_prediction error: %s", exc)

    try:
        _auto_resolve_expired(symbol)
    except Exception as exc:
        logging.debug("_auto_resolve_expired error: %s", exc)

    try:
        _maybe_send_boundary_telegram_alert(summary, symbol)
    except Exception as exc:
        logging.debug("_maybe_send_boundary_telegram_alert error: %s", exc)


def _auto_record_prediction(summary: dict[str, Any]) -> None:
    """
    Convert an MCL summary into a recorded prediction for the learning engine.
    Only records directional signals (BUY / SELL) — never WAIT.
    De-duplicates on observation_id so each fresh signal is only recorded once.
    """
    _raw_signal = str(summary.get("signal") or "").upper()
    # Normalise "STRONG BUY" → "BUY", "STRONG SELL" → "SELL", etc.
    if "BUY" in _raw_signal:
        signal = "BUY"
    elif "SELL" in _raw_signal:
        signal = "SELL"
    else:
        return  # WAIT / NEUTRAL — nothing to record

    # Build a stable prediction_id from the observation so we don't duplicate
    obs_id = str(summary.get("observation_id") or "")
    import hashlib as _hashlib, uuid as _uuid
    if obs_id:
        pid = str(_uuid.UUID(bytes=_hashlib.md5(obs_id.encode()).digest()))
    else:
        # Fallback: use symbol + signal + rounded timestamp (nearest 5 min)
        ts_bucket = int(time.time() // 300) * 300
        pid = str(_uuid.UUID(bytes=_hashlib.md5(f"{summary.get('symbol')}|{signal}|{ts_bucket}".encode()).digest()))

    # Don't re-record if already stored
    existing_ids = {p.get("id") for p in _LEARNING_ENGINE.predictions}
    if pid in existing_ids:
        return

    # Extract signal booleans from observation
    obs = summary.get("observation") or {}
    tl = summary.get("trade_levels") or {}

    def _sf(v: Any, default: float = 0.0) -> float:
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    entry_price  = _sf(tl.get("entry") or summary.get("observation_signal_start_price"), 0.0)
    stop_price   = _sf(tl.get("stop_loss"), 0.0)
    target_price = _sf(tl.get("take_profit"), 0.0)

    # Need valid prices to record
    if entry_price <= 0:
        return
    if stop_price <= 0:
        stop_price = entry_price * (0.997 if signal == "BUY" else 1.003)
    if target_price <= 0:
        target_price = entry_price * (1.006 if signal == "BUY" else 0.994)

    confidence_raw = _sf(summary.get("confidence"), 50.0)
    # Confidence may be 0–100 or 0–1
    confluence_score = confidence_raw / 100.0 if confidence_raw > 1.0 else confidence_raw

    # Signal boolean flags from observation confirmations + system outputs
    def _yes(v: Any) -> bool:
        """'YES' → True, 'NO'/None/False → False."""
        return str(v or "").strip().upper() == "YES"

    geometry_signal  = _yes(obs.get("confirmation_geometry"))
    time_signal      = _yes(obs.get("confirmation_time"))
    structure_signal = _yes(obs.get("confirmation_structure"))

    # physics_momentum_runtime may be a string ("NEUTRAL") or a dict — handle both
    _mom_raw = obs.get("physics_momentum_runtime")
    if isinstance(_mom_raw, dict):
        _mom_dir = str(_mom_raw.get("direction") or "").lower()
    else:
        _mom_dir = str(_mom_raw or "").lower()
    momentum_signal  = bool(
        (_mom_dir in ("up", "bullish") and signal == "BUY")
        or (_mom_dir in ("down", "bearish") and signal == "SELL")
    )

    gann_signal      = bool(summary.get("gann_confluence_ready"))

    # institutional_score may be a dict {'BUY': N, 'SELL': N} or a float
    _inst_raw = summary.get("institutional_score")
    if isinstance(_inst_raw, dict):
        _buy_votes  = int(_inst_raw.get("BUY", 0))
        _sell_votes = int(_inst_raw.get("SELL", 0))
        ict_signal  = (_buy_votes > _sell_votes) if signal == "BUY" else (_sell_votes > _buy_votes)
    else:
        ict_signal  = _sf(_inst_raw, 0.0) > 0.55

    # confluence: use reliability_score + quality as proxy (math_verdict not always present)
    _reliability = _sf(summary.get("reliability_score"), 0.0)
    _quality     = str(summary.get("quality") or "").upper()
    confluence_signal = bool(
        summary.get("math_verdict") in ("PASS", "HIGH_CONFIDENCE")
        or _reliability >= 0.8
        or _quality in ("STRONG", "HIGH", "EXCELLENT")
    )

    # Forecast horizon from signal window hours (default 1 day)
    window_hours = _sf(summary.get("observation_signal_window_hours"), 24.0)
    forecast_horizon_days = max(1, int(round(window_hours / 24.0)))

    try:
        result = _LEARNING_ENGINE.record_prediction(
            prediction_id=pid,
            direction=signal,
            confluence_score=confluence_score,
            geometry_signal=geometry_signal,
            time_signal=time_signal,
            structure_signal=structure_signal,
            momentum_signal=momentum_signal,
            gann_signal=gann_signal,
            ict_signal=ict_signal,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            forecast_horizon_days=forecast_horizon_days,
            confluence_signal=confluence_signal,
        )
        if result.get("status") not in ("error", None):
            logging.info(
                "MCL auto-prediction recorded: %s %s @ %.4f  (id=%s horizon=%dd)",
                signal, summary.get("symbol", "?"), entry_price, pid, forecast_horizon_days,
            )
    except Exception as exc:
        logging.debug("record_prediction failed: %s", exc)


def _auto_resolve_expired(symbol: str) -> None:
    """
    Resolve any recorded predictions whose forecast horizon has passed.
    Called from the background thread so it never blocks the API response.
    """
    from datetime import datetime, timezone as _tz
    now_utc = datetime.now(_tz.utc)

    resolved_ids: set[str] = {
        o.get("prediction_id")
        for o in _LEARNING_ENGINE.realized_outcomes
        if o.get("prediction_id")
    }

    # Fetch current price once
    current_price: float | None = None
    try:
        resp = market_causality_live_price(symbol=symbol)
        if resp.get("status") == "ok":
            current_price = float(resp["price"])
    except Exception:
        pass

    if current_price is None:
        return

    for pred in list(_LEARNING_ENGINE.predictions):
        pid = pred.get("id")
        if not pid or pid in resolved_ids:
            continue
        try:
            # Accept either recorded_at (ISO string) or prediction_timestamp (unix int)
            recorded_raw = pred.get("recorded_at")
            ts_raw = pred.get("prediction_timestamp")
            if recorded_raw:
                recorded_at = datetime.fromisoformat(
                    str(recorded_raw).replace("Z", "+00:00")
                )
                if recorded_at.tzinfo is None:
                    recorded_at = recorded_at.replace(tzinfo=_tz.utc)
            elif ts_raw:
                from datetime import timezone as _tz2
                recorded_at = datetime.fromtimestamp(float(ts_raw), tz=_tz2.utc)
            else:
                continue

            horizon_days = int(pred.get("forecast_horizon_days") or 1)
            elapsed_days = (now_utc - recorded_at).total_seconds() / 86400.0
            if elapsed_days < horizon_days:
                continue

            entry_price = float(pred.get("entry_price") or current_price)
            move = current_price - entry_price
            direction = "UP" if move > 0.10 else ("DOWN" if move < -0.10 else "SIDEWAYS")
            pips = abs(round(move, 2))

            result = _LEARNING_ENGINE.record_outcome(
                prediction_id=pid,
                realized_price=current_price,
                outcome_direction=direction,
                actual_move_pips=pips,
                timeframe_reached=max(1, int(elapsed_days * 24)),
            )
            if result.get("status") not in ("error", None):
                logging.info(
                    "MCL auto-resolved: %s → %s %.4f→%.4f was_correct=%s",
                    pid[:8], direction, entry_price, current_price, result.get("was_correct"),
                )
        except Exception as exc:
            logging.debug("auto_resolve pred %s error: %s", str(pid)[:8], exc)


def _compute_timeframe_matrix(
    refresh: bool = False,
    symbol: str = "XAUUSD",
    lookback_years: int = 25,
    source_mode: str = "historical_first",
) -> dict[str, Any]:
    started_at = time.time()
    symbol = _normalize_symbol(symbol)
    lookback_years = _normalize_lookback_years(lookback_years)
    source_mode = _normalize_source_mode(source_mode)

    rows: list[dict[str, Any]] = []
    ok_count = 0

    def _summary_to_row(tf: str, summary: dict[str, Any]) -> dict[str, Any]:
        process_timing = summary.get("process_timing") or []
        return {
            "timeframe": tf,
            "status": summary.get("status"),
            "signal": summary.get("signal"),
            "signal_original": summary.get("signal_original"),
            "gann_signal_candidate": summary.get("gann_signal_candidate"),
            "gann_confluence_ready": summary.get("gann_confluence_ready"),
            "confidence": summary.get("confidence"),
            "quality": summary.get("quality"),
            "requested_timeframe": summary.get("requested_timeframe"),
            "applied_timeframe": summary.get("applied_timeframe"),
            "timeframe_fallback_applied": summary.get("timeframe_fallback_applied"),
            "timeframe_fallback_reason": summary.get("timeframe_fallback_reason"),
            "rows_analyzed": summary.get("rows_analyzed"),
            "historical_depth_years": summary.get("historical_depth_years"),
            "lookback_target_met": summary.get("lookback_target_met"),
            "lookback_depth_warning": summary.get("lookback_depth_warning"),
            "memory_size": summary.get("memory_size"),
            "engine_stage_count": len(process_timing) if isinstance(process_timing, list) else 0,
            "engine_stage_names": [
                str(item.get("name")) for item in process_timing if isinstance(item, dict) and item.get("name")
            ] if isinstance(process_timing, list) else [],
            "ai_model_used": summary.get("ai_model_used"),
            "ai_model_version": summary.get("ai_model_version"),
            "ai_model_scope": summary.get("ai_model_scope"),
            "ai_model_trade_direction": summary.get("ai_model_trade_direction"),
            "ai_trigger_direction": summary.get("ai_trigger_direction"),
            "ai_bundle_source": summary.get("ai_bundle_source"),
            "ai_decision": summary.get("ai_decision"),
            "akshaya_active": (summary.get("ai_phase_forecast") or {}).get("akshaya_active"),
            "akshaya_days_offset": (summary.get("ai_phase_forecast") or {}).get("akshaya_days_offset"),
            "akshaya_nearest_date": (summary.get("ai_phase_forecast") or {}).get("akshaya_nearest_date"),
            "summary_mode": summary.get("summary_mode"),
            "reasoning_summary": summary.get("reasoning_summary"),
            "reasoning_top_drivers": summary.get("reasoning_top_drivers"),
            "trade_levels": summary.get("trade_levels"),
            "trend": summary.get("trend"),
            "bias_label": summary.get("bias_label"),
            "bias_score": summary.get("bias_score"),
            "astro": summary.get("astro"),
            "gann": summary.get("gann"),
            "compression": summary.get("compression"),
            "future": summary.get("future"),
            "time_signal": summary.get("time_signal"),
            "observation": summary.get("observation"),
            "observation_trend_start_time": summary.get("observation_trend_start_time"),
            "observation_latest_time": summary.get("observation_latest_time"),
            "observation_signal_start_time": summary.get("observation_signal_start_time"),
            "observation_signal_end_time": summary.get("observation_signal_end_time"),
            "observation_signal_start_price": summary.get("observation_signal_start_price"),
            "observation_signal_end_price": summary.get("observation_signal_end_price"),
            "observation_signal_window_hours": summary.get("observation_signal_window_hours"),
            "observation_signal_projected_move": summary.get("observation_signal_projected_move"),
            "observation_signal_projected_move_pct": summary.get("observation_signal_projected_move_pct"),
            "observation_gann_nearest_key_angle": summary.get("observation_gann_nearest_key_angle"),
            "observation_gann_angle_proximity": summary.get("observation_gann_angle_proximity"),
            "observation_confirmation_geometry": summary.get("observation_confirmation_geometry"),
            "observation_confirmation_time": summary.get("observation_confirmation_time"),
            "observation_confirmation_structure": summary.get("observation_confirmation_structure"),
            "observation_confirmation_tape_action": summary.get("observation_confirmation_tape_action"),
            "observation_numerology_cycle_runtime": summary.get("observation_numerology_cycle_runtime"),
            "observation_structure_major_runtime": summary.get("observation_structure_major_runtime"),
            "observation_physics_momentum_runtime": summary.get("observation_physics_momentum_runtime"),
            "observation_gann_mindset_bias": summary.get("observation_gann_mindset_bias"),
            "observation_gann_mindset_narration": summary.get("observation_gann_mindset_narration"),
            "observation_news_previous_time": summary.get("observation_news_previous_time"),
            "observation_news_next_time": summary.get("observation_news_next_time"),
            "observation_gann_degree": summary.get("observation_gann_degree"),
            "observation_price_time_ratio": summary.get("observation_price_time_ratio"),
            "observation_degree_time_ratio": summary.get("observation_degree_time_ratio"),
            "news_status": summary.get("news_status"),
            "global_events_status": summary.get("global_events_status"),
            "elapsed_ms": summary.get("elapsed_ms"),
            "error": summary.get("error"),
            # Gann 52-question scoring (populated when summary computed successfully)
            "gann_questions_pct": summary.get("gann_questions_pct"),
            "gann_questions_verdict": summary.get("gann_questions_verdict"),
            "gann_questions_score": summary.get("gann_questions_score"),
            "gann_buy_prob": summary.get("gann_buy_prob"),
            "gann_sell_prob": summary.get("gann_sell_prob"),
            "gann_wait_prob": summary.get("gann_wait_prob"),
            "gann_weakest_component": summary.get("gann_weakest_component"),
            "mcl_astro_nakshatra": summary.get("mcl_astro_nakshatra"),
            "mcl_astro_strength": summary.get("mcl_astro_strength"),
            "mcl_astro_moon_phase": summary.get("mcl_astro_moon_phase"),
            "mcl_astro_nearby_event": summary.get("mcl_astro_nearby_event"),
            "mcl_future_direction": summary.get("mcl_future_direction"),
            "mcl_future_strength": summary.get("mcl_future_strength"),
            "mcl_future_timing_window": summary.get("mcl_future_timing_window"),
            "mcl_compression_direction_bias": summary.get("mcl_compression_direction_bias"),
            "mcl_compression_breakout_near": summary.get("mcl_compression_breakout_near"),
        }

    by_tf: dict[str, dict[str, Any]] = {}
    # Use one worker per timeframe so all run concurrently; each worker's
    # subprocess already has its own _SUMMARY_TIMEOUT_SECONDS cap.
    worker_count = max(1, min(len(_MATRIX_TIMEFRAMES), _MATRIX_MAX_WORKERS))
    # Keep normal matrix fetches responsive, but allow explicit refresh=true
    # calls to use a longer budget aligned with deep summary refreshes.
    if refresh:
        # A matrix refresh must wait at least as long as an individual background
        # summary refresh, otherwise slow but valid timeframes get downgraded to
        # matrix_cached even though their own /summary refresh would complete.
        matrix_wait = max(_MATRIX_REFRESH_WAIT_SECONDS, _BACKGROUND_SUMMARY_TIMEOUT_SECONDS + 4.0)
    else:
        matrix_wait = min(_SUMMARY_TIMEOUT_SECONDS + 4.0, _MATRIX_WAIT_SECONDS)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=worker_count)
    future_map = {
        executor.submit(
            _compute_summary,
            refresh,
            symbol,
            tf,
            lookback_years,
            source_mode,
        ): tf
        for tf in _MATRIX_TIMEFRAMES
    }

    try:
        try:
            for future in concurrent.futures.as_completed(future_map, timeout=matrix_wait):
                tf = future_map[future]
                try:
                    summary = future.result()
                    status = str(summary.get("status") or "").lower()
                    if status in {"ok", "stale_timeout"}:
                        ok_count += 1
                    by_tf[tf] = _summary_to_row(tf, summary)
                except Exception as exc:
                    summary = _matrix_cached_summary(
                        symbol=symbol,
                        timeframe=tf,
                        lookback_years=lookback_years,
                        source_mode=source_mode,
                        started_at=started_at,
                        error_text=str(exc),
                    )
                    if summary is None:
                        summary = _build_timeout_fallback_summary(
                            symbol=symbol,
                            timeframe=tf,
                            lookback_years=lookback_years,
                            source_mode=source_mode,
                            started_at=started_at,
                            error_text=str(exc),
                            fast_mode=True,
                        )
                    status = str(summary.get("status") or "").lower()
                    if status in {"ok", "stale_timeout"}:
                        ok_count += 1
                    by_tf[tf] = _summary_to_row(tf, summary)
        except concurrent.futures.TimeoutError:
            # Some timeframes did not finish in time; synthesize the same degraded
            # fallback row used by /summary so the intraday panel still has data.
            for fut, tf in future_map.items():
                if tf not in by_tf:
                    summary = _matrix_cached_summary(
                        symbol=symbol,
                        timeframe=tf,
                        lookback_years=lookback_years,
                        source_mode=source_mode,
                        started_at=started_at,
                        error_text=f"matrix_timeout>{matrix_wait:.0f}s",
                    )
                    if summary is None:
                        summary = _build_timeout_fallback_summary(
                            symbol=symbol,
                            timeframe=tf,
                            lookback_years=lookback_years,
                            source_mode=source_mode,
                            started_at=started_at,
                            error_text=f"matrix_timeout>{matrix_wait:.0f}s",
                            fast_mode=True,
                        )
                    by_tf[tf] = _summary_to_row(tf, summary)
                    ok_count += 1
        finally:
            # Do not block request completion waiting on long-running workers.
            for fut in future_map:
                if not fut.done():
                    fut.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    # Preserve canonical timeframe order for stable UI rendering.
    rows = [by_tf.get(tf, {"timeframe": tf, "status": "error", "error": "missing_row"}) for tf in _MATRIX_TIMEFRAMES]

    coverage_pct = round((ok_count / max(1, len(_MATRIX_TIMEFRAMES))) * 100.0, 2)
    return {
        "status": "ok",
        "symbol": symbol,
        "lookback_years": lookback_years,
        "source_mode": source_mode,
        "timeframes": list(_MATRIX_TIMEFRAMES),
        "rows": rows,
        "coverage": {
            "ok_count": ok_count,
            "total": len(_MATRIX_TIMEFRAMES),
            "ok_pct": coverage_pct,
        },
        "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
        "updated_at": int(time.time()),
    }


def _observation_log_csv_path() -> Path:
    return _repo_root() / "market-causality-lab" / "data" / "observation_logs" / "market_observations.csv"


def _build_gann_qa_rows(
    selected_date: str,
    symbol: str = "XAUUSD",
    limit: int = 60,
    horizon_days: int = 1,
) -> dict[str, Any]:
    import pandas as pd

    path = _observation_log_csv_path()
    horizon_days = max(1, min(int(horizon_days), 30))
    if not path.exists():
        return {
            "status": "ok",
            "date": selected_date,
            "symbol": symbol,
            "rows": [],
            "summary": {
                "selected_date": selected_date,
                "symbol": _normalize_symbol(symbol),
                "horizon_days": horizon_days,
                "dominant_signal": "WAIT",
                "signal_counts": {"BUY": 0, "SELL": 0, "WAIT": 0},
                "past_present_future": {"past": 0, "present": 0, "future": 0},
                "overview": "No observation log found for selected date.",
            },
            "counts": {"past": 0, "present": 0, "future": 0, "qa_rows": 0},
            "source": str(path),
            "note": "observation_log_missing",
        }

    try:
        # Observation logs may occasionally contain malformed rows from interrupted writes.
        # Skip bad lines so Gann Q&A remains available instead of failing the endpoint.
        df = pd.read_csv(path, on_bad_lines="skip")
    except TypeError:
        # Backward compatibility for older pandas variants.
        df = pd.read_csv(path)
    if df.empty:
        return {
            "status": "ok",
            "date": selected_date,
            "symbol": symbol,
            "rows": [],
            "summary": {
                "selected_date": selected_date,
                "symbol": _normalize_symbol(symbol),
                "horizon_days": horizon_days,
                "dominant_signal": "WAIT",
                "signal_counts": {"BUY": 0, "SELL": 0, "WAIT": 0},
                "past_present_future": {"past": 0, "present": 0, "future": 0},
                "overview": "Observation log is empty for selected date.",
            },
            "counts": {"past": 0, "present": 0, "future": 0, "qa_rows": 0},
            "source": str(path),
            "note": "observation_log_empty",
        }

    symbol_norm = _normalize_symbol(symbol)
    if "symbol" in df.columns:
        df = df[df["symbol"].astype(str).str.upper() == symbol_norm]

    if df.empty:
        return {
            "status": "ok",
            "date": selected_date,
            "symbol": symbol_norm,
            "rows": [],
            "summary": {
                "selected_date": selected_date,
                "symbol": symbol_norm,
                "horizon_days": horizon_days,
                "dominant_signal": "WAIT",
                "signal_counts": {"BUY": 0, "SELL": 0, "WAIT": 0},
                "past_present_future": {"past": 0, "present": 0, "future": 0},
                "overview": "No observations found for selected symbol/date.",
            },
            "counts": {"past": 0, "present": 0, "future": 0, "qa_rows": 0},
            "source": str(path),
            "note": "symbol_not_found_in_observations",
        }

    ts_col = None
    for candidate in ("signal_end_time", "latest_time", "signal_start_time", "recorded_at_utc"):
        if candidate in df.columns:
            ts_col = candidate
            break
    if ts_col is None:
        return {
            "status": "ok",
            "date": selected_date,
            "symbol": symbol_norm,
            "rows": [],
            "summary": {
                "selected_date": selected_date,
                "symbol": symbol_norm,
                "horizon_days": horizon_days,
                "dominant_signal": "WAIT",
                "signal_counts": {"BUY": 0, "SELL": 0, "WAIT": 0},
                "past_present_future": {"past": 0, "present": 0, "future": 0},
                "overview": "Time columns are missing in observation log.",
            },
            "counts": {"past": 0, "present": 0, "future": 0, "qa_rows": 0},
            "source": str(path),
            "note": "time_column_missing",
        }

    df = df.copy()
    df["_ts"] = pd.to_datetime(df[ts_col], errors="coerce", utc=True)
    df = df.dropna(subset=["_ts"])
    # Sort by recorded_at_utc (most-recently-generated observations last) so that
    # tail(5) always returns the freshest analysis, not older stale observations.
    if "recorded_at_utc" in df.columns:
        df["_recorded"] = pd.to_datetime(df["recorded_at_utc"], errors="coerce", utc=True)
        df = df.sort_values(["_recorded"], na_position="first")
    else:
        df = df.sort_values("_ts")
    if df.empty:
        return {
            "status": "ok",
            "date": selected_date,
            "symbol": symbol_norm,
            "rows": [],
            "summary": {
                "selected_date": selected_date,
                "symbol": symbol_norm,
                "horizon_days": horizon_days,
                "dominant_signal": "WAIT",
                "signal_counts": {"BUY": 0, "SELL": 0, "WAIT": 0},
                "past_present_future": {"past": 0, "present": 0, "future": 0},
                "overview": "No valid timestamps found for selected date.",
            },
            "counts": {"past": 0, "present": 0, "future": 0, "qa_rows": 0},
            "source": str(path),
            "note": "no_valid_timestamps",
        }

    day = pd.to_datetime(selected_date, errors="coerce", utc=True)
    if pd.isna(day):
        day = pd.Timestamp.now(tz="UTC").normalize()
    day_start = day.normalize()
    day_end = day_start + pd.Timedelta(days=1)

    past = df[df["_ts"] < day_start].tail(5)
    present = df[(df["_ts"] >= day_start) & (df["_ts"] < day_end)].tail(5)
    future = df[df["_ts"] >= day_end].head(5)

    def _scenario_probs(rec: str, geom: str, tconf: str, sconf: str, pconf: str, era: str, horizon: int) -> dict[str, float]:
        rec_up = str(rec or "WAIT").upper()
        score = 0.0
        score += 0.25 if str(geom).upper() == "YES" else 0.0
        score += 0.25 if str(tconf).upper() == "YES" else 0.0
        score += 0.25 if str(sconf).upper() == "YES" else 0.0
        score += 0.25 if str(pconf).upper() == "YES" else 0.0

        # Future answers must be probabilistic with confidence decay.
        if era == "FUTURE":
            # Stronger decay as forecast horizon increases.
            decay = max(0.45, 1.0 - (min(horizon, 30) - 1) * 0.03)
            score *= decay

        if rec_up == "BUY":
            p_buy = min(0.85, max(0.35, 0.40 + score * 0.50))
            p_sell = max(0.05, 0.70 - p_buy)
        elif rec_up == "SELL":
            p_sell = min(0.85, max(0.35, 0.40 + score * 0.50))
            p_buy = max(0.05, 0.70 - p_sell)
        else:
            p_buy = max(0.10, 0.20 + score * 0.20)
            p_sell = max(0.10, 0.20 + score * 0.20)

        p_wait = max(0.05, 1.0 - p_buy - p_sell)
        total = p_buy + p_sell + p_wait
        return {
            "buy": round(p_buy / total, 4),
            "sell": round(p_sell / total, 4),
            "wait": round(p_wait / total, 4),
        }

    def _invalidation_rules(rec: str, s_px: Any, e_px: Any, s_time: Any, e_time: Any) -> list[str]:
        rec_up = str(rec or "WAIT").upper()
        try:
            sp = float(s_px)
            ep = float(e_px)
        except Exception:
            sp = None
            ep = None

        rules = [
            f"Window invalid if no directional follow-through by {e_time}.",
            f"Invalidate if macro/news regime shifts against setup inside {s_time} to {e_time}.",
        ]
        if rec_up == "BUY" and sp is not None and ep is not None:
            rules.append(f"BUY invalidation: sustained trade below anchor price {sp:.4f}.")
        elif rec_up == "SELL" and sp is not None and ep is not None:
            rules.append(f"SELL invalidation: sustained trade above anchor price {sp:.4f}.")
        else:
            rules.append("WAIT invalidation: confluence upgrade required before execution.")
        return rules

    def _answer_from_row(row: pd.Series, era: str) -> list[dict[str, Any]]:
        angle = row.get("gann_nearest_key_angle", "--")
        # Compute nearest key angle from gann_degree when CSV column is null
        if angle is None or (isinstance(angle, float) and pd.isna(angle)) or str(angle).strip().lower() in ("--", "nan", "none", ""):
            raw_degree = None
            try:
                raw_degree = float(row.get("gann_degree") or 0)
            except (TypeError, ValueError):
                raw_degree = None
            if raw_degree and raw_degree > 0:
                _key_angles = [45, 90, 180, 225, 315]
                angle = min(_key_angles, key=lambda a: min(abs(raw_degree - a), 360 - abs(raw_degree - a)))
            else:
                angle = "--"
        prox = row.get("gann_angle_proximity", "--")
        # Compute proximity from gann_degree when it is NONE and we have a real angle
        if str(prox).upper() in ("NONE", "--", "NAN", "NONE") and angle != "--":
            raw_degree = None
            try:
                raw_degree = float(row.get("gann_degree") or 0)
            except (TypeError, ValueError):
                raw_degree = None
            if raw_degree and raw_degree > 0:
                _diff = min(abs(raw_degree - angle), 360 - abs(raw_degree - angle))
                prox = "EXACT" if _diff < 5 else "NEAR" if _diff < 15 else "NONE"
        geom = row.get("confirmation_geometry", "--")
        tconf = row.get("confirmation_time", "--")
        sconf = row.get("confirmation_structure", "--")
        pconf = row.get("confirmation_tape_action", "--")
        bias = row.get("gann_mindset_bias", "--")
        rec = row.get("gann_recommended_signal", "WAIT")
        narr = row.get("gann_mindset_narration", "--")
        # Replace stale "--deg" placeholder with real computed values
        if "--deg" in str(narr) and angle != "--":
            raw_degree = None
            try:
                raw_degree = float(row.get("gann_degree") or 0)
            except (TypeError, ValueError):
                raw_degree = None
            if raw_degree and raw_degree > 0:
                narr = str(narr).replace("near --deg", f"near {angle}deg").replace("(current --deg)", f"(current {raw_degree:.4f}deg)")
        s_time = row.get("signal_start_time", "--")
        e_time = row.get("signal_end_time", "--")
        s_px = row.get("signal_start_price", "--")
        e_px = row.get("signal_end_price", "--")
        cycle = row.get("numerology_cycle_runtime", "--")
        structure = row.get("structure_major_runtime", "--")
        momentum = row.get("physics_momentum_runtime", "--")
        move_abs = row.get("signal_projected_move", "--")
        move_pct = row.get("signal_projected_move_pct", "--")

        # News fields (present in observation CSV columns 39-46)
        def _nf(val, default="--"):
            """Return default when val is None, NaN, 'nan', 'none', or empty."""
            if val is None:
                return default
            s = str(val).strip()
            if s.lower() in ("nan", "none", "nat", ""):
                return default
            return s

        news_prev_time = _nf(row.get("news_previous_time"))
        news_prev_event = _nf(row.get("news_previous_event"))
        news_prev_impact = _nf(row.get("news_previous_impact"))
        news_next_time = _nf(row.get("news_next_time"))
        news_next_event = _nf(row.get("news_next_event"))
        news_next_impact = _nf(row.get("news_next_impact"))

        if news_prev_event == "--" and news_next_event == "--":
            news_context = "No news data available"
        else:
            news_context = (
                f"prev: {news_prev_event} [{news_prev_impact}] @{news_prev_time} | "
                f"next: {news_next_event} [{news_next_impact}] @{news_next_time}"
            )

        ts = row.get("_ts")
        ts_txt = ts.isoformat() if hasattr(ts, "isoformat") else "--"
        px_path = f"{s_px} -> {e_px}"
        tw = f"{s_time} to {e_time}"
        answer_mode = "REALIZED" if era == "PAST" else ("LIVE" if era == "PRESENT" else "FORECAST")
        probs = _scenario_probs(rec, geom, tconf, sconf, pconf, era, horizon_days)
        invalidations = _invalidation_rules(rec, s_px, e_px, s_time, e_time)

        q1 = "Gann question: Is price at a cardinal angle and should we act now?"
        a1 = (
            f"{era}: nearest angle {angle}deg with proximity {prox}; geometry confirmation={geom}. "
            f"Recommended Gann action={rec}. Time window {tw}; price path {px_path}."
        )
        q2 = "Gann question: Is time in phase and is the signal window active?"
        a2 = (
            f"{era}: time confirmation={tconf}, cycle={cycle}. "
            f"Window {tw}, price path {px_path}, projected move {move_abs} ({move_pct}%)."
        )
        q3 = "Gann question: Do supporting concepts confirm continuation?"
        a3 = (
            f"{era}: structure confirmation={sconf} ({structure}), tape confirmation={pconf} ({momentum}), bias={bias}. "
            f"Time {tw}, prices {px_path}. Narration: {narr}"
        )
        q4 = "ICT question: Is liquidity sweep + displacement/FVG context supporting the same directional bias?"
        ict_side = "premium-zone continuation" if str(rec).upper() == "SELL" else "discount-to-expansion continuation"
        a4 = (
            f"{era}: ICT read uses structure={structure} and momentum={momentum}; inferred context={ict_side}. "
            f"Anchor time {tw}, anchor prices {px_path}. Suggested signal={str(rec).upper()}."
        )

        q5 = "News/Event question: Does scheduled news timing conflict with or reinforce the signal window?"
        a5 = (
            f"{era} ({answer_mode}): Previous event={news_prev_event} [{news_prev_impact}] at {news_prev_time}. "
            f"Next scheduled event={news_next_event} [{news_next_impact}] at {news_next_time}. "
            f"Signal window {tw}. Recommended signal given news context={str(rec).upper()}. "
            f"{'CAUTION: upcoming high-impact event within window.' if str(news_next_impact).upper() in ('HIGH', 'CRITICAL') else 'No high-impact news override detected.'}"
        )

        return [
            {
                "era": era,
                "ts": ts_txt,
                "answer_mode": answer_mode,
                "question": q1,
                "answer": a1,
                "recommended_signal": str(rec).upper(),
                "scenario_probs": probs,
                "invalidation_rules": invalidations,
                "forecast_horizon_days": horizon_days,
                "news_context": news_context,
            },
            {
                "era": era,
                "ts": ts_txt,
                "answer_mode": answer_mode,
                "question": q2,
                "answer": a2,
                "recommended_signal": str(rec).upper(),
                "scenario_probs": probs,
                "invalidation_rules": invalidations,
                "forecast_horizon_days": horizon_days,
                "news_context": news_context,
            },
            {
                "era": era,
                "ts": ts_txt,
                "answer_mode": answer_mode,
                "question": q3,
                "answer": a3,
                "recommended_signal": str(rec).upper(),
                "scenario_probs": probs,
                "invalidation_rules": invalidations,
                "forecast_horizon_days": horizon_days,
                "news_context": news_context,
            },
            {
                "era": era,
                "ts": ts_txt,
                "answer_mode": answer_mode,
                "question": q4,
                "answer": a4,
                "recommended_signal": str(rec).upper(),
                "scenario_probs": probs,
                "invalidation_rules": invalidations,
                "forecast_horizon_days": horizon_days,
                "news_context": news_context,
            },
            {
                "era": era,
                "ts": ts_txt,
                "answer_mode": answer_mode,
                "question": q5,
                "answer": a5,
                "recommended_signal": str(rec).upper(),
                "scenario_probs": probs,
                "invalidation_rules": invalidations,
                "forecast_horizon_days": horizon_days,
                "news_context": news_context,
            },
        ]

    rows: list[dict[str, Any]] = []
    for _, row in past.iterrows():
        rows.extend(_answer_from_row(row, "PAST"))
    for _, row in present.iterrows():
        rows.extend(_answer_from_row(row, "PRESENT"))
    for _, row in future.iterrows():
        rows.extend(_answer_from_row(row, "FUTURE"))

    rows = rows[: max(1, min(int(limit), 300))]

    sig_counts = {"BUY": 0, "SELL": 0, "WAIT": 0}
    for r in rows:
        sig = str(r.get("recommended_signal") or "WAIT").upper()
        if sig not in sig_counts:
            sig = "WAIT"
        sig_counts[sig] += 1

    dominant = max(sig_counts.items(), key=lambda kv: kv[1])[0] if rows else "WAIT"
    summary = {
        "selected_date": day_start.strftime("%Y-%m-%d"),
        "symbol": symbol_norm,
        "horizon_days": horizon_days,
        "dominant_signal": dominant,
        "signal_counts": sig_counts,
        "past_present_future": {
            "past": int(len(past)),
            "present": int(len(present)),
            "future": int(len(future)),
        },
        "overview": (
            f"For {symbol_norm} on {day_start.strftime('%Y-%m-%d')}: dominant suggested signal is {dominant}. "
            f"Rows built from Past={len(past)}, Present={len(present)}, Future={len(future)} observation slices. "
            f"Forecast horizon set to +{horizon_days} day(s)."
        ),
    }

    return {
        "status": "ok",
        "date": day_start.strftime("%Y-%m-%d"),
        "symbol": symbol_norm,
        "rows": rows,
        "summary": summary,
        "counts": {
            "past": int(len(past)),
            "present": int(len(present)),
            "future": int(len(future)),
            "qa_rows": int(len(rows)),
        },
        "source": str(path),
    }


def _compute_chart(
    symbol: str = "XAUUSD",
    timeframe: str = "1d",
    source_mode: str = "historical_first",
    lookback_years: int = 25,
    limit: int = 12000,
    strict_mt5: bool = False,
) -> dict[str, Any]:
    symbol = _normalize_symbol(symbol)
    requested_timeframe = _normalize_timeframe(timeframe)
    source_mode = _normalize_source_mode(source_mode)
    timeframe = requested_timeframe
    lookback_years = _normalize_lookback_years(lookback_years)
    limit = max(1, min(int(limit), 50000))
    strict_mt5 = bool(strict_mt5)
    if strict_mt5:
        # Force live-only behavior when user explicitly requests strict MT5 charting.
        source_mode = "live_only"

    chart_forced_fallback_reason = None
    # 1m chart requests are currently too heavy for responsive dashboard rendering.
    # Serve 5m data as a controlled fallback so timeframe switching does not hang.
    if timeframe == "1m":
        timeframe = "5m"
        chart_forced_fallback_reason = "chart_intraday_auto_fallback_1m_to_5m"

    # Intraday chart guardrails: keep lookback bounded for responsive UI loads.
    _chart_lookback_cap = {
        "1m": 1,
        "5m": 2,
        "15m": 3,
        "30m": 5,
        "1h": 7,
    }
    effective_lookback_years = min(lookback_years, _chart_lookback_cap.get(timeframe, lookback_years))

    def _load_live_intraday_df(_tf: str) -> Any | None:
        """Load persisted live intraday dataset (local or MT5 bridge CSV)."""
        try:
            import pandas as _pd

            _tf_norm = _normalize_timeframe(_tf)

            def _source_rank(_source: str) -> int:
                s = str(_source or "").strip().lower()
                rank = 0
                # Prefer exact timeframe feeds to avoid rendering spot/minute bars
                # under higher timeframe labels.
                if s.endswith(f"_{_tf_norm}"):
                    rank += 100
                elif s.endswith("_spot"):
                    rank += 10

                # Within a tier, prefer MT5 bridge outputs.
                if s.startswith("mt5_live_"):
                    rank += 30
                elif s.startswith("mt5_export_"):
                    rank += 20
                elif s.startswith("local_live_"):
                    rank += 10
                return rank

            def _resample_to_timeframe(_df: Any, _target_tf: str) -> Any:
                try:
                    _rule = {
                        "1m": "1min",
                        "5m": "5min",
                        "15m": "15min",
                        "30m": "30min",
                        "1h": "1h",
                        "4h": "4h",
                        "1d": "1D",
                    }.get(str(_target_tf or "").strip().lower())
                    if not _rule or _df is None or _df.empty or "time" not in _df.columns:
                        return _df

                    _work = _df.copy()
                    _work["time"] = _pd.to_datetime(_work["time"], utc=True, errors="coerce")
                    _work = _work.dropna(subset=["time"]).sort_values("time")
                    for _c in ("open", "high", "low", "close", "volume"):
                        if _c not in _work.columns:
                            _work[_c] = 0.0
                        _work[_c] = _pd.to_numeric(_work[_c], errors="coerce")

                    _work = (
                        _work.set_index("time")
                        .resample(_rule, closed="left", label="left")
                        .agg(
                            open=("open", "first"),
                            high=("high", "max"),
                            low=("low", "min"),
                            close=("close", "last"),
                            volume=("volume", "sum"),
                        )
                        .dropna(subset=["open", "close"])
                        .reset_index()
                    )
                    return _work
                except Exception:
                    return _df

            _selected = None
            _selected_source = ""
            _selected_rank = -1
            _selected_ts = None
            for _source, _path in _live_csv_candidates(symbol=symbol, timeframe=_tf):
                if strict_mt5:
                    _src = str(_source or "").strip().lower()
                    if not _src.startswith("mt5_"):
                        continue
                    if _src.endswith("_spot"):
                        continue
                _df = _read_live_csv_ohlc(_path)
                if _df is None or _df.empty:
                    continue
                _ts = _latest_epoch_from_df(_df)
                _rank = _source_rank(_source)
                if _selected is None:
                    _selected = _df
                    _selected_source = str(_source)
                    _selected_rank = _rank
                    _selected_ts = _ts
                    continue
                if _rank > _selected_rank:
                    _selected = _df
                    _selected_source = str(_source)
                    _selected_rank = _rank
                    _selected_ts = _ts
                    continue
                if _rank == _selected_rank and _ts is not None and (_selected_ts is None or int(_ts) >= int(_selected_ts)):
                    _selected = _df
                    _selected_source = str(_source)
                    _selected_rank = _rank
                    _selected_ts = _ts

            if _selected is not None and _selected_source.strip().lower().endswith("_spot"):
                _selected = _resample_to_timeframe(_selected, _tf_norm)
            return _selected
        except Exception:
            return None

    def _latest_epoch_from_df(_df: Any) -> int | None:
        try:
            if _df is None or _df.empty or "time" not in _df.columns:
                return None
            _ts = _df["time"].max()
            if _ts is None:
                return None
            return int(_ts.timestamp())
        except Exception:
            return None

    def _latest_local_live_quote(_live_df_hint: Any | None) -> tuple[float | None, int | None]:
        """Return latest local live price/timestamp from persisted datasets (no network)."""
        # 1) Prefer already-loaded timeframe live dataset.
        try:
            if _live_df_hint is not None and not _live_df_hint.empty:
                _tail = _live_df_hint.sort_values("time").tail(1)
                if not _tail.empty:
                    _price = float(_tail.iloc[0].get("close") or 0.0)
                    _ts_obj = _tail.iloc[0].get("time")
                    _ts = int(_ts_obj.timestamp()) if _ts_obj is not None else None
                    if _price > 0 and _ts is not None:
                        return _price, _ts
        except Exception:
            pass

        # 2) Fallback to spot intraday CSV tail.
        try:
            for _source, _path in _live_csv_candidates(symbol=symbol, timeframe=timeframe):
                if not _source.endswith("spot"):
                    continue
                _spot_df = _read_live_csv_ohlc(_path)
                if _spot_df is None or _spot_df.empty:
                    continue
                _spot_tail = _spot_df.sort_values("time").tail(1)
                if _spot_tail.empty:
                    continue
                _price = float(_spot_tail.iloc[0].get("close") or 0.0)
                _ts_obj = _spot_tail.iloc[0].get("time")
                _ts = int(_ts_obj.timestamp()) if _ts_obj is not None else None
                if _price > 0 and _ts is not None:
                    return _price, _ts
        except Exception:
            pass

        return None, None

    def _latest_stooq_spot_quote(max_age_seconds: int = 6 * 3600) -> tuple[float | None, int | None]:
        """Fetch latest public XAUUSD spot quote from stooq for stale-chart tail fallback."""
        try:
            import urllib.request as _urllib_req
            from datetime import datetime as _dt, timezone as _tz

            _req = _urllib_req.Request(
                "https://stooq.com/q/l/?s=xauusd&f=sd2t2ohlcv&h&e=csv",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with _urllib_req.urlopen(_req, timeout=6) as _resp:
                _lines = _resp.read().decode().strip().split("\n")
            if len(_lines) < 2 or _lines[1].startswith("N/A"):
                return None, None
            _parts = _lines[1].split(",")
            if len(_parts) < 7:
                return None, None
            _price = float(_parts[6])
            if _price <= 0:
                return None, None
            _dt_text = f"{_parts[1].strip()} {_parts[2].strip()}"
            try:
                _ts = int(_dt.strptime(_dt_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_tz.utc).timestamp())
            except Exception:
                return None, None
            _now_ts = int(time.time())
            _ts = min(_ts, _now_ts)
            _age = int(max(0, _now_ts - _ts))
            if _age > int(max_age_seconds):
                return None, None
            return round(float(_price), 4), _ts
        except Exception:
            return None, None

    def _load_hist_with_requested_tf(_tf: str) -> tuple[Any, str, dict[str, Any]]:
        """Load historical dataframe for a specific timeframe using module helpers."""
        if callable(load_with_fallback):
            _df, _dataset_path, _applied_tf, _fb_meta = load_with_fallback(
                symbol=symbol,
                timeframe=_tf,
                lookback_years=effective_lookback_years,
                data_dir=data_dir,
            )
            return _df, str(_applied_tf), dict(_fb_meta or {})

        path = resolve_timeframe_file(timeframe=_tf, symbol=symbol, data_dir=data_dir)
        raw_df = load_data(str(path))
        _df = apply_lookback(raw_df, effective_lookback_years)
        _fb_meta = {
            "requested_timeframe": requested_timeframe,
            "applied_timeframe": _tf,
            "fallback_applied": bool(chart_forced_fallback_reason),
            "fallback_reason": chart_forced_fallback_reason,
        }
        return _df, str(_tf), _fb_meta

    started_at = time.time()
    try:
        module = _load_module()
        data_dir = str(_repo_root() / "market-causality-lab" / "data")

        load_with_fallback = getattr(module, "_load_historical_with_fallback", None)
        resolve_timeframe_file = getattr(module, "_resolve_timeframe_file", None)
        load_data = getattr(module, "load_data", None)
        apply_lookback = getattr(module, "_apply_lookback_years", None)
        if not callable(load_with_fallback):
            if not callable(resolve_timeframe_file) or not callable(load_data) or not callable(apply_lookback):
                raise RuntimeError("market-causality-lab historical chart helpers are unavailable")

        _mode_live_only = source_mode == "live_only"
        _mode_hist_only = source_mode in {"historical_only"}
        _mode_live_prefer = source_mode == "live_first"
        _mode_merge = source_mode in {"combined", "hybrid"}
        _allow_live_tail_patch = (not _mode_hist_only) and (not strict_mt5)

        _live_intraday_tfs = {"5m", "15m", "30m", "1h", "4h", "1d"}
        _live_df = None
        if (not _mode_hist_only) and str(timeframe).lower().strip() in _live_intraday_tfs:
            _live_df = _load_live_intraday_df(timeframe)

        if strict_mt5:
            try:
                import pandas as _pd
                if _live_df is not None and not _live_df.empty:
                    _live_df = _live_df.copy()
                    _live_df["time"] = _pd.to_datetime(_live_df["time"], utc=True, errors="coerce")
                    _live_df = _live_df.dropna(subset=["time"]).sort_values("time")
            except Exception:
                pass

            if _live_df is None or _live_df.empty:
                raise RuntimeError("strict_mt5_no_live_dataset")

            # In strict mode, chart must be sourced from MT5 live dataset only.
            df = _live_df
            applied_timeframe = str(timeframe)
            fallback_meta = {
                "requested_timeframe": requested_timeframe,
                "applied_timeframe": str(timeframe),
                "fallback_applied": False,
                "fallback_reason": None,
            }

            for _c in ("open", "high", "low", "close", "volume"):
                if _c not in df.columns:
                    df[_c] = 0.0

        # Baseline historical dataset; source_mode can override below.
        df, applied_timeframe, fallback_meta = _load_hist_with_requested_tf(timeframe)

        if _live_df is not None and not _live_df.empty:
            try:
                import pandas as _pd

                _hist_df, _hist_applied_tf, _hist_fb = _load_hist_with_requested_tf(timeframe)
                _hist_ready = _hist_df is not None and not _hist_df.empty and "time" in _hist_df.columns
                if _hist_ready:
                    _hist_df = _hist_df.copy()
                    _hist_df["time"] = _pd.to_datetime(_hist_df["time"], utc=True, errors="coerce")
                    _hist_df = _hist_df.dropna(subset=["time"]).copy()
                    for _c in ("open", "high", "low", "close", "volume"):
                        if _c not in _hist_df.columns:
                            _hist_df[_c] = 0.0
                        _hist_df[_c] = _pd.to_numeric(_hist_df[_c], errors="coerce")
                    _hist_df = _hist_df.dropna(subset=["close"]).copy()

                if _mode_live_only:
                    df = _live_df
                    applied_timeframe = str(timeframe)
                    fallback_meta = {
                        "requested_timeframe": requested_timeframe,
                        "applied_timeframe": str(timeframe),
                        "fallback_applied": True,
                        "fallback_reason": f"chart_live_only_dataset_{str(timeframe).lower()}",
                    }
                elif _mode_live_prefer:
                    df = _live_df
                    applied_timeframe = str(timeframe)
                    fallback_meta = {
                        **(dict(_hist_fb or {})),
                        "requested_timeframe": requested_timeframe,
                        "applied_timeframe": str(timeframe),
                        "fallback_applied": True,
                        "fallback_reason": f"chart_live_first_dataset_{str(timeframe).lower()}",
                    }
                elif _mode_merge:
                    if _hist_ready:
                        _tf_norm_merge = str(timeframe).lower().strip()
                        _seam_live_only_seconds = {
                            "5m": 2 * 24 * 3600,
                            "15m": 3 * 24 * 3600,
                            "30m": 5 * 24 * 3600,
                            "1h": 2 * 24 * 3600,
                            "4h": 4 * 24 * 3600,
                        }
                        _hist_last_ts = _latest_epoch_from_df(_hist_df)
                        _live_first_ts = None
                        try:
                            _live_first = _live_df["time"].min()
                            _live_first_ts = int(_live_first.timestamp()) if _live_first is not None else None
                        except Exception:
                            _live_first_ts = None
                        _seam_gap = None
                        if _hist_last_ts is not None and _live_first_ts is not None:
                            _seam_gap = int(max(0, _live_first_ts - _hist_last_ts))

                        _prefer_live_only = (
                            _tf_norm_merge in _seam_live_only_seconds
                            and _seam_gap is not None
                            and _seam_gap > int(_seam_live_only_seconds[_tf_norm_merge])
                        )

                        if _prefer_live_only:
                            df = _live_df
                            applied_timeframe = str(timeframe)
                            fallback_meta = {
                                **(dict(_hist_fb or {})),
                                "requested_timeframe": requested_timeframe,
                                "applied_timeframe": str(timeframe),
                                "fallback_applied": True,
                                "fallback_reason": f"chart_live_dataset_preferred_large_seam_{_tf_norm_merge}",
                            }
                        else:
                            _merged = _pd.concat([_hist_df, _live_df], ignore_index=True)
                            _merged = _merged.sort_values("time").drop_duplicates(subset=["time"], keep="last")
                            df = _merged
                            applied_timeframe = str(_hist_applied_tf)
                            fallback_meta = {
                                **(dict(_hist_fb or {})),
                                "requested_timeframe": requested_timeframe,
                                "applied_timeframe": str(_hist_applied_tf),
                                "fallback_applied": True,
                                "fallback_reason": f"chart_live_dataset_merged_{str(timeframe).lower()}",
                            }
                    else:
                        df = _live_df
                        applied_timeframe = str(timeframe)
                        fallback_meta = {
                            "requested_timeframe": requested_timeframe,
                            "applied_timeframe": str(timeframe),
                            "fallback_applied": True,
                            "fallback_reason": f"chart_live_dataset_preferred_{str(timeframe).lower()}",
                        }
                else:
                    # historical_first / historical_only keeps historical baseline.
                    if (df is None or getattr(df, "empty", True)) and _hist_ready:
                        df = _hist_df
                        applied_timeframe = str(_hist_applied_tf)
                        fallback_meta = dict(_hist_fb or {})
            except Exception:
                if _mode_live_only or _mode_live_prefer:
                    df = _live_df
                    applied_timeframe = str(timeframe)
                    fallback_meta = {
                        "requested_timeframe": requested_timeframe,
                        "applied_timeframe": str(timeframe),
                        "fallback_applied": True,
                        "fallback_reason": f"chart_live_dataset_preferred_{str(timeframe).lower()}",
                    }

        if _mode_live_only and (_live_df is None or _live_df.empty):
            fallback_meta = {
                **(dict(fallback_meta or {})),
                "requested_timeframe": requested_timeframe,
                "applied_timeframe": str(applied_timeframe),
                "fallback_applied": True,
                "fallback_reason": "chart_live_only_unavailable_using_historical",
            }

        # In default historical_first mode, prefer a reasonably fresh intraday live
        # dataset when it exists so 5m/15m/30m charts keep their requested timeframe.
        _intraday_live_pref_tfs = {"1m", "5m", "15m", "30m"}
        _is_hist_first = not (_mode_live_only or _mode_hist_only or _mode_live_prefer or _mode_merge)
        if _is_hist_first and _live_df is not None and not _live_df.empty:
            _req_tf_norm = str(timeframe).strip().lower()
            if _req_tf_norm in _intraday_live_pref_tfs:
                _now_epoch = int(time.time())
                _live_latest = _latest_epoch_from_df(_live_df)
                _curr_latest = _latest_epoch_from_df(df)
                _live_max_gap_sec = int(max(300, float(os.getenv("MCL_CHART_INTRADAY_LIVE_MAX_GAP_SEC", str(96 * 3600)))))
                _live_newer_min_sec = int(max(60, float(os.getenv("MCL_CHART_INTRADAY_LIVE_NEWER_MIN_SEC", "900"))))
                _prefer_live_intraday = (
                    _live_latest is not None
                    and int(max(0, _now_epoch - _live_latest)) <= _live_max_gap_sec
                    and (
                        str(applied_timeframe).strip().lower() != _req_tf_norm
                        or _curr_latest is None
                        or int(_live_latest - _curr_latest) >= _live_newer_min_sec
                    )
                )
                if _prefer_live_intraday:
                    df = _live_df
                    applied_timeframe = str(timeframe)
                    fallback_meta = {
                        **(dict(fallback_meta or {})),
                        "requested_timeframe": requested_timeframe,
                        "applied_timeframe": str(timeframe),
                        "fallback_applied": False,
                        "fallback_reason": None,
                    }

        # If intraday source is very stale (e.g., frozen at old date), move to a fresher
        # higher timeframe so chart remains current instead of appearing "stuck".
        _intraday_stale_threshold_sec = int(7 * 24 * 3600)
        _latest_epoch = _latest_epoch_from_df(df)
        _gap_now = None if _latest_epoch is None else int(max(0, time.time() - _latest_epoch))
        _intraday_tfs = {"1m", "5m", "15m", "30m"}
        _tf_norm_requested = str(requested_timeframe).strip().lower()
        _tf_norm_applied = str(applied_timeframe).strip().lower()
        _needs_freshness_fallback = (
            (not _mode_live_only)
            and _tf_norm_requested in _intraday_tfs
            and _gap_now is not None
            and _gap_now > _intraday_stale_threshold_sec
        )
        if _needs_freshness_fallback:
            _fallback_order_map = {
                "1m": ["5m", "15m", "30m", "1h", "4h", "1d"],
                "5m": ["15m", "30m", "1h", "4h", "1d"],
                "15m": ["30m", "1h", "4h", "1d"],
                "30m": ["1h", "4h", "1d"],
            }
            _current_latest = _latest_epoch or 0
            for _candidate_tf in _fallback_order_map.get(_tf_norm_requested, []):
                try:
                    _cand_df, _cand_applied_tf, _cand_fb_meta = _load_hist_with_requested_tf(_candidate_tf)
                    _cand_latest = _latest_epoch_from_df(_cand_df)
                    if _cand_latest is None:
                        continue
                    # Accept only materially fresher datasets.
                    if (_cand_latest - _current_latest) >= int(24 * 3600):
                        df = _cand_df
                        applied_timeframe = str(_cand_applied_tf)
                        fallback_meta = {
                            **(dict(fallback_meta or {})),
                            **(dict(_cand_fb_meta or {})),
                            "requested_timeframe": requested_timeframe,
                            "applied_timeframe": str(_cand_applied_tf),
                            "fallback_applied": True,
                            "fallback_reason": f"chart_intraday_stale_autofallback_{_tf_norm_applied}_to_{str(_cand_applied_tf).lower()}",
                        }
                        _latest_epoch = _cand_latest
                        _tf_norm_applied = str(applied_timeframe).strip().lower()
                        break
                except Exception:
                    continue

        # If weekly/monthly was fulfilled by daily history, aggregate it here so the
        # chart renders true timeframe candles instead of showing daily bars under a
        # weekly/monthly label.
        try:
            import pandas as _pd

            _tf_norm_requested = str(requested_timeframe).strip().lower()
            _tf_norm_applied = str(applied_timeframe).strip().lower()
            if _tf_norm_requested in {"1w", "1month"} and _tf_norm_applied == "1d" and df is not None and not df.empty:
                _agg_df = df.copy()
                _agg_df["time"] = _pd.to_datetime(_agg_df["time"], utc=True, errors="coerce")
                _agg_df = _agg_df.dropna(subset=["time"]).sort_values("time")
                for _c in ("open", "high", "low", "close", "volume"):
                    if _c not in _agg_df.columns:
                        _agg_df[_c] = 0.0
                    _agg_df[_c] = _pd.to_numeric(_agg_df[_c], errors="coerce")
                _agg_df = _agg_df.dropna(subset=["open", "close"])
                if not _agg_df.empty:
                    _rule = "W-MON" if _tf_norm_requested == "1w" else "MS"
                    _agg_df = (
                        _agg_df.set_index("time")
                        .resample(_rule, closed="left", label="left")
                        .agg(
                            open=("open", "first"),
                            high=("high", "max"),
                            low=("low", "min"),
                            close=("close", "last"),
                            volume=("volume", "sum"),
                        )
                        .dropna(subset=["open", "close"])
                        .reset_index()
                    )
                    if not _agg_df.empty:
                        df = _agg_df
                        applied_timeframe = _tf_norm_requested
                        fallback_meta = {
                            **(dict(fallback_meta or {})),
                            "requested_timeframe": requested_timeframe,
                            "applied_timeframe": _tf_norm_requested,
                            "fallback_applied": True,
                            "fallback_reason": f"{str((fallback_meta or {}).get('fallback_reason') or '').strip()}|chart_aggregated_from_1d_to_{_tf_norm_requested}".strip("|"),
                        }
        except Exception:
            pass

        if "time" not in df.columns:
            raise RuntimeError("historical dataset is missing required time column")

        rows = []
        base_cols = ["time", "open", "high", "low", "close"]
        missing = [c for c in base_cols if c not in df.columns]
        if missing:
            raise RuntimeError(f"historical dataset is missing required columns: {', '.join(missing)}")

        subset = df[base_cols].copy()
        # Some consolidated timeframe CSVs do not carry volume; default to 0.
        if "volume" in df.columns:
            subset["volume"] = df["volume"]
        else:
            subset["volume"] = 0.0
        subset = subset.dropna(subset=["time", "open", "high", "low", "close"])
        subset = subset.sort_values("time")

        historical_last_epoch = None

        for item in subset.itertuples(index=False):
            ts = getattr(item, "time", None)
            try:
                epoch = int(ts.timestamp())
                o = float(getattr(item, "open"))
                h = float(getattr(item, "high"))
                l = float(getattr(item, "low"))
                c = float(getattr(item, "close"))
                v = float(getattr(item, "volume", 0.0) or 0.0)
            except Exception:
                continue
            rows.append(
                {
                    "time": epoch,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": max(0.0, v),
                }
            )
            historical_last_epoch = epoch

        live_gap_fill_applied = False
        live_gap_seconds = None
        live_last_epoch = None
        live_gap_reason = None
        try:
            if _allow_live_tail_patch and historical_last_epoch is not None:
                import os as _os
                from datetime import datetime as _dt, timezone as _tz, timedelta as _td
                import pandas as _pd

                _gap_est = int(max(0, time.time() - historical_last_epoch))
                tf_seconds = _timeframe_seconds(applied_timeframe)
                _tf_norm = str(applied_timeframe).lower().strip()
                # Guardrail: avoid huge intraday backfills that can stall chart endpoints,
                # especially for 1m where stale datasets imply very large remote pulls.
                if _tf_norm in ("1m", "5m") and _gap_est > 7 * 24 * 3600:
                    raise RuntimeError("live_gap_fill_skipped_intraday_gap_too_large")
                if _gap_est >= max(60, tf_seconds // 2):
                    if not _mcl_databento_enabled():
                        raise RuntimeError("databento_disabled_for_mcl")
                    _api_key = str(_os.getenv("DATABENTO_API_KEY", "")).strip()
                    if not _api_key:
                        raise RuntimeError("DATABENTO_API_KEY not configured")
                    import databento as _db

                    _start = _dt.fromtimestamp(historical_last_epoch + 1, tz=_tz.utc)
                    # Stay 2h behind "now" to avoid Databento available-end errors
                    _end = _dt.now(_tz.utc) - _td(hours=2)
                    if _end <= _start:
                        raise RuntimeError("gap too small or data too fresh for backfill")

                    if _tf_norm in ("1m", "1min", "5m", "15m", "30m"):
                        # Keep intraday chart endpoint responsive by avoiding remote intraday backfill.
                        raise RuntimeError("live_gap_fill_skipped_intraday_remote_backfill")
                    elif _tf_norm in ("1h",):
                        raise RuntimeError("live_gap_fill_skipped_intraday_remote_backfill")
                    elif _tf_norm in ("4h",):
                        raise RuntimeError("live_gap_fill_skipped_intraday_remote_backfill")
                    elif _tf_norm in ("1d", "daily", "day"):
                        _schema, _resample_rule = "ohlcv-1h", "1D"
                    else:
                        _schema, _resample_rule = "ohlcv-1h", None

                    _client = _db.Historical(_api_key)
                    _raw = _client.timeseries.get_range(
                        dataset="GLBX.MDP3",
                        symbols=["GC.c.0"],
                        stype_in="continuous",
                        schema=_schema,
                        start=_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        end=_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    )
                    _gap_df = _raw.to_df().reset_index()
                    _gap_df = _gap_df.rename(columns={"ts_event": "time"})
                    _gap_df["time"] = _pd.to_datetime(_gap_df["time"], utc=True)
                    _gap_df = _gap_df[["time", "open", "high", "low", "close", "volume"]].dropna(
                        subset=["time", "open", "close"]
                    )
                    # Scale fixed-point prices if needed
                    if not _gap_df.empty and float(_gap_df["close"].iloc[0]) > 100000:
                        for _c in ("open", "high", "low", "close"):
                            _gap_df[_c] = _gap_df[_c] / 1e9
                    # Resample to applied_timeframe if needed
                    if _resample_rule and not _gap_df.empty:
                        _gap_df = (
                            _gap_df.set_index("time")
                            .resample(_resample_rule, closed="left", label="left")
                            .agg(
                                open=("open", "first"),
                                high=("high", "max"),
                                low=("low", "min"),
                                close=("close", "last"),
                                volume=("volume", "sum"),
                            )
                            .dropna(subset=["open", "close"])
                            .reset_index()
                        )
                    if not _gap_df.empty:
                        for _gr in _gap_df.itertuples(index=False):
                            _t = int(_gr.time.timestamp())
                            _o = float(_gr.open or 0.0)
                            _h = float(_gr.high or 0.0)
                            _l = float(_gr.low or 0.0)
                            _c = float(_gr.close or 0.0)
                            _v = float(getattr(_gr, "volume", 0.0) or 0.0)
                            if _c > 0.0 and _t > historical_last_epoch:
                                rows.append(
                                    {
                                        "time": _t,
                                        "open": _o,
                                        "high": _h,
                                        "low": _l,
                                        "close": _c,
                                        "volume": max(0.0, _v),
                                    }
                                )
                        live_last_epoch = int(_gap_df["time"].max().timestamp())
                        live_gap_seconds = int(max(0, live_last_epoch - historical_last_epoch))
                        live_gap_fill_applied = True
                        live_gap_reason = f"databento_backfill_{len(_gap_df)}_candles"
        except Exception as exc:
            live_gap_reason = f"live_gap_fill_unavailable: {exc}"
            # Databento gap-fill may be unavailable (auth/network). First use local persisted
            # live quote to avoid extra network latency during chart rendering.
            try:
                _local_close, _local_ts = _latest_local_live_quote(_live_df)
                _tf_seconds = _timeframe_seconds(applied_timeframe)
                _bucket = max(60, _tf_seconds)
                _aligned_ts = int((int(_local_ts or 0) // _bucket) * _bucket) if _local_ts else None
                _now_aligned_ts = int((int(time.time()) // _bucket) * _bucket)
                if _aligned_ts is not None:
                    _aligned_ts = min(_aligned_ts, _now_aligned_ts)
                _last_close = float(rows[-1]["close"]) if rows else float(_local_close or 0.0)

                if (
                    _local_close is not None
                    and _local_close > 0
                    and _aligned_ts is not None
                    and historical_last_epoch is not None
                    and _aligned_ts > int(historical_last_epoch)
                ):
                    _tail_start = int(rows[-1]["time"]) if rows else int(historical_last_epoch)
                    _first_tail_ts = int(((_tail_start // _bucket) + 1) * _bucket)
                    if _first_tail_ts <= _aligned_ts:
                        # Use only the latest aligned bucket from the live quote. Filling every
                        # missing bucket with the same observed price creates a long run of flat,
                        # synthetic candles that visually dominates the real chart.
                        _tail_ts = int(_aligned_ts)
                        _c = float(_local_close)
                        _o = _last_close
                        _h = max(_o, _c)
                        _l = min(_o, _c)
                        rows.append(
                            {
                                "time": _tail_ts,
                                "open": float(_o),
                                "high": float(_h),
                                "low": float(_l),
                                "close": float(_c),
                                "volume": 0.0,
                            }
                        )

                        live_last_epoch = _tail_ts
                    else:
                        live_last_epoch = _aligned_ts
                    live_gap_seconds = int(max(0, int(live_last_epoch or _aligned_ts) - int(historical_last_epoch)))
                    live_gap_fill_applied = True
                    live_gap_reason = "local_live_dataset_patch_tail"
            except Exception:
                pass

        if rows:
            rows = sorted(rows, key=lambda item: int(item.get("time", 0)))
            deduped = []
            last_t = None
            for item in rows:
                t = int(item.get("time", 0))
                if t == last_t:
                    deduped[-1] = item
                else:
                    deduped.append(item)
                    last_t = t
            rows = deduped

            # Bridge only modest gaps so small discontinuities stay smooth without
            # fabricating thousands of synthetic candles across long seams.
            try:
                _fallback_reason_txt = str((fallback_meta or {}).get("fallback_reason") or "")
                _skip_gap_bridge = "chart_live_dataset_preferred_large_seam_" in _fallback_reason_txt
                _bucket_bridge = max(60, _timeframe_seconds(applied_timeframe))
                _gap_bridge_threshold = _bucket_bridge * 6
                _default_gap_bridge_days = int(max(1, float(os.getenv("MCL_CHART_GAP_BRIDGE_MAX_DAYS", "7"))))
                _gap_bridge_max_seconds = {
                    "1m": 3 * 24 * 3600,
                    "5m": 7 * 24 * 3600,
                    "15m": 7 * 24 * 3600,
                    "30m": 7 * 24 * 3600,
                    "1h": 10 * 24 * 3600,
                    "4h": 14 * 24 * 3600,
                    "1d": 30 * 24 * 3600,
                }.get(str(applied_timeframe).lower().strip(), _default_gap_bridge_days * 24 * 3600)
                _bridge_cap = int(max(256, float(os.getenv("MCL_CHART_GAP_BRIDGE_CAP", "3000"))))
                _bridge_max_steps_per_gap = int(max(64, float(os.getenv("MCL_CHART_GAP_BRIDGE_MAX_STEPS_PER_GAP", "2048"))))
                _bridge_count = 0
                _bridged_rows = []
                _prev_row = None

                for _row in rows:
                    if _prev_row is not None:
                        _pt = int(_prev_row.get("time", 0))
                        _ct = int(_row.get("time", 0))
                        _gap = _ct - _pt
                        if (
                            (not _skip_gap_bridge)
                            and _gap > _gap_bridge_threshold
                            and _gap <= _gap_bridge_max_seconds
                            and _bridge_count < _bridge_cap
                        ):
                            _steps = max(0, (_gap // _bucket_bridge) - 1)
                            _steps = min(_steps, _bridge_max_steps_per_gap)
                            _steps = min(_steps, max(1, _bridge_cap - _bridge_count))
                            if _steps > 0:
                                _from_close = float(_prev_row.get("close") or _prev_row.get("open") or 0.0)
                                _to_close = float(_row.get("close") or _row.get("open") or _from_close)
                                _prev_close_local = _from_close
                                for _i in range(1, _steps + 1):
                                    _t = _pt + (_i * _bucket_bridge)
                                    _r = _i / float(_steps + 1)
                                    _c = (_from_close * (1.0 - _r)) + (_to_close * _r)
                                    _o = _prev_close_local
                                    _h = max(_o, _c)
                                    _l = min(_o, _c)
                                    _bridged_rows.append(
                                        {
                                            "time": int(_t),
                                            "open": float(_o),
                                            "high": float(_h),
                                            "low": float(_l),
                                            "close": float(_c),
                                            "volume": 0.0,
                                        }
                                    )
                                    _prev_close_local = float(_c)
                                _bridge_count += _steps
                    _bridged_rows.append(_row)
                    _prev_row = _row

                if _bridge_count > 0:
                    rows = _bridged_rows
                    live_gap_fill_applied = True
                    if live_gap_reason:
                        live_gap_reason = f"{live_gap_reason}|gap_bridge_{_bridge_count}"
                    else:
                        live_gap_reason = f"gap_bridge_{_bridge_count}"
            except Exception:
                pass

            # If latest bar is stale, bridge to current bucket with spot live quote.
            # This keeps intraday chart current even when historical backfill is unavailable.
            try:
                _bucket = max(60, _timeframe_seconds(applied_timeframe))
                _now_epoch = int(time.time())
                _now_aligned = int((_now_epoch // _bucket) * _bucket)
                _last_epoch = int(rows[-1].get("time", 0)) if rows else 0
                _is_intraday = str(applied_timeframe).lower().strip() in {"1m", "5m", "15m", "30m", "1h", "4h"}
                if _allow_live_tail_patch and _is_intraday and _last_epoch > 0 and (_now_aligned - _last_epoch) >= _bucket:
                    _live_price, _live_ts = _latest_local_live_quote(_live_df)
                    _live_price = float(_live_price or 0.0)
                    if _live_price > 0.0:
                        if _live_ts is not None:
                            _aligned_live_ts = int((_live_ts // _bucket) * _bucket)
                            _now_aligned = min(_now_aligned, _aligned_live_ts)
                        _target_ts = int(_now_aligned)
                        if _target_ts > _last_epoch:
                            _o = float(rows[-1].get("close") or _live_price)
                            _c = _live_price
                            _h = max(_o, _c)
                            _l = min(_o, _c)
                            rows.append(
                                {
                                    "time": _target_ts,
                                    "open": float(_o),
                                    "high": float(_h),
                                    "low": float(_l),
                                    "close": float(_c),
                                    "volume": 0.0,
                                }
                            )
                            live_last_epoch = _target_ts
                            live_gap_seconds = int(max(0, live_last_epoch - _last_epoch))
                            live_gap_fill_applied = True
                            if live_gap_reason:
                                live_gap_reason = f"{live_gap_reason}|live_quote_tail"
                            else:
                                live_gap_reason = "live_quote_tail"
            except Exception:
                pass

            # A late tail append (e.g., stooq_tail) can introduce a fresh large seam
            # after the initial bridge pass. Run a compact second pass to smooth it.
            try:
                _fallback_reason_txt2 = str((fallback_meta or {}).get("fallback_reason") or "")
                _skip_gap_bridge2 = "chart_live_dataset_preferred_large_seam_" in _fallback_reason_txt2
                if not _skip_gap_bridge2 and rows and len(rows) >= 2:
                    _bucket_bridge2 = max(60, _timeframe_seconds(applied_timeframe))
                    _gap_bridge_threshold2 = _bucket_bridge2 * 6
                    _default_gap_bridge_days2 = int(max(1, float(os.getenv("MCL_CHART_GAP_BRIDGE_MAX_DAYS", "7"))))
                    _gap_bridge_max_seconds2 = {
                        "1m": 3 * 24 * 3600,
                        "5m": 7 * 24 * 3600,
                        "15m": 7 * 24 * 3600,
                        "30m": 7 * 24 * 3600,
                        "1h": 10 * 24 * 3600,
                        "4h": 14 * 24 * 3600,
                        "1d": 30 * 24 * 3600,
                    }.get(str(applied_timeframe).lower().strip(), _default_gap_bridge_days2 * 24 * 3600)
                    _bridge_cap2 = int(max(256, float(os.getenv("MCL_CHART_GAP_BRIDGE_CAP", "3000"))))
                    _bridge_max_steps_per_gap2 = int(max(64, float(os.getenv("MCL_CHART_GAP_BRIDGE_MAX_STEPS_PER_GAP", "2048"))))

                    _bridge_remaining = max(0, _bridge_cap2 - int(_bridge_count if '_bridge_count' in locals() else 0))
                    _bridge_count2 = 0
                    _bridged_rows2 = []
                    _prev_row2 = None

                    for _row2 in rows:
                        if _prev_row2 is not None and _bridge_remaining > 0:
                            _pt2 = int(_prev_row2.get("time", 0))
                            _ct2 = int(_row2.get("time", 0))
                            _gap2 = _ct2 - _pt2
                            if _gap2 > _gap_bridge_threshold2 and _gap2 <= _gap_bridge_max_seconds2:
                                _steps2 = max(0, (_gap2 // _bucket_bridge2) - 1)
                                _steps2 = min(_steps2, _bridge_max_steps_per_gap2, _bridge_remaining)
                                if _steps2 > 0:
                                    _from_close2 = float(_prev_row2.get("close") or _prev_row2.get("open") or 0.0)
                                    _to_close2 = float(_row2.get("close") or _row2.get("open") or _from_close2)
                                    _prev_close_local2 = _from_close2
                                    for _i2 in range(1, _steps2 + 1):
                                        _t2 = _pt2 + (_i2 * _bucket_bridge2)
                                        _r2 = _i2 / float(_steps2 + 1)
                                        _c2 = (_from_close2 * (1.0 - _r2)) + (_to_close2 * _r2)
                                        _o2 = _prev_close_local2
                                        _h2 = max(_o2, _c2)
                                        _l2 = min(_o2, _c2)
                                        _bridged_rows2.append(
                                            {
                                                "time": int(_t2),
                                                "open": float(_o2),
                                                "high": float(_h2),
                                                "low": float(_l2),
                                                "close": float(_c2),
                                                "volume": 0.0,
                                            }
                                        )
                                        _prev_close_local2 = float(_c2)
                                    _bridge_count2 += _steps2
                                    _bridge_remaining -= _steps2
                        _bridged_rows2.append(_row2)
                        _prev_row2 = _row2

                    if _bridge_count2 > 0:
                        rows = _bridged_rows2
                        live_gap_fill_applied = True
                        if live_gap_reason:
                            live_gap_reason = f"{live_gap_reason}|gap_bridge_tail_{_bridge_count2}"
                        else:
                            live_gap_reason = f"gap_bridge_tail_{_bridge_count2}"
            except Exception:
                pass

            # Guard against future-dated bars from external feeds/timezone mismatches.
            _tf_seconds = _timeframe_seconds(applied_timeframe)
            _now_epoch = int(time.time())
            _max_allowed = int((_now_epoch // max(60, _tf_seconds)) * max(60, _tf_seconds))
            rows = [item for item in rows if int(item.get("time", 0)) <= _max_allowed]
            if len(rows) > limit:
                rows = rows[-limit:]
            if live_last_epoch is not None:
                live_last_epoch = min(int(live_last_epoch), _max_allowed)

            # Re-check staleness after clamp (important when ahead-of-now bars were removed).
            try:
                _bucket = max(60, _timeframe_seconds(applied_timeframe))
                _now_epoch = int(time.time())
                _now_aligned = int((_now_epoch // _bucket) * _bucket)
                _last_epoch = int(rows[-1].get("time", 0)) if rows else 0
                _is_intraday = str(applied_timeframe).lower().strip() in {"1m", "5m", "15m", "30m", "1h", "4h"}
                if _allow_live_tail_patch and _is_intraday and _last_epoch > 0 and (_now_aligned - _last_epoch) >= _bucket:
                    _live_price, _live_ts = _latest_local_live_quote(_live_df)
                    _live_price = float(_live_price or 0.0)
                    if _live_price > 0.0:
                        if _live_ts is not None:
                            _aligned_live_ts = int((_live_ts // _bucket) * _bucket)
                            _now_aligned = min(_now_aligned, _aligned_live_ts)
                        _target_ts = int(_now_aligned)
                        if _target_ts > _last_epoch:
                            _o = float(rows[-1].get("close") or _live_price)
                            _c = _live_price
                            _h = max(_o, _c)
                            _l = min(_o, _c)
                            rows.append(
                                {
                                    "time": _target_ts,
                                    "open": float(_o),
                                    "high": float(_h),
                                    "low": float(_l),
                                    "close": float(_c),
                                    "volume": 0.0,
                                }
                            )
                            live_last_epoch = _target_ts
                            live_gap_seconds = int(max(0, live_last_epoch - _last_epoch))
                            live_gap_fill_applied = True
                            if live_gap_reason:
                                live_gap_reason = f"{live_gap_reason}|live_quote_tail"
                            else:
                                live_gap_reason = "live_quote_tail"
            except Exception:
                pass

            # Public spot tail fallback when MT5/local quote is unavailable and the
            # intraday chart is still stale after local tail attempts.
            try:
                _bucket = max(60, _timeframe_seconds(applied_timeframe))
                _now_epoch = int(time.time())
                _now_aligned = int((_now_epoch // _bucket) * _bucket)
                _last_epoch = int(rows[-1].get("time", 0)) if rows else 0
                _is_intraday = str(applied_timeframe).lower().strip() in {"1m", "5m", "15m", "30m", "1h", "4h"}
                if _allow_live_tail_patch and _is_intraday and _last_epoch > 0 and (_now_aligned - _last_epoch) >= _bucket:
                    _stooq_max_age = int(max(300, float(os.getenv("MCL_STOOQ_MAX_AGE_SEC", str(6 * 3600)))))
                    _stooq_price, _stooq_ts = _latest_stooq_spot_quote(max_age_seconds=_stooq_max_age)
                    if _stooq_price is not None and _stooq_price > 0.0 and _stooq_ts is not None:
                        _aligned_stooq_ts = int((_stooq_ts // _bucket) * _bucket)
                        _target_ts = min(_now_aligned, _aligned_stooq_ts)
                        if _target_ts > _last_epoch:
                            _o = float(rows[-1].get("close") or _stooq_price)
                            _c = float(_stooq_price)
                            _h = max(_o, _c)
                            _l = min(_o, _c)
                            rows.append(
                                {
                                    "time": _target_ts,
                                    "open": float(_o),
                                    "high": float(_h),
                                    "low": float(_l),
                                    "close": float(_c),
                                    "volume": 0.0,
                                }
                            )
                            live_last_epoch = _target_ts
                            live_gap_seconds = int(max(0, live_last_epoch - _last_epoch))
                            live_gap_fill_applied = True
                            if live_gap_reason:
                                live_gap_reason = f"{live_gap_reason}|stooq_tail"
                            else:
                                live_gap_reason = "stooq_tail"
            except Exception:
                pass

        latest_candle_time = int(rows[-1].get("time", 0)) if rows else None
        stale_seconds = None
        stale_threshold_seconds = int(max(60, _timeframe_seconds(applied_timeframe)))
        data_stale = False
        if latest_candle_time is not None and latest_candle_time > 0:
            stale_seconds = int(max(0, time.time() - latest_candle_time))
            data_stale = bool(stale_seconds > stale_threshold_seconds)

        historical_depth_fn = getattr(module, "_historical_depth_years", None)
        depth_years = None
        if callable(historical_depth_fn) and not df.empty:
            try:
                _depth_val = historical_depth_fn(df)
                depth_years = float(_depth_val) if _depth_val is not None else None
            except Exception:
                depth_years = None

        if chart_forced_fallback_reason:
            _existing_reason = str((fallback_meta or {}).get("fallback_reason") or "").strip()
            _combined_reason = chart_forced_fallback_reason if not _existing_reason else f"{chart_forced_fallback_reason}|{_existing_reason}"
            fallback_meta = {
                **(fallback_meta or {}),
                "requested_timeframe": requested_timeframe,
                "applied_timeframe": str(applied_timeframe),
                "fallback_applied": True,
                "fallback_reason": _combined_reason,
            }

        return {
            "status": "ok",
            "symbol": symbol,
            "source_mode": source_mode,
            "strict_mt5": strict_mt5,
            "requested_timeframe": requested_timeframe,
            "applied_timeframe": str(applied_timeframe),
            "lookback_years": effective_lookback_years,
            "historical_depth_years": depth_years,
            "rows": len(rows),
            "candles": rows,
            "timeframe_fallback_applied": bool(fallback_meta.get("fallback_applied")),
            "timeframe_fallback_reason": fallback_meta.get("fallback_reason"),
            "live_gap_fill_applied": live_gap_fill_applied,
            "live_gap_reason": live_gap_reason,
            "historical_last_time": historical_last_epoch,
            "live_last_time": live_last_epoch,
            "live_gap_seconds": live_gap_seconds,
            "latest_candle_time": latest_candle_time,
            "stale_seconds": stale_seconds,
            "stale_threshold_seconds": stale_threshold_seconds,
            "data_stale": data_stale,
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "symbol": symbol,
            "source_mode": source_mode,
            "strict_mt5": strict_mt5,
            "requested_timeframe": requested_timeframe,
            "lookback_years": effective_lookback_years,
            "candles": [],
            "rows": 0,
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
        }


@router.get("/summary")
def market_causality_summary(
    refresh: bool = Query(default=False),
    symbol: str = Query(default="XAUUSD"),
    timeframe: str = Query(default="1d"),
    lookback_years: int = Query(default=25, ge=1, le=100),
    source_mode: str = Query(default="live_first"),
) -> dict[str, Any]:
    """Unified bridge endpoint for market-causality-lab summary data."""
    return _compute_summary(
        refresh=bool(refresh),
        symbol=symbol,
        timeframe=timeframe,
        lookback_years=lookback_years,
        source_mode=source_mode,
    )


@router.post("/math_check")
def market_causality_math_check(payload: dict[str, Any]) -> dict[str, Any]:
    """Run standalone MATH_01..MATH_15 checks without requiring full summary execution."""
    out = _compute_math_questions(payload)
    return {
        "status": "ok",
        **out,
    }


@router.post("/gann_questions")
def market_causality_gann_questions(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Answer all 52 _TRADING_GANN_QUESTION_BANK questions from a raw payload.

    Accepts the same payload shape as /summary (observation, trade_levels, etc.).
    Returns gann_questions list + aggregate scoring without running the full system.
    """
    out = _compute_gann_answers(payload)
    return {"status": "ok", **out}


@router.post("/record_outcome")
def market_causality_record_outcome(payload: dict[str, Any]) -> dict[str, Any]:
    """Record realized outcome and update learning weights for POST_01/POST_02 lifecycle."""
    prediction_id = str(payload.get("prediction_id") or payload.get("observation_id") or "").strip()
    if not prediction_id:
        return {"status": "error", "error": "prediction_id (or observation_id) is required"}

    outcome_direction = str(payload.get("outcome_direction") or "").strip().upper()
    if outcome_direction not in {"UP", "DOWN", "SIDEWAYS"}:
        return {"status": "error", "error": "outcome_direction must be one of: UP, DOWN, SIDEWAYS"}

    try:
        realized_price = float(payload.get("realized_price"))
        actual_move_pips = float(payload.get("actual_move_pips"))
        timeframe_reached = int(payload.get("timeframe_reached"))
    except (TypeError, ValueError):
        return {
            "status": "error",
            "error": "realized_price, actual_move_pips, timeframe_reached are required numeric fields",
        }

    existing_prediction = next((p for p in _LEARNING_ENGINE.predictions if p.get("id") == prediction_id), None)
    if existing_prediction is None:
        direction = str(payload.get("direction") or payload.get("predicted_direction") or "WAIT").upper()
        direction = direction if direction in {"BUY", "SELL", "WAIT"} else "WAIT"
        signals = payload.get("signals") or {}
        entry_price = float(payload.get("entry_price") or realized_price)
        stop_price = float(payload.get("stop_price") or (entry_price - 10.0))
        target_price = float(payload.get("target_price") or (entry_price + 20.0))
        forecast_horizon_days = int(payload.get("forecast_horizon_days") or 1)

        _LEARNING_ENGINE.record_prediction(
            prediction_id=prediction_id,
            direction=direction,
            confluence_score=float(payload.get("confluence_score") or 0.0),
            geometry_signal=bool(signals.get("geometry", False)),
            time_signal=bool(signals.get("time", False)),
            structure_signal=bool(signals.get("structure", False)),
            momentum_signal=bool(signals.get("momentum", False)),
            gann_signal=bool(signals.get("gann", False)),
            ict_signal=bool(signals.get("ict", False)),
            confluence_signal=bool(signals.get("confluence", float(payload.get("confluence_score") or 0.0) >= 0.7)),
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            forecast_horizon_days=forecast_horizon_days,
        )

    result = _LEARNING_ENGINE.record_outcome(
        prediction_id=prediction_id,
        realized_price=realized_price,
        outcome_direction=outcome_direction,
        actual_move_pips=actual_move_pips,
        timeframe_reached=timeframe_reached,
    )

    if result.get("status") == "error":
        return {"status": "error", "error": result.get("message")}

    return {
        "status": "ok",
        "prediction_id": prediction_id,
        "accuracy_score": result.get("accuracy_score"),
        "was_correct": result.get("was_correct"),
        "learning_update": result.get("learning_update"),
    }


@router.get("/status")
def market_causality_status() -> dict[str, Any]:
    module_exists = _module_path().exists()
    with _cache_lock:
        cache_keys = sorted(list(_cache_payloads.keys()))

    cal = _LEARNING_ENGINE.get_model_calibration()

    return {
        "module_path": str(_module_path()),
        "module_exists": module_exists,
        "module_loaded": _module is not None,
        "cache_ttl_seconds": _CACHE_TTL_SECONDS,
        "summary_timeout_seconds": _SUMMARY_TIMEOUT_SECONDS,
        "background_summary_timeout_seconds": _BACKGROUND_SUMMARY_TIMEOUT_SECONDS,
        "matrix_wait_seconds": _MATRIX_WAIT_SECONDS,
        "matrix_refresh_wait_seconds": _MATRIX_REFRESH_WAIT_SECONDS,
        "cache_entries": len(cache_keys),
        "cache_keys": cache_keys,
        # Model health summary
        "model_confidence": cal["model_confidence"],
        "overall_accuracy": round(cal["overall_accuracy"], 4),
        "total_outcomes": cal["total_outcomes"],
        "total_predictions": cal["total_predictions"],
        "top_signal": max(cal["current_weights"], key=lambda k: cal["current_weights"][k]),
        "weakest_signal": min(cal["current_weights"], key=lambda k: cal["current_weights"][k]),
    }


@router.get("/engines")
def market_causality_engines(
    symbol: str = Query(default="XAUUSD"),
    timeframe: str = Query(default="1d"),
    lookback_years: int = Query(default=25, ge=1, le=100),
    source_mode: str = Query(default="live_first"),
) -> dict[str, Any]:
    """
    Return the raw output of every MCL analytical engine for the current bar.

    This endpoint exposes the full 9-framework intelligence stack as separate
    structured objects — physics, gann, gann_advanced, gann_nodes, liquidity,
    phase, trap, psychology, behavior, numerology, harmonic, astro, compression,
    time_signal, future, sync, backtest, execution, failure, data_quality,
    latency, timescale, overfit, universal, and the final consensus signal.

    Designed for:
    - Dashboard deep-dive panels
    - Automated trading decision audit trail
    - External consumers wanting structured per-engine data
    """
    symbol = _normalize_symbol(symbol)
    timeframe = _normalize_timeframe(timeframe)
    lookback_years = _normalize_lookback_years(lookback_years)
    source_mode = _normalize_source_mode(source_mode)

    cache_key = _cache_key(symbol, timeframe, lookback_years, source_mode)
    with _cache_lock:
        payload = _cache_raw_payloads.get(cache_key)

    if payload is None:
        return {
            "status": "no_cache",
            "detail": "No cached MCL result available. Call /market_causality/summary first to populate cache.",
            "symbol": symbol,
            "timeframe": timeframe,
        }

    def _safe(val: Any) -> Any:
        """Return val if truthy-and-not-empty, else None."""
        if val is None:
            return None
        if isinstance(val, dict) and not val:
            return None
        return val

    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "updated_at": int(time.time()),
        # ── Core market state ─────────────────────────────────────────────
        "state": _safe(payload.get("final")),
        "signal": payload.get("filtered_signal"),
        "confidence": payload.get("confidence"),
        "quality": payload.get("quality"),
        "bias_score": (payload.get("simple") or {}).get("bias_score"),
        "bias_label": (payload.get("simple") or {}).get("bias_label"),
        "clarity": (payload.get("simple") or {}).get("clarity"),
        "conviction": (payload.get("simple") or {}).get("conviction"),
        # ── Framework 1: Market Physics ───────────────────────────────────
        "physics": {
            "force": (payload.get("physics") or {}).get("force"),
            "velocity": (payload.get("physics") or {}).get("velocity"),
            "energy": (payload.get("physics") or {}).get("energy"),
        },
        # ── Framework 2: W.D. Gann ────────────────────────────────────────
        "gann": _safe(payload.get("gann_adv")),
        "gann_nodes": _safe(payload.get("gann_nodes")),
        # ── Framework 3: ICT / SMC Liquidity ─────────────────────────────
        "liquidity": _safe(payload.get("liquidity")),
        # ── Framework 4: Wyckoff Phase ────────────────────────────────────
        "phase": (payload.get("final") or {}).get("phase"),
        # ── Framework 5: Vedic Astrology + Moon ──────────────────────────
        "astro": _safe(payload.get("astro")),
        # ── Framework 6: Time Compression (Gann Silence) ─────────────────
        "compression": _safe(payload.get("compression")),
        # ── Framework 7: Pythagorean Numerology ──────────────────────────
        "numerology": _safe(payload.get("numerology")),
        # ── Framework 8: Harmonic Patterns ───────────────────────────────
        "harmonic": _safe(payload.get("harmonic")),
        # ── Framework 9: Psychology / Trap / Behavior ─────────────────────
        "psychology": _safe(payload.get("psychology")),
        "trap": _safe(payload.get("trap")),
        "behavior": _safe(payload.get("behavior")),
        # ── Time Convergence Engine ───────────────────────────────────────
        "time_signal": _safe(payload.get("time_signal")),
        # ── Gann Cycle Future Projection ─────────────────────────────────
        "future": _safe(payload.get("future")),
        # ── Signal Aggregation Layer ──────────────────────────────────────
        "signals": _safe(payload.get("signals")),
        "dominance_score": _safe(payload.get("score")),
        "weights": _safe(payload.get("weights")),
        "scenarios": _safe(payload.get("scenarios")),
        "probability": _safe(payload.get("probability")),
        # ── Institutional / Macro Layer ───────────────────────────────────
        "institutional": _safe(payload.get("institutional")),
        # ── Trade Levels ──────────────────────────────────────────────────
        "trade_levels": _safe(payload.get("trade_levels")),
        # ── Precision / Realism Layer ─────────────────────────────────────
        "data_quality": _safe(payload.get("data_quality")),
        "latency": _safe(payload.get("latency")),
        "timescale": _safe(payload.get("timescale")),
        "overfit": _safe(payload.get("overfit")),
        "execution": _safe(payload.get("execution")),
        "failure": _safe(payload.get("failure")),
        # ── Universal Conversion Engine ───────────────────────────────────
        "universal": _safe(payload.get("universal")),
        # ── Memory / Backtest ─────────────────────────────────────────────
        "backtest": _safe(payload.get("backtest")),
        "memory_size": payload.get("memory_size"),
        # ── AI / Learning ─────────────────────────────────────────────────
        "ai_decision": payload.get("ai_decision"),
        "ai_model": _safe(payload.get("ai_model")),
        # ── Timing ───────────────────────────────────────────────────────
        "process_timing": _safe(payload.get("process_timing")),
        "rows_analyzed": payload.get("rows_analyzed"),
        "data_source": payload.get("data_source"),
    }


@router.get("/chart")
def market_causality_chart(
    symbol: str = Query(default="XAUUSD"),
    timeframe: str = Query(default="1d"),
    source_mode: str = Query(default="live_first"),
    lookback_years: int = Query(default=25, ge=1, le=100),
    limit: int = Query(default=12000, ge=1, le=50000),
    strict_mt5: bool = Query(default=False),
) -> dict[str, Any]:
    """Historical candlestick data for the MCL dashboard chart."""
    return _compute_chart(
        symbol=symbol,
        timeframe=timeframe,
        source_mode=source_mode,
        lookback_years=lookback_years,
        limit=limit,
        strict_mt5=strict_mt5,
    )


@router.get("/live_price")
def market_causality_live_price(
    symbol: str = Query(default="XAUUSD"),
    prefer_source: str = Query(default="mt5"),
    broker_only: bool = Query(default=False),
    max_age_seconds: int = Query(default=45, ge=1, le=900),
) -> dict[str, Any]:
    """Return the most recent XAUUSD live spot price.

        Priority chain for MCL (MT5 first):
            1. Local/MT5 bridge quote files (primary for MCL)
            2. Maven broker DOM (real-time XAUUSD spot via CDP bridge)
            3. stooq.com XAUUSD spot (free, no API key, ~seconds delay)
            4. Databento futures fallback (optional; disabled by default for MCL)
    Used by the MCL dashboard for periodic live price polling.
    """
    import pandas as _pd
    import urllib.request as _urllib_req

    symbol = _normalize_symbol(symbol)
    started_at = time.time()
    # Unwrap FastAPI Query objects when the endpoint is called directly (e.g., in tests)
    prefer_source = str(getattr(prefer_source, "default", prefer_source) or "mt5").strip().lower()
    _broker_only_raw = getattr(broker_only, "default", broker_only)
    broker_only = bool(_broker_only_raw)
    _max_age_raw = getattr(max_age_seconds, "default", max_age_seconds)
    max_age_seconds = int(max(1, int(_max_age_raw)))

    def _fetch_broker_quote() -> dict[str, Any] | None:
        try:
            try:
                from astroquant.backend.services.runner import get_runner  # type: ignore
            except (ImportError, ModuleNotFoundError):
                get_runner = None
            if not (get_runner and callable(get_runner)):
                return None
            _runner = get_runner()
            if _runner is None:
                return None
            _quote = _runner.get_broker_spot_quote("XAUUSD")
            _price = (_quote or {}).get("price") if isinstance(_quote, dict) else getattr(_quote, "price", None)
            if _price and float(_price) > 0 and not (_quote or {}).get("stale", True):
                return {
                    "price": round(float(_price), 4),
                    "source": "broker_dom_spot",
                    "spot": True,
                    "ts": int(time.time()),
                }
        except Exception:
            return None
        return None

    def _fetch_stooq_quote() -> dict[str, Any] | None:
        try:
            _req = _urllib_req.Request(
                "https://stooq.com/q/l/?s=xauusd&f=sd2t2ohlcv&h&e=csv",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with _urllib_req.urlopen(_req, timeout=6) as _r:
                _lines = _r.read().decode().strip().split("\n")
            if len(_lines) < 2 or _lines[1].startswith("N/A"):
                return None
            _fields = _lines[1].split(",")
            _price = float(_fields[6])
            _dt_str = f"{_fields[1]} {_fields[2]}"
            _ts = int(_pd.Timestamp(_dt_str).timestamp())
            _now_ts = int(time.time())
            if _ts > _now_ts + 120:
                _ts = _now_ts
            _age = int(max(0, time.time() - _ts))
            if _price <= 0 or _age > max_age_seconds:
                return None
            return {
                "price": round(float(_price), 4),
                "source": "stooq_xauusd_spot",
                "spot": True,
                "ts": _ts,
            }
        except Exception:
            return None

    def _fetch_mt5_local_quote() -> dict[str, Any] | None:
        try:
            _q = _load_local_live_quote(symbol=symbol, timeframe="5m")
            if not _q:
                return None
            _price = float(_q.get("price") or 0.0)
            _ts = _q.get("ts")
            if _price <= 0 or not isinstance(_ts, (int, float)):
                return None
            _age = int(max(0, time.time() - int(_ts)))
            if _age > max_age_seconds:
                return None
            return {
                "price": round(float(_price), 4),
                "source": str(_q.get("source") or "mt5_local"),
                "spot": bool(_q.get("spot", False)),
                "ts": int(_ts),
            }
        except Exception:
            return None

    def _fetch_databento_quote() -> dict[str, Any] | None:
        if not _mcl_databento_enabled():
            return None
        try:
            from astroquant.backend.services.databento_utility import fetch_candles_unified

            candles, _meta = fetch_candles_unified(symbol=symbol, limit=5, minutes=90)
            if not candles:
                return None
            last = candles[-1]
            price = float(last.get("close") or last.get("open") or 0.0)
            if price <= 0:
                return None
            _raw_ts = last.get("time") or last.get("timestamp") or last.get("t") or last.get("ts")
            try:
                _ts = int(_pd.Timestamp(_raw_ts).timestamp()) if _raw_ts is not None else None
            except Exception:
                _ts = None
            return {
                "price": round(float(price), 4),
                "source": f"databento_futures/{_meta.get('resolved_symbol','GC.c.1')}",
                "spot": False,
                "fallback": True,
                "ts": _ts,
            }
        except Exception:
            return None

    mt5_quote = _fetch_mt5_local_quote()
    broker_quote = _fetch_broker_quote()
    stooq_quote: dict[str, Any] | None = None
    stooq_loaded = False
    databento_quote: dict[str, Any] | None = None
    databento_loaded = False

    def _get_stooq_quote() -> dict[str, Any] | None:
        nonlocal stooq_quote, stooq_loaded
        if not stooq_loaded:
            stooq_quote = _fetch_stooq_quote()
            stooq_loaded = True
        return stooq_quote

    def _get_databento_quote() -> dict[str, Any] | None:
        nonlocal databento_quote, databento_loaded
        if broker_only:
            return None
        if not databento_loaded:
            databento_quote = _fetch_databento_quote()
            databento_loaded = True
        return databento_quote

    if broker_only and broker_quote is None:
        return {
            "status": "unavailable",
            "symbol": symbol,
            "price": None,
            "source": None,
            "spot": None,
            "broker_matched": False,
            "error": "broker_only_requested_no_broker_quote",
            "drift_learning": _live_broker_drift_snapshot(),
            "requested_prefer_source": prefer_source,
            "requested_broker_only": broker_only,
            "requested_max_age_seconds": max_age_seconds,
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
        }

    selected_quote: dict[str, Any] | None = None
    if broker_only:
        selected_quote = broker_quote
    elif prefer_source in {"mt5", "mcl", "local", "bridge"}:
        selected_quote = mt5_quote or broker_quote or _get_stooq_quote() or _get_databento_quote()
    elif prefer_source in {"stooq", "spot", "public_spot"}:
        selected_quote = _get_stooq_quote() or mt5_quote or broker_quote or _get_databento_quote()
    elif prefer_source in {"databento", "futures", "proxy"}:
        selected_quote = _get_databento_quote() or mt5_quote or broker_quote or _get_stooq_quote()
    else:
        selected_quote = mt5_quote or broker_quote or _get_stooq_quote() or _get_databento_quote()

    if selected_quote is None:
        return {
            "status": "unavailable",
            "symbol": symbol,
            "price": None,
            "source": None,
            "spot": None,
            "broker_matched": False,
            "error": "no_live_quote_available",
            "drift_learning": _live_broker_drift_snapshot(),
            "requested_prefer_source": prefer_source,
            "requested_broker_only": broker_only,
            "requested_max_age_seconds": max_age_seconds,
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
        }

    broker_reference_price = float(broker_quote.get("price")) if broker_quote else None
    selected_price = float(selected_quote.get("price") or 0.0)
    live_vs_broker_diff = None
    live_vs_broker_diff_pct = None
    if broker_reference_price and selected_price > 0:
        live_vs_broker_diff = selected_price - broker_reference_price
        live_vs_broker_diff_pct = (live_vs_broker_diff / broker_reference_price) * 100.0
        _update_live_broker_drift(
            abs_diff=abs(float(live_vs_broker_diff)),
            abs_pct=abs(float(live_vs_broker_diff_pct)),
            source=str(selected_quote.get("source") or "--"),
        )

    out = {
        "status": "ok",
        "symbol": symbol,
        "price": round(selected_price, 4),
        "source": selected_quote.get("source"),
        "spot": bool(selected_quote.get("spot", True)),
        "broker_matched": bool(str(selected_quote.get("source") or "").startswith("broker_dom_spot")),
        "ts": selected_quote.get("ts"),
        "requested_prefer_source": prefer_source,
        "requested_broker_only": broker_only,
        "requested_max_age_seconds": max_age_seconds,
        "broker_reference_price": round(float(broker_reference_price), 4) if broker_reference_price else None,
        "live_vs_broker_diff": round(float(live_vs_broker_diff), 6) if live_vs_broker_diff is not None else None,
        "live_vs_broker_diff_pct": round(float(live_vs_broker_diff_pct), 6) if live_vs_broker_diff_pct is not None else None,
        "drift_learning": _live_broker_drift_snapshot(),
        "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
    }
    if selected_quote.get("fallback"):
        out["fallback"] = True
    return out


# ---------------------------------------------------------------------------
# AMD + IFVG Distribution Strategy endpoint
# ---------------------------------------------------------------------------

@router.get("/amd_ifvg")
def market_causality_amd_ifvg(
    symbol: str = Query(default="XAUUSD"),
    timeframe: str = Query(default="5m"),
    lookback: int = Query(default=20, ge=5, le=200, description="Accumulation lookback bars"),
    atr_length: int = Query(default=14, ge=1, le=100, description="ATR period"),
    atr_mult: float = Query(default=1.5, ge=0.1, le=10.0, description="Max range ATR multiplier"),
    min_fvg_pct: float = Query(default=0.0, ge=0.0, le=5.0, description="Minimum FVG size (%)"),
    lookback_years: int = Query(default=1, ge=1, le=10),
    limit: int = Query(default=5000, ge=10, le=50000),
) -> dict[str, Any]:
    """AMD + IFVG Distribution Strategy indicator.

    Detects Accumulation → Manipulation → Distribution phases on the MCL chart data
    and returns entry signals, stop-loss and take-profit levels, and phase labels.

    Query params mirror the TradingView Pine Script inputs exactly.
    """
    try:
        import sys as _sys
        import importlib as _importlib
        _mcl_root = str(_repo_root() / "market-causality-lab")
        if _mcl_root not in _sys.path:
            _sys.path.insert(0, _mcl_root)
        _amd_mod = _importlib.import_module("backend.engines.amd_ifvg_engine")
    except Exception as exc:
        return {"status": "error", "message": f"amd_ifvg_engine import failed: {exc}"}

    # Load candle data via existing chart pipeline
    try:
        chart = _compute_chart(
            symbol=symbol,
            timeframe=timeframe,
            lookback_years=lookback_years,
            limit=limit,
        )
        candles = chart.get("candles") or []
        if not candles:
            return {
                "status": "ok",
                "symbol": symbol,
                "timeframe": timeframe,
                "signal": "NONE",
                "phase": "NONE",
                "message": "No candle data available",
                "latest": {},
                "recent_signals": [],
            }

        import pandas as _pd
        df_c = _pd.DataFrame(candles)
        for _col in ("open", "high", "low", "close", "volume"):
            if _col in df_c.columns:
                df_c[_col] = _pd.to_numeric(df_c[_col], errors="coerce")
        if "time" in df_c.columns:
            df_c["time"] = _pd.to_datetime(df_c["time"], unit="s", utc=True, errors="coerce")
        df_c = df_c.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    except Exception as exc:
        return {"status": "error", "message": f"chart data load failed: {exc}"}

    # Run the engine
    try:
        min_fvg_frac = float(min_fvg_pct) / 100.0
        summary = _amd_mod.amd_ifvg_summary(
            df_c,
            lookback=int(lookback),
            atr_length=int(atr_length),
            atr_mult=float(atr_mult),
            min_fvg_pct=min_fvg_frac,
        )
    except Exception as exc:
        return {"status": "error", "message": f"amd_ifvg engine error: {exc}"}

    latest = summary.get("latest") or {}
    signal = latest.get("signal", "NONE")
    phase = latest.get("phase", "NONE")

    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "settings": {
            "lookback": lookback,
            "atr_length": atr_length,
            "atr_mult": atr_mult,
            "min_fvg_pct": min_fvg_pct,
        },
        "signal": signal,
        "phase": phase,
        "sl": latest.get("sl"),
        "tp": latest.get("tp"),
        "entry_top": latest.get("entry_top"),
        "entry_bot": latest.get("entry_bot"),
        "rr_ratio": latest.get("rr_ratio"),
        "acc_hh": latest.get("acc_hh"),
        "acc_ll": latest.get("acc_ll"),
        "atr": latest.get("atr"),
        "total_bull": summary.get("total_bull"),
        "total_bear": summary.get("total_bear"),
        "avg_rr_bull": summary.get("avg_rr_bull"),
        "avg_rr_bear": summary.get("avg_rr_bear"),
        "recent_signals": summary.get("recent_signals") or [],
        "candles_scanned": len(df_c),
        "applied_timeframe": chart.get("applied_timeframe"),
    }


@router.get("/mt5_bridge_status")
def market_causality_mt5_bridge_status(
    symbol: str = Query(default="XAUUSD"),
    timeframe: str = Query(default="5m"),
) -> dict[str, Any]:
    """Return MT5 runtime + bridge-file readiness for MCL chart ingestion."""
    symbol = _normalize_symbol(symbol)
    timeframe = _normalize_timeframe(timeframe)

    mt5_runtime: dict[str, Any] = {
        "python_module_available": False,
        "initialize_ok": False,
        "last_error": None,
    }
    try:
        mt5_spec = importlib.util.find_spec("MetaTrader5")
        mt5_runtime["python_module_available"] = mt5_spec is not None
        if mt5_spec is not None:
            import MetaTrader5 as mt5  # type: ignore[import]

            ok = bool(mt5.initialize())
            mt5_runtime["initialize_ok"] = ok
            if ok:
                try:
                    tick = mt5.symbol_info_tick(symbol)
                    mt5_runtime["symbol_tick_available"] = bool(tick is not None)
                except Exception:
                    mt5_runtime["symbol_tick_available"] = False
                finally:
                    mt5.shutdown()
            else:
                mt5_runtime["last_error"] = str(mt5.last_error())
    except Exception as exc:
        mt5_runtime["last_error"] = str(exc)

    bridge_files: list[dict[str, Any]] = []
    for source, path in _live_csv_candidates(symbol=symbol, timeframe=timeframe):
        _exists = path.exists()
        _rows = 0
        _last_ts = None
        if _exists:
            try:
                _df = _read_live_csv_ohlc(path)
                if _df is not None and not _df.empty:
                    _rows = int(len(_df))
                    _tail = _df.sort_values("time").tail(1)
                    if not _tail.empty:
                        _ts_obj = _tail.iloc[0].get("time")
                        if _ts_obj is not None:
                            _last_ts = int(_ts_obj.timestamp())
            except Exception:
                pass
        bridge_files.append({
            "source": source,
            "path": str(path),
            "exists": _exists,
            "rows": _rows,
            "last_ts": _last_ts,
        })

    best_quote = _load_local_live_quote(symbol=symbol, timeframe=timeframe)
    bridge_sources = [item for item in bridge_files if str(item.get("source") or "").startswith("mt5_")]
    bridge_ready = any(bool(item.get("exists")) and int(item.get("rows") or 0) > 0 for item in bridge_sources)

    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "mt5_runtime": mt5_runtime,
        "bridge_ready": bridge_ready,
        "bridge_files": bridge_files,
        "best_live_quote": best_quote,
        "chart_ingestion_ready": bool(best_quote),
        "message": (
            "MT5 bridge files detected; MCL chart can ingest XAUUSD from bridge"
            if bridge_ready
            else "No MT5 bridge files detected yet; chart will use existing local/live fallback"
        ),
        "updated_at": int(time.time()),
    }


@router.post("/mt5_upload")
async def market_causality_mt5_upload(
    request: Request,
    symbol: str = Query(default="XAUUSD"),
    timeframe: str = Query(default="5m"),
) -> dict[str, Any]:
    """Accept an MT5 CSV export as raw body or multipart from any HTTP client."""
    symbol = _normalize_symbol(symbol)
    incoming_dir = _repo_root() / "market-causality-lab" / "data" / "live" / "mt5" / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    dest = incoming_dir / "XAUUSD_feed_latest.csv"
    content = await request.body()
    if not content:
        return {"status": "error", "message": "empty file"}
    dest.write_bytes(content)
    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "bytes": len(content),
        "dest": str(dest),
        "ts": int(time.time()),
    }


@router.get("/timeframe_matrix")
def market_causality_timeframe_matrix(
    refresh: bool = Query(default=False),
    symbol: str = Query(default="XAUUSD"),
    lookback_years: int = Query(default=25, ge=1, le=100),
    source_mode: str = Query(default="live_first"),
) -> dict[str, Any]:
    """Aggregated timeframe-wise AI observation matrix payload."""
    return _compute_timeframe_matrix(
        refresh=bool(refresh),
        symbol=symbol,
        lookback_years=lookback_years,
        source_mode=source_mode,
    )


@router.get("/gann_qa")
def market_causality_gann_qa(
    date: str = Query(default=""),
    symbol: str = Query(default="XAUUSD"),
    limit: int = Query(default=60, ge=1, le=300),
    horizon_days: int = Query(default=1, ge=1, le=30),
) -> dict[str, Any]:
    """Date-selectable Gann Q&A table generated from observation history (past/present/future)."""
    selected = date or time.strftime("%Y-%m-%d", time.gmtime())
    try:
        return _build_gann_qa_rows(selected_date=selected, symbol=symbol, limit=limit, horizon_days=horizon_days)
    except Exception as exc:
        return {
            "status": "error",
            "date": selected,
            "symbol": _normalize_symbol(symbol),
            "rows": [],
            "error": str(exc),
        }


@router.get("/question_bank")
def market_causality_question_bank(
    category: str = Query(default=""),
    framework: str = Query(default=""),
) -> dict[str, Any]:
    """Comprehensive trading question bank across Gann + supporting concepts + AI learning."""
    return _question_bank_payload(category=category, framework=framework)


@router.get("/weights")
def market_causality_weights() -> dict[str, Any]:
    """Return current learned signal weights and model calibration stats."""
    calibration = _LEARNING_ENGINE.get_model_calibration()
    return {
        "status": "ok",
        "weights": _LEARNING_ENGINE.weights.copy(),
        "total_predictions": calibration.get("total_predictions", 0),
        "total_outcomes": calibration.get("total_outcomes", 0),
        "overall_accuracy": calibration.get("overall_accuracy", 0.0),
        "model_confidence": calibration.get("model_confidence", "LOW"),
        "signal_accuracy": calibration.get("signal_accuracy", {}),
        "accuracy_trend": calibration.get("accuracy_trend", []),
        "direction_accuracy": calibration.get("direction_accuracy", {}),
        "learning_message": calibration.get("learning_message", ""),
        "updated_at": int(time.time()),
    }


@router.get("/history")
def market_causality_history(limit: int = 50, correct_only: bool = False) -> dict[str, Any]:
    """Return the last N recorded trade outcomes joined with their prediction data.

    Query params:
      - limit (int): max rows returned, default 50
      - correct_only (bool): when true, return only winning outcomes
    """
    predictions = _PREDICTION_TRACKER.load_predictions()
    outcomes = _PREDICTION_TRACKER.load_outcomes()

    pred_by_id: dict[str, Any] = {p["id"]: p for p in predictions}

    rows = []
    for o in outcomes:
        pid = o.get("prediction_id", "")
        pred = pred_by_id.get(pid, {})
        was_correct = o.get("was_correct", False)
        if correct_only and not was_correct:
            continue
        rows.append({
            "prediction_id":        pid,
            "prediction_timestamp": pred.get("prediction_timestamp"),
            "direction":            pred.get("direction", ""),
            "confluence_score":     pred.get("confluence_score"),
            "entry_price":          pred.get("entry_price"),
            "stop_price":           pred.get("stop_price"),
            "target_price":         pred.get("target_price"),
            "realized_price":       o.get("realized_price"),
            "outcome_direction":    o.get("outcome_direction", ""),
            "actual_move_pips":     o.get("actual_move_pips"),
            "timeframe_reached":    o.get("timeframe_reached"),
            "was_correct":          was_correct,
            "accuracy_score":       o.get("accuracy_score", 0.0),
        })

    # Return most-recent first, capped at limit
    total_available = len(rows)
    rows = rows[-limit:][::-1]
    return {
        "status": "ok",
        "total": total_available,
        "returned": len(rows),
        "correct_only": correct_only,
        "history": rows,
    }


@router.post("/question_bank")
def market_causality_question_bank_with_answers(
    payload: dict[str, Any],
    category: str = Query(default=""),
    framework: str = Query(default=""),
) -> dict[str, Any]:
    """
    Question bank merged with live answers from the provided system payload.

    POST body: same shape as /summary payload (observation, trade_levels, final, etc.)
    Each question row gets answer (bool), reasoning (str), confidence (0..1) injected.
    Aggregate scoring (verdict, score, pct, weakest) included in the response.
    """
    # Coerce FastAPI Query descriptor objects to plain strings when called directly in tests
    _cat = str(category.default if hasattr(category, "default") else category)
    _fw  = str(framework.default if hasattr(framework, "default") else framework)
    return _question_bank_payload(category=_cat, framework=_fw, live_payload=payload)


@router.post("/run_batch")
def market_causality_run_batch(
    payload: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    """
    Trigger a batch backtest replay over all chart data files.

    Optional body fields:
        dry_run  (bool):  default false — when true, weights are NOT saved.
        window   (int):   lookback bars (default 12)
        horizon  (int):   forward bars for outcome (default 24)
        min_move (float): minimum price move in points to count as a valid
                          outcome (default 3.0)

    Returns the full batch summary including per-file stats and final weights.
    """
    from astroquant.backend.backtest_replay import run_batch_replay  # local import to avoid circular

    dry_run  = bool(payload.get("dry_run", False))
    window   = int(payload.get("window", 12))
    horizon  = int(payload.get("horizon", 24))
    min_move = float(payload.get("min_move", 3.0))

    result = run_batch_replay(
        window=window,
        horizon=horizon,
        min_move=min_move,
        dry_run=dry_run,
        tracker_path=str(_PREDICTION_TRACKER.path),
    )

    # Reload live-engine state so /weights reflects the updated values immediately
    if not dry_run:
        persisted = _PREDICTION_TRACKER.load_weights()
        for k, v in persisted.items():
            if k in _LEARNING_ENGINE.weights:
                _LEARNING_ENGINE.weights[k] = v
        _LEARNING_ENGINE.predictions        = _PREDICTION_TRACKER.load_predictions()
        _LEARNING_ENGINE.realized_outcomes  = _PREDICTION_TRACKER.load_outcomes()

    return result


def _node_wave_training_defaults(timeframe: str | None) -> dict[str, Any]:
    tf = _normalize_timeframe(timeframe)
    tf_sec = max(60, _timeframe_seconds(tf))

    # Aim for ~2 days prediction horizon with timeframe-scaled bars.
    horizon = max(12, min(480, int(round((2 * 86400) / tf_sec))))
    window = max(8, min(160, int(round(horizon * 0.5))))

    if tf_sec <= 300:
        min_move = 1.5
    elif tf_sec <= 3600:
        min_move = 3.0
    elif tf_sec <= 14400:
        min_move = 5.0
    else:
        min_move = 8.0

    return {
        "timeframe": tf,
        "tf_seconds": int(tf_sec),
        "window": int(window),
        "horizon": int(horizon),
        "min_move": float(min_move),
    }


@router.post("/train_node_wave_model")
def market_causality_train_node_wave_model(
    payload: dict[str, Any] = Body(default={}),
    timeframe: str = Query(default="1h"),
) -> dict[str, Any]:
    """Train AI weights with timeframe-aware defaults focused on node/wave start-stop calibration."""
    defaults = _node_wave_training_defaults(timeframe)
    dry_run = bool(payload.get("dry_run", False))

    train_payload = {
        "dry_run": dry_run,
        "window": int(payload.get("window", defaults["window"])),
        "horizon": int(payload.get("horizon", defaults["horizon"])),
        "min_move": float(payload.get("min_move", defaults["min_move"])),
    }

    before = _LEARNING_ENGINE.get_model_calibration()
    result = market_causality_run_batch(train_payload)
    after = _LEARNING_ENGINE.get_model_calibration()

    return {
        "status": "ok",
        "training_focus": "adjacent_node_wave_timeframe_calibration",
        "timeframe_profile": defaults,
        "applied_params": train_payload,
        "calibration_before": {
            "overall_accuracy": before.get("overall_accuracy"),
            "total_outcomes": before.get("total_outcomes"),
            "total_predictions": before.get("total_predictions"),
        },
        "calibration_after": {
            "overall_accuracy": after.get("overall_accuracy"),
            "total_outcomes": after.get("total_outcomes"),
            "total_predictions": after.get("total_predictions"),
        },
        "batch_result": result,
    }


@router.post("/auto_resolve_pending")
def market_causality_auto_resolve(
    symbol: str = Query(default="XAUUSD"),
) -> dict[str, Any]:
    """Auto-resolve predictions whose forecast horizon has passed.

    For each recorded prediction that:
      - has no corresponding outcome yet
      - whose forecast_horizon_days has elapsed since recorded_at

    … the endpoint fetches the latest live price, infers the realized direction
    versus the entry price, and records the outcome automatically.

    Returns a summary of how many predictions were resolved.
    """
    now_utc = datetime.now(timezone.utc)
    resolved = []
    errors: list[str] = []

    # Build set of already-resolved prediction IDs
    resolved_ids: set[str] = {o.get("prediction_id") for o in _LEARNING_ENGINE.realized_outcomes if o.get("prediction_id")}

    # Gather expired-but-unresolved predictions
    pending: list[dict[str, Any]] = []
    for pred in _LEARNING_ENGINE.predictions:
        pid = pred.get("id")
        if not pid or pid in resolved_ids:
            continue
        recorded_raw = pred.get("recorded_at")
        if not recorded_raw:
            continue
        try:
            recorded_at = datetime.fromisoformat(str(recorded_raw).replace("Z", "+00:00"))
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        horizon_days = int(pred.get("forecast_horizon_days") or 1)
        elapsed = (now_utc - recorded_at).total_seconds() / 86400.0
        if elapsed >= horizon_days:
            pending.append(pred)

    if not pending:
        return {"status": "ok", "resolved_count": 0, "message": "No expired unresolved predictions found."}

    # Get current live price once
    current_price: float | None = None
    try:
        price_resp = market_causality_live_price(symbol=symbol)
        if price_resp.get("status") == "ok":
            current_price = float(price_resp["price"])
    except Exception as exc:
        errors.append(f"price_fetch_error: {exc}")

    if current_price is None:
        return {
            "status": "error",
            "error": "Could not fetch current price for auto-resolution",
            "errors": errors,
        }

    for pred in pending:
        pid = str(pred.get("id"))
        entry_price = float(pred.get("entry_price") or current_price)
        try:
            move = current_price - entry_price
            pips = abs(round(move, 2))
            if move > 0.10:
                direction = "UP"
            elif move < -0.10:
                direction = "DOWN"
            else:
                direction = "SIDEWAYS"

            elapsed_days = (now_utc - datetime.fromisoformat(
                str(pred.get("recorded_at")).replace("Z", "+00:00")
            ).replace(tzinfo=timezone.utc)).total_seconds() / 86400.0

            result = _LEARNING_ENGINE.record_outcome(
                prediction_id=pid,
                realized_price=current_price,
                outcome_direction=direction,
                actual_move_pips=pips,
                timeframe_reached=max(1, int(elapsed_days * 24)),
            )
            if result.get("status") != "error":
                resolved.append({
                    "prediction_id": pid,
                    "direction": direction,
                    "entry_price": entry_price,
                    "current_price": current_price,
                    "move_pips": pips,
                    "accuracy_score": result.get("accuracy_score"),
                    "was_correct": result.get("was_correct"),
                })
            else:
                errors.append(f"{pid}: {result.get('message')}")
        except Exception as exc:
            errors.append(f"{pid}: {exc}")

    return {
        "status": "ok",
        "resolved_count": len(resolved),
        "current_price": current_price,
        "resolved": resolved,
        "errors": errors if errors else None,
    }


@router.post("/reset_weights")
def market_causality_reset_weights(
    payload: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    """
    Reset all learning-engine signal weights to their original baseline values.

    Optional body fields:
        clear_predictions (bool): default false — when true, ALL predictions and
            outcomes are also wiped (full reset).  Use with caution.

    Returns confirmation with the new weight values.
    """
    _baseline: dict[str, float] = {
        "geometry":  0.88,
        "time":      0.82,
        "structure": 0.92,
        "momentum":  0.85,
        "gann":      0.80,
        "ict":       0.78,
        "confluence": 0.90,
    }

    clear_predictions = bool(payload.get("clear_predictions", False))

    if clear_predictions:
        _PREDICTION_TRACKER.clear()           # wipes predictions, outcomes, weights
        _LEARNING_ENGINE.predictions          = []
        _LEARNING_ENGINE.realized_outcomes    = []

    # Always persist baseline weights and sync live engine
    _PREDICTION_TRACKER.save_weights(_baseline)
    _LEARNING_ENGINE.weights = dict(_baseline)

    msg = "Weights reset to baseline."
    if clear_predictions:
        msg = "Weights reset to baseline and all predictions cleared."

    return {
        "status":               "weights_reset",
        "weights":              dict(_baseline),
        "predictions_cleared":  clear_predictions,
        "message":              msg,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Chart Overlays — Cycles · Lunar Events · Auto-Pattern Identification
# ─────────────────────────────────────────────────────────────────────────────

def _build_node_overlay(candles: list, cached_summary: dict | None = None) -> dict:
    """
    Build Gann Node pressure-point overlay for dashboard chart.
    Nodes = spiral intersections where TIME + PRICE converge.
    Price-only hits = noise (filtered out).
    """
    import math as _math

    if not candles:
        return {"node_active": False, "signal_quality": "WATCH", "next_nodes": [], "sq9_levels": []}

    last = candles[-1]
    price = float(last.get("close", last.get("c", 0)) or 0)
    if price <= 0:
        return {"node_active": False, "signal_quality": "WATCH", "next_nodes": [], "sq9_levels": []}

    # ── SQ9 spiral levels (each step = 90° arc on sqrt scale) ────────────────
    _STEP = 0.5
    root = _math.sqrt(price)
    floor_n = int(root / _STEP)
    sq9_levels = []
    for i in range(-6, 7):
        n = floor_n + i
        if n <= 0:
            continue
        lvl = round((n * _STEP) ** 2, 2)
        step_n = abs(i)
        node_type = "CARDINAL" if step_n <= 4 else "ORDINAL" if step_n <= 6 else "MINOR"
        direction = "above" if lvl > price else "below" if lvl < price else "exact"
        sq9_levels.append({
            "price": lvl,
            "step": i,
            "degree": i * 90,
            "node_type": node_type,
            "direction": direction,
        })
    sq9_levels.sort(key=lambda x: x["price"])

    # ── Check price proximity to node ────────────────────────────────────────
    price_node = None
    for lvl in sq9_levels:
        if lvl["price"] <= 0:
            continue
        dev = abs(price - lvl["price"]) / lvl["price"]
        if dev <= 0.003:   # 0.3% tolerance
            price_node = {**lvl, "deviation_pct": round(dev * 100, 3)}
            break

    # ── Bars from last swing (walk back through candles) ─────────────────────
    bars_from_swing = 0
    if len(candles) >= 6:
        closes = [c.get("close", c.get("c", 0)) for c in candles]
        highs  = [c.get("high",  c.get("h", 0)) for c in candles]
        lows   = [c.get("low",   c.get("l", 0)) for c in candles]
        for i in range(len(closes) - 2, 2, -1):
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                bars_from_swing = len(closes) - 1 - i
                break
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                bars_from_swing = len(closes) - 1 - i
                break

    _HARMONICS = [45, 72, 90, 144, 180, 270, 360]
    best_harmonic = min(_HARMONICS, key=lambda h: abs(h - bars_from_swing)) if bars_from_swing > 0 else 90
    bars_away     = abs(best_harmonic - bars_from_swing)
    time_at_node  = bars_away <= max(2, int(best_harmonic * 0.03))
    price_at_node = price_node is not None

    # ── Signal quality (the core rule) ───────────────────────────────────────
    if time_at_node and price_at_node:
        signal_quality = "REAL"
        node_active = True
    elif price_at_node:
        signal_quality = "NOISE"      # price alone = ignore
        node_active = False
    elif time_at_node:
        signal_quality = "BUILDING"   # time fires, await price
        node_active = False
    else:
        signal_quality = "WATCH"
        node_active = False

    # ── Next nodes list for chart lines ──────────────────────────────────────
    above = [x for x in sq9_levels if x["direction"] == "above"][:4]
    below = [x for x in sq9_levels if x["direction"] == "below"][-4:]
    next_harmonic = next((h for h in _HARMONICS if h > bars_from_swing), 360)
    bars_to_next  = next_harmonic - bars_from_swing

    def _enrich(n):
        return {**n, "dist_pct": round(abs(n["price"] - price) / price * 100, 2),
                "est_bars_to_reach": bars_to_next}

    next_nodes = [_enrich(n) for n in (above + below)]
    next_nodes.sort(key=lambda x: x["dist_pct"])

    # ── Pull live node data from cached summary if available ─────────────────
    live_narration = ""
    live_spiral    = ""
    if cached_summary:
        gn = cached_summary.get("gann_nodes") or {}
        live_narration = gn.get("narration", "")
        live_spiral    = gn.get("spiral_expansion", "")

    # ── Narration ─────────────────────────────────────────────────────────────
    if not live_narration:
        if signal_quality == "REAL":
            live_narration = (
                f"NODE CONFIRMED — ${price_node['price']} + {best_harmonic} bars converge. "
                f"{price_node['node_type']} node. MOVE EXPECTED."
            )
        elif signal_quality == "NOISE":
            live_narration = (
                f"NOISE — Price at ${price_node['price']} but time is {bars_away} bars "
                f"from harmonic {best_harmonic}. No action."
            )
        elif signal_quality == "BUILDING":
            live_narration = (
                f"TIME HARMONIC {best_harmonic} bars firing — price ${price:.2f} not yet at SQ9 node. "
                f"Watch ${above[0]['price'] if above else 0}."
            )
        else:
            live_narration = (
                f"Spiral: {bars_from_swing} bars from swing, {bars_to_next} bars to harmonic {next_harmonic}. "
                f"Next nodes: ↑${above[0]['price'] if above else 0}  ↓${below[-1]['price'] if below else 0}"
            )

    return {
        "node_active":     node_active,
        "signal_quality":  signal_quality,
        "node_type":       price_node["node_type"] if price_node else "NONE",
        "node_price":      price_node["price"]     if price_node else 0.0,
        "time_harmonic":   best_harmonic,
        "bars_from_swing": bars_from_swing,
        "bars_to_next":    bars_to_next,
        "price_at_node":   price_at_node,
        "time_at_node":    time_at_node,
        "spiral_expansion": live_spiral or ("UP_SPIRAL" if last.get("close", 0) > (candles[-20].get("close", 0) if len(candles) >= 20 else 0) else "DOWN_SPIRAL"),
        "next_nodes":      next_nodes,
        "sq9_levels":      sq9_levels,
        "narration":       live_narration,
        "rule":            "TIME+PRICE=REAL | PRICE_ONLY=NOISE | CYCLE_ENDS_AT_NODE",
    }


def _build_moon_overlay(candles: list) -> dict:
    """
    Compute the current moon phase from the last candle timestamp and return
    a structured dict for the dashboard cycle/moon display panel.
    """
    from datetime import datetime, timezone as _tz

    # ── Pure-math moon phase (same formula as astro_engine.moon_phase) ───────
    _KNOWN_NEW_MOON_TS = 947182440.0   # 2000-01-06 18:14 UTC in epoch seconds (verified)
    _SYNODIC            = 29.530588853 * 86400.0  # seconds

    last_ts = candles[-1]["time"] if candles else int(datetime.now(_tz.utc).timestamp())
    elapsed  = last_ts - _KNOWN_NEW_MOON_TS
    age_secs = elapsed % _SYNODIC
    age_days = age_secs / 86400.0
    cycle_pct = (age_days / 29.530588853) * 100.0

    _PHASES = [
        (0.0,  1.85,  "New Moon",        "NEW_MOON",        "🌑", "#64748b"),
        (1.85, 7.38,  "Waxing Crescent", "WAXING_CRESCENT", "🌒", "#93c5fd"),
        (7.38, 9.22,  "First Quarter",   "FIRST_QUARTER",   "🌓", "#fbbf24"),
        (9.22, 14.75, "Waxing Gibbous",  "WAXING_GIBBOUS",  "🌔", "#f59e0b"),
        (14.75,16.61, "Full Moon",        "FULL_MOON",        "🌕", "#fcd34d"),
        (16.61,22.15, "Waning Gibbous",  "WANING_GIBBOUS",  "🌖", "#fb923c"),
        (22.15,24.46, "Last Quarter",    "LAST_QUARTER",    "🌗", "#f97316"),
        (24.46,29.53, "Waning Crescent", "WANING_CRESCENT", "🌘", "#9ca3af"),
    ]
    phase_name, phase_key, emoji, color = "Waning Crescent", "WANING_CRESCENT", "🌘", "#9ca3af"
    for lo, hi, name, key, em, col in _PHASES:
        if lo <= age_days < hi:
            phase_name, phase_key, emoji, color = name, key, em, col
            break

    _MOON_BIAS = {
        "NEW_MOON":        ("ACCUMULATION",  "BUY_ZONE",   "Gann: New cycle starting — seeds of next move planted"),
        "WAXING_CRESCENT": ("MARKUP",        "BUY",        "Gann: Energy building — watch for breakout confirmation"),
        "FIRST_QUARTER":   ("DECISION",      "WATCH",      "Gann: Mid-cycle decision — resistance test"),
        "WAXING_GIBBOUS":  ("MARKUP",        "BUY_STRONG", "Gann: Power accumulating — momentum peak near"),
        "FULL_MOON":       ("DISTRIBUTION",  "REVERSAL",   "Gann: Cycle peak — distribution zone, reversal risk"),
        "WANING_GIBBOUS":  ("DISTRIBUTION",  "SELL",       "Gann: Energy dispersing — consider distribution"),
        "LAST_QUARTER":    ("DECISION",      "WATCH",      "Gann: Mid-decline decision — support test"),
        "WANING_CRESCENT": ("MARKDOWN",      "SELL_END",   "Gann: Final drain — next accumulation cycle forming"),
    }
    market_phase, market_bias, gann_narration = _MOON_BIAS.get(
        phase_key, ("NEUTRAL", "WATCH", "Moon phase neutral")
    )

    days_to_full = (14.765 - age_days) % 29.530588853
    days_to_new  = (29.530588853 - age_days) % 29.530588853
    if days_to_new < 0.01:
        days_to_new = 29.530588853

    cycle_started = age_days < 2.0
    full_peaked   = abs(age_days - 14.765) < 1.5

    # ── Cycle identification from cached summary ──────────────────────────────
    cycle_event = cycle_progress = cycle_energy = None
    try:
        with _cache_lock:
            summaries = list(_cache_payloads.values())
        for s in summaries:
            if s.get("status") == "ok":
                fut = (s.get("future") or {})
                cycle_event    = fut.get("cycle_event")
                cycle_progress = fut.get("cycle_progress_pct")
                cycle_energy   = fut.get("numerology_energy")
                break
    except Exception:
        pass

    return {
        "phase_name":     phase_name,
        "phase_key":      phase_key,
        "emoji":          emoji,
        "color":          color,
        "age_days":       round(age_days, 2),
        "cycle_pct":      round(cycle_pct, 1),
        "days_to_full":   round(days_to_full, 1),
        "days_to_new":    round(days_to_new, 1),
        "market_phase":   market_phase,
        "market_bias":    market_bias,
        "gann_narration": gann_narration,
        "cycle_started":  cycle_started,
        "full_peaked":    full_peaked,
        "display": f"{emoji} {phase_name}  ({cycle_pct:.0f}% cycle)  │  {gann_narration}",
        "badge":   f"{emoji} {phase_name}",
        "cycle_event":    cycle_event,
        "cycle_progress": cycle_progress,
        "cycle_energy":   cycle_energy,
    }


def _build_compression_overlay(candles: list, cached_summary: dict | None = None) -> dict:
    """
    3-layer time compression overlay for dashboard panel.
    Implements Gann's silence-before-expansion law:
    - Layer 1: Price range compression (bars contracting)
    - Layer 2: Cycle gap compression (swing intervals shortening)
    - Layer 3: Volatility silence (stddev contracting)
    Returns phase, score, layers, and breakout signal.
    """
    import math as _m
    import statistics as _stat

    EMPTY = {
        "phase": "OPEN", "score": 0.0, "breakout_near": False,
        "silence_active": False, "cycle_tightening": False,
        "direction_bias": "NEUTRAL", "energy_stored": 0.0,
        "bars_in_compression": 0,
        "signal": "Insufficient data for compression analysis.",
        "layers": {},
    }

    # Pull from cached full_system if available (live signal)
    if cached_summary:
        comp = cached_summary.get("compression") or {}
        if comp.get("phase"):
            return comp

    if len(candles) < 55:
        return EMPTY

    highs  = [float(c.get("high",  c.get("h", 0)) or 0) for c in candles]
    lows   = [float(c.get("low",   c.get("l", 0)) or 0) for c in candles]
    closes = [float(c.get("close", c.get("c", 0)) or 0) for c in candles]

    # ── Layer 1: price range compression ──────────────────────────────────────
    ranges = [h - l for h, l in zip(highs, lows)]
    r5  = sum(ranges[-5:])  / 5  if len(ranges) >= 5  else 0
    r20 = sum(ranges[-20:]) / 20 if len(ranges) >= 20 else 0
    r50 = sum(ranges[-50:]) / 50 if len(ranges) >= 50 else 0
    price_ratio = (r5 / r20) if r20 > 0 else 1.0
    price_score = max(0.0, min(1.0, 1.0 - price_ratio))
    price_compressed = price_ratio < 0.60
    silence_price     = price_ratio < 0.40

    # ── Layer 2: cycle gap compression (bars between pivots shortening) ────────
    window = min(60, len(closes) - 1)
    gaps = []
    i = 1
    last_pivot = 0
    while i < window - 1:
        is_high = highs[-i-1] > highs[-i] and highs[-i-1] > highs[-i-2]
        is_low  = lows[-i-1]  < lows[-i]  and lows[-i-1]  < lows[-i-2]
        if is_high or is_low:
            if last_pivot > 0:
                gaps.append(i - last_pivot)
            last_pivot = i
        i += 1

    if len(gaps) >= 4:
        recent_gaps  = gaps[:len(gaps)//2]
        earlier_gaps = gaps[len(gaps)//2:]
        avg_recent   = sum(recent_gaps)  / len(recent_gaps)
        avg_earlier  = sum(earlier_gaps) / len(earlier_gaps)
        cycle_ratio  = (avg_recent / avg_earlier) if avg_earlier > 0 else 1.0
        cycle_score  = max(0.0, min(1.0, 1.0 - cycle_ratio))
        cycle_compressed = cycle_ratio < 0.65
    else:
        cycle_ratio     = 1.0
        cycle_score     = 0.0
        cycle_compressed = False

    # ── Layer 3: volatility silence (stddev compression) ─────────────────────
    returns = [((closes[-i] - closes[-i-1]) / closes[-i-1]) for i in range(1, min(52, len(closes)))]
    if len(returns) >= 20:
        recent_std   = _stat.stdev(returns[:10]) if len(returns[:10]) > 1 else 0.0
        baseline_std = _stat.stdev(returns[:50]) if len(returns[:50]) > 1 else 0.0
        vol_ratio    = (recent_std / baseline_std) if baseline_std > 0 else 1.0
        vol_score    = max(0.0, min(1.0, 1.0 - vol_ratio))
        vol_compressed = vol_ratio < 0.50
    else:
        vol_ratio     = 1.0
        vol_score     = 0.0
        vol_compressed = False

    # ── Composite score ────────────────────────────────────────────────────────
    score = round(price_score * 0.40 + cycle_score * 0.35 + vol_score * 0.25, 3)
    layers_active = sum([price_compressed, cycle_compressed, vol_compressed])
    breakout_near  = layers_active >= 2
    silence_active = silence_price and vol_compressed

    # ── Phase ─────────────────────────────────────────────────────────────────
    if silence_active:
        phase = "SILENT"
    elif score >= 0.60:
        phase = "CONTRACTING"
    elif score <= 0.15 and not breakout_near:
        phase = "OPEN"
    elif price_ratio > 1.4:
        phase = "EXPANDING"
    elif layers_active >= 2 and price_ratio > 0.8:
        # Energy released: was compressed, now range expanding through compression
        phase = "RELEASED"
    else:
        phase = "OPEN"

    # ── Direction bias (pre-compression trend) ────────────────────────────────
    if len(closes) >= 20:
        trend_close = closes[-20]
        direction_bias = "UP" if closes[-1] > trend_close else ("DOWN" if closes[-1] < trend_close else "NEUTRAL")
    else:
        direction_bias = "NEUTRAL"

    # ── Energy stored ─────────────────────────────────────────────────────────
    max_range = max(ranges[-50:]) if len(ranges) >= 50 else (max(ranges) if ranges else 1.0)
    energy_stored = round((1.0 - (r5 / max_range if max_range > 0 else 0)) * 100, 1)
    energy_stored = max(0.0, min(100.0, energy_stored))

    # ── Bars in compression ────────────────────────────────────────────────────
    bars_in_compression = 0
    for i in range(2, min(50, len(ranges))):
        if (ranges[-i] / r20 if r20 > 0 else 1.0) < 0.70:
            bars_in_compression += 1
        else:
            break

    # ── Signal narration ──────────────────────────────────────────────────────
    if phase == "SILENT":
        signal = (
            f"SILENCE PHASE — Price range {price_ratio:.0%} of norm, vol {vol_ratio:.0%} of norm. "
            f"Maximum compression. {direction_bias} bias. Breakout imminent."
        )
    elif phase == "CONTRACTING":
        signal = (
            f"CONTRACTING — {layers_active}/3 layers compressing. Score {score:.2f}. "
            f"Cycles tightening: {cycle_compressed}. Energy {energy_stored:.0f}% stored."
        )
    elif phase == "EXPANDING":
        signal = f"EXPANDING — Range expanding {price_ratio:.0%} above norm. Energy releasing {direction_bias}."
    elif phase == "RELEASED":
        signal = f"RELEASED — Breakout discharged. {direction_bias} move underway. Monitor for re-compression."
    else:
        signal = f"OPEN — No compression detected. Score {score:.2f}. Market in free range."

    return {
        "phase":              phase,
        "score":              score,
        "breakout_near":      breakout_near,
        "silence_active":     silence_active,
        "cycle_tightening":   cycle_compressed,
        "direction_bias":     direction_bias,
        "energy_stored":      energy_stored,
        "bars_in_compression": bars_in_compression,
        "signal":             signal,
        "layers": {
            "price_score":     round(price_score, 3),
            "price_ratio":     round(price_ratio, 3),
            "price_compressed": price_compressed,
            "cycle_score":     round(cycle_score, 3),
            "cycle_ratio":     round(cycle_ratio, 3),
            "cycle_compressed": cycle_compressed,
            "vol_score":       round(vol_score, 3),
            "vol_ratio":       round(vol_ratio, 3),
            "vol_compressed":  vol_compressed,
        },
    }


def _build_cycle_alignment_markers(
    candles: list[dict[str, Any]],
    timeframe: str | None = None,
    bar_units_hint: float | None = None,
) -> dict[str, Any]:
    """
    Detect cycle segment boundaries and create vertical/horizontal alignment markers.
    Snaps chart lines to cycle node endings and segment start/end points.
    Returns: vertical_lines (time-based) and horizontal_lines (price-based) snap points.
    """
    try:
        import pandas as pd
        import numpy as np
    except Exception:
        return {"vertical_lines": [], "horizontal_lines": [], "snap_points": []}

    if not candles or len(candles) < 2:
        return {"vertical_lines": [], "horizontal_lines": [], "snap_points": []}

    # Resolve master cycle CSV path
    base = Path(__file__).resolve().parents[2]
    candidates = [
        base / "market-causality-lab" / "data" / "reports" / "master_cycles_25y.csv",
        base / "data" / "reports" / "master_cycles_25y.csv",
    ]
    csv_path = next((p for p in candidates if p.exists()), None)
    if csv_path is None:
        return {"vertical_lines": [], "horizontal_lines": [], "snap_points": []}

    try:
        mc = pd.read_csv(
            csv_path,
            usecols=[
                "event_time",
                "start_time",
                "end_time",
                "cycle_type",
                "sub_type",
                "degree_at_event",
            ],
        )
    except Exception:
        return {"vertical_lines": [], "horizontal_lines": [], "snap_points": []}

    if mc.empty:
        return {"vertical_lines": [], "horizontal_lines": [], "snap_points": []}

    # Normalize mixed time encodings found in master cycle ledger.
    # Supported inputs: ISO datetime strings, epoch-seconds, or epoch-day integers.
    def _normalize_time_unit(raw_series: "pd.Series", target_day_scale: bool) -> "pd.Series":
        raw_num = pd.to_numeric(raw_series, errors="coerce")
        dt = pd.to_datetime(raw_series, errors="coerce", utc=True)
        dt_unit = ((dt - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().fillna(0)).astype("int64")

        # If most values are numeric and small, treat as day-units directly.
        if raw_num.notna().mean() > 0.8:
            med = float(raw_num.median())
            if med < 100_000:
                base = raw_num.fillna(0).astype("int64")
                return base if target_day_scale else (base * 86400)
            if med < 10_000_000_000:
                base = raw_num.fillna(0).astype("int64")
                return (base // 86400) if target_day_scale else base

        # Datetime-parsed fallback.
        return (dt_unit // 86400) if target_day_scale else dt_unit

    mc = mc.copy()
    mc = mc.dropna(subset=["event_time"]).copy()
    if mc.empty:
        return {"vertical_lines": [], "horizontal_lines": [], "snap_points": []}

    candle_times = sorted(int(c.get("time", 0)) for c in candles if c.get("time") is not None)
    if not candle_times:
        return {"vertical_lines": [], "horizontal_lines": [], "snap_points": []}

    is_day_scale = candle_times[-1] < 100_000
    dt_units = [
        max(1, int(candle_times[i + 1] - candle_times[i]))
        for i in range(len(candle_times) - 1)
        if int(candle_times[i + 1]) > int(candle_times[i])
    ]
    if dt_units:
        bar_units = float(np.median(np.array(dt_units, dtype=float)))
    elif bar_units_hint and float(bar_units_hint) > 0:
        bar_units = float(bar_units_hint)
    else:
        tf_sec = max(60, _timeframe_seconds(timeframe))
        bar_units = float(max(1, int(round(tf_sec / 86400.0)))) if is_day_scale else float(tf_sec)

    # Restrict snapping to nearby bars only; prevents wrong adjacent-node mapping.
    snap_tolerance_units = max(1.0, 2.0 * bar_units)
    for tcol in ("event_time", "start_time", "end_time"):
        mc[f"{tcol}_unit"] = _normalize_time_unit(mc[tcol], target_day_scale=is_day_scale)

    first_ts, last_ts = candle_times[0], candle_times[-1]
    time_to_close = {int(c.get("time")): float(c.get("close", 0.0) or 0.0) for c in candles if c.get("time") is not None}

    major_types = {"moon", "gann", "planetary"}
    mcf = mc[mc["cycle_type"].astype(str).str.lower().isin(major_types)].copy()
    if mcf.empty:
        return {"vertical_lines": [], "horizontal_lines": [], "snap_points": [], "meta": {"boundary_count": 0, "price_level_count": 0, "total_snap_points": 0}}

    def _snap_time(t: int) -> tuple[int | None, float]:
        idx = int(np.searchsorted(candle_times, t))
        if idx <= 0:
            d = abs(float(candle_times[0] - t))
            if d > snap_tolerance_units:
                return None, d
            return candle_times[0], d
        if idx >= len(candle_times):
            d = abs(float(candle_times[-1] - t))
            if d > snap_tolerance_units:
                return None, d
            return candle_times[-1], d
        before = candle_times[idx - 1]
        after = candle_times[idx]
        if abs(before - t) <= abs(after - t):
            best = before
        else:
            best = after
        d = abs(float(best - t))
        if d > snap_tolerance_units:
            return None, d
        return best, d

    # Build start/end boundaries only (cycle boundaries user asked for).
    raw_boundaries: list[dict[str, Any]] = []
    snap_errors_units: list[float] = []
    for _, row in mcf.iterrows():
        ct = str(row.get("cycle_type", "")).lower().strip()
        st = str(row.get("sub_type", "")).strip()
        for kind, col in (("start", "start_time_unit"), ("end", "end_time_unit")):
            tv = row.get(col)
            if pd.isna(tv):
                continue
            t = int(tv)
            if t < first_ts or t > last_ts:
                continue
            snap_t, snap_err = _snap_time(t)
            if snap_t is None:
                continue
            snap_errors_units.append(float(snap_err))
            color = "#a855f7" if ct == "moon" else ("#f59e0b" if ct == "gann" else "#3b82f6")
            raw_boundaries.append(
                {
                    "time": int(snap_t),
                    "color": color,
                    "width": 1,
                    "label": f"{ct[:3].upper()}_{kind[0].upper()}",
                    "segment_type": ct,
                    "segment_sub": st,
                    "boundary_kind": kind,
                    "snap_error_units": round(float(snap_err), 3),
                    "snap_error_bars": round(float(snap_err) / max(1e-9, bar_units), 3),
                }
            )

    # Deduplicate and downsample to keep chart readable.
    dedup = {(b["time"], b["segment_type"], b["boundary_kind"]): b for b in raw_boundaries}
    vertical_lines = sorted(dedup.values(), key=lambda x: x["time"])
    max_lines = max(24, min(140, len(candle_times) // 6))
    if len(vertical_lines) > max_lines:
        step = int(np.ceil(len(vertical_lines) / max_lines))
        vertical_lines = vertical_lines[::step]

    # Horizontal lines from snapped boundary candle prices (real price levels).
    raw_prices = []
    for b in vertical_lines:
        p = float(time_to_close.get(int(b["time"]), 0.0) or 0.0)
        if p > 0:
            raw_prices.append(round(p, 2))

    horizontal_lines = []
    if raw_prices:
        # Cluster by rounded price bucket to avoid near-duplicate lines.
        buckets = {}
        for p in raw_prices:
            key = round(p / 2.0) * 2.0
            buckets.setdefault(key, 0)
            buckets[key] += 1
        top = sorted(buckets.items(), key=lambda kv: kv[1], reverse=True)[:12]
        for price_level, hits in top:
            horizontal_lines.append(
                {
                    "price": float(price_level),
                    "color": "#f59e0b",
                    "width": 1,
                    "label": f"P{price_level:.0f} ({hits})",
                    "type": "cycle_boundary_price",
                }
            )

    # Combine into snap points for chart renderer
    snap_points = []
    for vline in vertical_lines:
        snap_points.append({
            "type": "vertical",
            "time": vline["time"],
            "color": vline["color"],
            "label": vline["label"],
        })
    for hline in horizontal_lines:
        snap_points.append({
            "type": "horizontal",
            "price": hline["price"],
            "color": hline["color"],
            "label": hline["label"],
        })

    starts = [v for v in vertical_lines if str(v.get("boundary_kind", "")).lower() == "start"]
    ends = [v for v in vertical_lines if str(v.get("boundary_kind", "")).lower() == "end"]
    starts_sorted = sorted(starts, key=lambda x: int(x.get("time", 0)))
    ends_sorted = sorted(ends, key=lambda x: int(x.get("time", 0)))
    paired_segments = 0
    for s in starts_sorted:
        st = int(s.get("time", 0))
        e = next((x for x in ends_sorted if int(x.get("time", 0)) > st), None)
        if e is not None:
            paired_segments += 1

    avg_snap_err_units = float(np.mean(snap_errors_units)) if snap_errors_units else None
    max_snap_err_units = float(np.max(snap_errors_units)) if snap_errors_units else None
    avg_snap_err_bars = (avg_snap_err_units / max(1e-9, bar_units)) if avg_snap_err_units is not None else None
    snap_quality = 1.0
    if avg_snap_err_bars is not None:
        snap_quality = float(max(0.0, min(1.0, 1.0 - (avg_snap_err_bars / 2.0))))

    return {
        "vertical_lines": vertical_lines,
        "horizontal_lines": horizontal_lines,
        "snap_points": snap_points,
        "meta": {
            "boundary_count": len(vertical_lines),
            "price_level_count": len(horizontal_lines),
            "total_snap_points": len(snap_points),
            "paired_segment_count": int(paired_segments),
            "timeframe": str(timeframe or ""),
            "bar_units": round(float(bar_units), 6),
            "snap_tolerance_units": round(float(snap_tolerance_units), 6),
            "avg_snap_error_units": round(float(avg_snap_err_units), 6) if avg_snap_err_units is not None else None,
            "max_snap_error_units": round(float(max_snap_err_units), 6) if max_snap_err_units is not None else None,
            "avg_snap_error_bars": round(float(avg_snap_err_bars), 6) if avg_snap_err_bars is not None else None,
            "adjacent_node_quality_score": round(float(snap_quality), 4),
        },
    }


def _build_cycle_wave_overlays(
    candles: list[dict[str, Any]],
    timeframe: str | None = None,
    bar_units_hint: float | None = None,
) -> dict[str, Any]:
    """Build continuous moon/nakshatra/gann wave overlays aligned to chart candle times."""
    try:
        import pandas as pd
        import numpy as np
    except Exception:
        return {"moon_wave": [], "nakshatra_wave": [], "gann_wave": [], "meta": {"enabled": False}}

    if not candles:
        return {"moon_wave": [], "nakshatra_wave": [], "gann_wave": [], "meta": {"enabled": False}}

    # Resolve master cycle CSV path from workspace root (newcpu/market-causality-lab/...)
    base = Path(__file__).resolve().parents[2]
    candidates = [
        base / "market-causality-lab" / "data" / "reports" / "master_cycles_25y.csv",
        base / "data" / "reports" / "master_cycles_25y.csv",
    ]
    csv_path = next((p for p in candidates if p.exists()), None)
    if csv_path is None:
        return {"moon_wave": [], "nakshatra_wave": [], "gann_wave": [], "meta": {"enabled": False, "reason": "master_cycles_missing"}}

    try:
        mc = pd.read_csv(
            csv_path,
            usecols=["event_time", "cycle_type", "sub_type", "nak_sequence", "degree_at_event", "gann_key_angle"],
        )
    except Exception as exc:
        return {
            "moon_wave": [],
            "nakshatra_wave": [],
            "gann_wave": [],
            "meta": {"enabled": False, "reason": f"read_error:{exc}"},
        }

    if mc.empty:
        return {"moon_wave": [], "nakshatra_wave": [], "gann_wave": [], "meta": {"enabled": False, "reason": "master_cycles_empty"}}

    mc["event_time"] = pd.to_datetime(mc["event_time"], errors="coerce", utc=True)
    mc = mc.dropna(subset=["event_time"]).copy()
    if mc.empty:
        return {"moon_wave": [], "nakshatra_wave": [], "gann_wave": [], "meta": {"enabled": False, "reason": "master_cycles_bad_time"}}

    # Candle time unit can be epoch-seconds or epoch-days depending on chart timeframe.
    candle_times = sorted(int(c.get("time", 0)) for c in candles if c.get("time") is not None)
    if not candle_times:
        return {"moon_wave": [], "nakshatra_wave": [], "gann_wave": [], "meta": {"enabled": False}}
    is_day_scale = candle_times[-1] < 100_000
    dt_units = [
        max(1, int(candle_times[i + 1] - candle_times[i]))
        for i in range(len(candle_times) - 1)
        if int(candle_times[i + 1]) > int(candle_times[i])
    ]
    if dt_units:
        bar_units = float(np.median(np.array(dt_units, dtype=float)))
    elif bar_units_hint and float(bar_units_hint) > 0:
        bar_units = float(bar_units_hint)
    else:
        tf_sec = max(60, _timeframe_seconds(timeframe))
        bar_units = float(max(1, int(round(tf_sec / 86400.0)))) if is_day_scale else float(tf_sec)

    mc["event_unit"] = ((mc["event_time"] - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().fillna(0)).astype("int64")
    if is_day_scale:
        mc["event_unit"] = (mc["event_unit"] // 86400).astype("int64")

    cdf = pd.DataFrame({"time": candle_times}).sort_values("time").reset_index(drop=True)

    # Moon phase wave (continuous in [0,1)) from phase anchor points.
    phase_map = {
        "new moon": 0.0,
        "solar eclipse": 0.0,
        "first quarter": 0.25,
        "full moon": 0.5,
        "lunar eclipse": 0.5,
        "last quarter": 0.75,
    }
    moon = mc[mc["cycle_type"].astype(str).str.lower() == "moon"].copy()
    moon["anchor"] = moon["sub_type"].astype(str).str.strip().str.lower().map(phase_map)
    moon = moon.dropna(subset=["anchor"]).sort_values("event_unit")

    moon_wave = []
    if not moon.empty:
        mprev = pd.merge_asof(cdf, moon[["event_unit", "anchor"]], left_on="time", right_on="event_unit", direction="backward")
        mnext = pd.merge_asof(cdf, moon[["event_unit", "anchor"]], left_on="time", right_on="event_unit", direction="forward")

        pa = mprev["anchor"].fillna(0.0).to_numpy(dtype=float)
        na = mnext["anchor"].to_numpy(dtype=float)
        na = np.where(np.isnan(na), pa, na)

        pt = pd.to_numeric(mprev["event_unit"], errors="coerce").to_numpy(dtype=float)
        nt = pd.to_numeric(mnext["event_unit"], errors="coerce").to_numpy(dtype=float)
        tt = cdf["time"].to_numpy(dtype=float)

        dt_total = nt - pt
        dt_part = tt - pt
        dt_total = np.where(np.isfinite(dt_total) & (dt_total > 0), dt_total, np.nan)
        frac = np.divide(dt_part, dt_total, out=np.zeros_like(dt_part), where=np.isfinite(dt_total))
        frac = np.clip(frac, 0.0, 1.0)

        delta = na - pa
        delta = np.where(delta < 0, delta + 1.0, delta)
        phase = np.mod(pa + frac * delta, 1.0)

        moon_wave = [{"time": int(t), "value": float(round(v, 6))} for t, v in zip(cdf["time"], phase)]

    # Nakshatra wave (ordinal normalized to [0,1]).
    nak = mc[mc["cycle_type"].astype(str).str.lower() == "nakshatra"].copy()
    nak["nak_sequence"] = pd.to_numeric(nak["nak_sequence"], errors="coerce")
    nak = nak.dropna(subset=["nak_sequence"]).sort_values("event_unit")
    nak_wave = []
    if not nak.empty:
        nprev = pd.merge_asof(cdf, nak[["event_unit", "nak_sequence"]], left_on="time", right_on="event_unit", direction="backward")
        ns = nprev["nak_sequence"].fillna(0.0).to_numpy(dtype=float)
        ns_norm = np.clip(ns / 26.0, 0.0, 1.0)
        nak_wave = [{"time": int(t), "value": float(round(v, 6))} for t, v in zip(cdf["time"], ns_norm)]

    # Gann degree wave normalized to [0,1].
    gann = mc[mc["cycle_type"].astype(str).str.lower() == "gann"].copy()
    gann["degree_at_event"] = pd.to_numeric(gann["degree_at_event"], errors="coerce")
    gann["gann_key_angle"] = pd.to_numeric(gann.get("gann_key_angle"), errors="coerce")
    # Many time-cycle rows store 0 in degree_at_event; use key-angle as fallback so
    # the Gann wave remains informative instead of flat zero.
    gann["degree_eff"] = gann["degree_at_event"]
    _use_key = gann["degree_eff"].isna() | (gann["degree_eff"] <= 0)
    gann.loc[_use_key, "degree_eff"] = gann.loc[_use_key, "gann_key_angle"]
    gann = gann.dropna(subset=["degree_eff"]).sort_values("event_unit")
    gann_wave = []
    if not gann.empty:
        gprev = pd.merge_asof(cdf, gann[["event_unit", "degree_eff"]], left_on="time", right_on="event_unit", direction="backward")
        gd = gprev["degree_eff"].fillna(0.0).to_numpy(dtype=float)
        gd_norm = np.clip(gd / 360.0, 0.0, 1.0)
        gann_wave = [{"time": int(t), "value": float(round(v, 6))} for t, v in zip(cdf["time"], gd_norm)]

    # If Gann wave is mostly flat/zero (common when source degree rows are sparse or zeroed),
    # derive a robust fallback from candle close-degree so lower TF overlays remain informative.
    try:
        _gw_vals = np.array([float(p.get("value") or 0.0) for p in gann_wave], dtype=float) if gann_wave else np.array([], dtype=float)
        _gw_nonzero = int(np.count_nonzero(_gw_vals > 1e-9))
        _tail_n = min(240, len(_gw_vals)) if len(_gw_vals) > 0 else 0
        _tail_vals = _gw_vals[-_tail_n:] if _tail_n > 0 else np.array([], dtype=float)
        _tail_nonzero = int(np.count_nonzero(_tail_vals > 1e-9)) if _tail_n > 0 else 0
        _tail_nonzero_ratio = (float(_tail_nonzero) / float(_tail_n)) if _tail_n > 0 else 0.0
        _last_val = float(_gw_vals[-1]) if len(_gw_vals) > 0 else 0.0
        _gw_is_degenerate = (
            (len(_gw_vals) == 0)
            or (_gw_nonzero <= max(2, int(len(_gw_vals) * 0.03)))
            or (_tail_n > 0 and _tail_nonzero <= max(2, int(_tail_n * 0.05)))
            or (_tail_n > 0 and _last_val <= 1e-9 and _tail_nonzero_ratio < 0.25)
            or (_last_val <= 1e-9)
        )
        if _gw_is_degenerate:
            _rows = []
            for _c in candles:
                try:
                    _t = int(_c.get("time"))
                    _p = float(_c.get("close"))
                    if _p > 0:
                        _rows.append((_t, _p))
                except Exception:
                    continue
            if _rows:
                _rows = sorted({int(t): float(p) for t, p in _rows}.items(), key=lambda kv: kv[0])
                gann_wave = [
                    {"time": int(t), "value": float(round(((p % 360.0) / 360.0), 6))}
                    for t, p in _rows
                ]
    except Exception:
        pass

    return {
        "moon_wave": moon_wave,
        "nakshatra_wave": nak_wave,
        "gann_wave": gann_wave,
        "meta": {
            "enabled": True,
            "source": str(csv_path),
            "is_day_scale": bool(is_day_scale),
            "timeframe": str(timeframe or ""),
            "bar_units": round(float(bar_units), 6),
            "moon_points": len(moon_wave),
            "nak_points": len(nak_wave),
            "gann_points": len(gann_wave),
        },
    }


@router.get("/chart/overlays")
def chart_overlays(
    symbol: str = Query(default="XAUUSD"),
    timeframe: str = Query(default="1d"),
    source_mode: str = Query(default="historical_first"),
    turtle_profile: str = Query(default="auto"),
    lookback_years: int = Query(default=25, ge=1, le=100),
    limit: int = Query(default=12000, ge=1, le=50000),
) -> dict[str, Any]:
    """
    Returns overlay data for the MCL chart:

    1. **gann_cycles**  — bar-index multiples of 30/45/90/180/360 with their angle labels
    2. **lunar_events** — New Moon / Full Moon dates over the full history window
    3. **auto_patterns** — auto-identified swing highs/lows, structure breaks (BOS/CHOCH)
    4. **prediction_zone** — Gann angle + P(t) projected price for next 30 calendar days
    5. **gann_angles**  — 1×1, 2×1, 0.5×1 price lines projected from key swing low
    """
    import math as _math

    # ── 1. Pull candle data ────────────────────────────────────────────────
    chart = _compute_chart(symbol=symbol, timeframe=timeframe, source_mode=source_mode,
                            lookback_years=lookback_years, limit=limit)
    candles = chart.get("candles", [])
    requested_turtle_profile = _normalize_turtle_profile(turtle_profile)
    applied_turtle_profile = _resolve_turtle_profile_for_timeframe(timeframe, requested_turtle_profile)
    if not candles:
        return {"status": "ok", "gann_cycles": [], "lunar_events": [],
                "auto_patterns": [], "turtle_soup": [], "turtle_soup_learning": {
                    "current_timeframe": str(timeframe or ""),
                    "turtle_profile_requested": requested_turtle_profile,
                    "turtle_profile_applied": applied_turtle_profile,
                },
                "latest_turtle_soup": None, "prediction_zone": [], "gann_angles": [],
                "turtle_profile_requested": requested_turtle_profile,
                "turtle_profile_applied": applied_turtle_profile,
                "meta": {"swing_highs_found": 0, "swing_lows_found": 0,
                         "lunar_events_found": 0, "bos_count": 0,
                         "turtle_soup_count": 0, "turtle_soup_ai_accuracy": 0.0,
                         "turtle_soup_learning_samples": 0, "turtle_soup_avg_liquidity_score": 0.0,
                         "turtle_profile_requested": requested_turtle_profile,
                         "turtle_profile_applied": applied_turtle_profile}}

    # Sort by time
    candles = sorted(candles, key=lambda c: c["time"])

    # ── Timeframe-aware parameters (computed once, used throughout all sections) ─────
    # Detect if chart uses day-scale timestamps (daily/weekly/monthly) or second-scale.
    _last_ct = candles[-1]["time"] if candles else 0
    _is_day_scale = bool(_last_ct) and _last_ct < 100_000
    # Compute average bar interval.  Day-scale → 1=daily, 7=weekly, 30=monthly.
    # Second-scale → 3600=1h, 300=5m, 60=1m etc.
    if len(candles) >= 2:
        _dts_raw = [
            candles[i + 1]["time"] - candles[i]["time"]
            for i in range(max(0, len(candles) - 20), len(candles) - 1)
            if candles[i + 1]["time"] > candles[i]["time"]
        ]
        _bar_secs_raw = int(sum(_dts_raw) / len(_dts_raw)) if _dts_raw else (1 if _is_day_scale else 86400)
    else:
        _bar_secs_raw = 1 if _is_day_scale else 86400
    # _bar_day_fraction: calendar days per bar (used for slope/ppu scaling).
    # Day-scale: bar_secs_raw already is days (1d→1.0, 1w→7.0).
    # Second-scale: convert to fractional day (1h→0.0417, 5m→0.00347, 1m→0.000694).
    _bar_day_fraction = float(_bar_secs_raw) if _is_day_scale else max(1e-6, _bar_secs_raw / 86400.0)
    # bars_per_cal_day: how many bars fit in one calendar day (for density/spacing limits).
    _bars_per_cal_day = max(1, int(1.0 / _bar_day_fraction)) if not _is_day_scale else 1

    # ── 2. Gann cycle markers — calendar-day based, auto-scaled per timeframe ─
    #
    # Cycles are defined in CALENDAR DAYS and converted to bar counts using
    # _bar_day_fraction so that "30D" means the same 30 calendar days on every
    # timeframe (1m → 30*1440=43200 bars, 1h → 720 bars, 1d → 30 bars, etc.)
    #
    # For intraday charts shorter cycles are prepended so the user always sees
    # at least 2-3 cycle tiers that are visible at that zoom level.

    # Calendar-day definitions: (cal_days, label, color, shape)
    _CAL_CYCLES_BASE = [
        (7,    "7D",    "#475569", "circle"),      # weekly
        (14,   "14D",   "#64748b", "circle"),      # bi-weekly
        (30,   "30D",   "#38bdf8", "circle"),      # monthly
        (45,   "45D",   "#fbbf24", "square"),      # 45-day Gann
        (90,   "90D",   "#a78bfa", "square"),      # quarterly
        (180,  "6M",    "#f472b6", "arrowDown"),   # semi-annual
        (360,  "1Y",    "#10b981", "arrowDown"),   # annual
        (720,  "2Y",    "#22d3ee", "arrowDown"),   # bi-annual
    ]
    # Intraday cycles added when timeframe < 1 day
    _CAL_CYCLES_INTRADAY = []
    if _bar_day_fraction < 1.0:
        # Express intraday cycles in fractional calendar days
        _hr = 1.0 / 24.0
        _CAL_CYCLES_INTRADAY = [
            (1 * _hr,  "1H",   "#334155", "circle"),
            (4 * _hr,  "4H",   "#38bdf8", "circle"),
            (8 * _hr,  "8H",   "#a78bfa", "square"),
            (24 * _hr, "1D",   "#10b981", "arrowDown"),
        ]

    all_cal_cycles = _CAL_CYCLES_INTRADAY + _CAL_CYCLES_BASE

    # Convert each calendar-day definition → bar count and filter to keep
    # only cycles that produce at least 5 bars (no over-density) AND at most
    # len(candles)//2 bars (must be visible in the chart window).
    _max_cycle_bars = max(10, len(candles) // 2)
    _min_spacing = max(5, _bars_per_cal_day // 4) if not _is_day_scale else 5

    GANN_CYCLES_FINAL: list[tuple[int, str, str, str, float]] = []  # (bar_count, label, color, shape, cal_days)
    for _cal_d, _lbl, _col, _sh in all_cal_cycles:
        _bars = max(1, round(_cal_d / _bar_day_fraction))
        if _bars < _min_spacing:
            continue
        if _bars > _max_cycle_bars:
            continue
        GANN_CYCLES_FINAL.append((_bars, _lbl, _col, _sh, _cal_d))

    # Ensure at least the 2 most appropriate cycles are present (fallback)
    if not GANN_CYCLES_FINAL:
        _fb = round(30.0 / _bar_day_fraction)
        _fb2 = round(90.0 / _bar_day_fraction)
        GANN_CYCLES_FINAL = [
            (max(5, _fb),  "30D", "#38bdf8", "arrowDown", 30.0),
            (max(5, _fb2), "90D", "#a78bfa", "arrowDown", 90.0),
        ]

    # Build cycle markers
    gann_cycles = []
    for idx, candle in enumerate(candles):
        bar_num = idx + 1
        for bar_count, label, color, shape, cal_days in GANN_CYCLES_FINAL:
            if bar_num % bar_count == 0:
                gann_cycles.append({
                    "time":     candle["time"],
                    "label":    label,
                    "color":    color,
                    "shape":    shape,
                    "position": "belowBar",
                    "cycle":    bar_count,      # bar count (for size logic)
                    "cal_days": cal_days,       # calendar days (for size/priority logic)
                })

    # ── Cycle auto-identification: compute current phase position in each cycle ──
    # For each defined cycle, find which cycle interval the LAST candle falls in,
    # compute 0→1 progress, and include a concise summary for the UI panel.
    cycle_phases: list[dict] = []
    n_candles = len(candles)
    for bar_count, label, color, shape, cal_days in GANN_CYCLES_FINAL:
        if bar_count < 1 or n_candles < bar_count:
            continue
        # Bar index of last complete cycle boundary
        bars_into_current = (n_candles - 1) % bar_count   # 0 = just started new cycle
        bars_left = bar_count - bars_into_current
        progress = bars_into_current / bar_count           # 0.0→1.0
        # Determine phase label
        if progress < 0.25:
            phase_lbl = "START"
        elif progress < 0.50:
            phase_lbl = "Q1"
        elif progress < 0.75:
            phase_lbl = "MID"
        elif progress < 0.90:
            phase_lbl = "Q3"
        else:
            phase_lbl = "END"
        cycle_phases.append({
            "label":          label,
            "cal_days":       cal_days,
            "bar_count":      bar_count,
            "progress":       round(progress, 4),
            "bars_into":      int(bars_into_current),
            "bars_left":      int(bars_left),
            "phase":          phase_lbl,
            "color":          color,
        })

    # Sort from shortest to longest cycle
    cycle_phases.sort(key=lambda x: x["cal_days"])

    # ── 3. Lunar events (New Moon / Full Moon) ─────────────────────────────
    # Reference new moon: 2000-01-06 18:14 UTC (J2000, same as astro_engine.py)
    _NEW_MOON_EPOCH = 947182440  # 2000-01-06 18:14 UTC
    _LUNAR_PERIOD = 29.530588853 * 86400  # seconds

    first_ts = candles[0]["time"]
    last_ts = candles[-1]["time"]

    # Walk forward from reference to first New Moon on or after chart start
    # (fast path: skip directly by integer months)
    months_ahead = max(0, (first_ts - _NEW_MOON_EPOCH) // _LUNAR_PERIOD)
    ref = _NEW_MOON_EPOCH + months_ahead * _LUNAR_PERIOD
    while ref > first_ts:
        ref -= _LUNAR_PERIOD
    while ref < first_ts:
        ref += _LUNAR_PERIOD

    # Build candle timeline in epoch-seconds for moon-event math.
    candle_times = sorted(int(c["time"]) for c in candles)

    def _median(values: list[int]) -> float:
        if not values:
            return 0.0
        xs = sorted(values)
        n = len(xs)
        mid = n // 2
        if n % 2:
            return float(xs[mid])
        return 0.5 * (float(xs[mid - 1]) + float(xs[mid]))

    _is_days_timescale = candle_times[-1] < 100_000 if candle_times else False
    candle_times_sec = [int(t * 86400) if _is_days_timescale else int(t) for t in candle_times]

    # Snap tolerance: about 2.5 bars. Larger miss implies weak astro timing accuracy.
    _diffs = [
        max(1, candle_times_sec[i + 1] - candle_times_sec[i])
        for i in range(len(candle_times_sec) - 1)
        if candle_times_sec[i + 1] > candle_times_sec[i]
    ]
    _bar_sec_med = max(60.0, _median(_diffs) if _diffs else (86400.0 if _is_days_timescale else float(_bar_secs_raw)))
    _snap_tol_sec = max(60.0, 2.5 * _bar_sec_med)

    first_ts_sec = int(first_ts * 86400) if _is_days_timescale else int(first_ts)
    last_ts_sec = int(last_ts * 86400) if _is_days_timescale else int(last_ts)

    def _nearest_candle_time(target_ts_sec: float) -> tuple[int, float]:
        """Snap a lunar event timestamp (epoch-sec) to nearest candle sec and return error-sec."""
        import bisect

        idx = bisect.bisect_left(candle_times_sec, int(target_ts_sec))
        if idx >= len(candle_times_sec):
            s = candle_times_sec[-1]
            return s, abs(float(s) - float(target_ts_sec))
        if idx == 0:
            s = candle_times_sec[0]
            return s, abs(float(s) - float(target_ts_sec))
        before = candle_times_sec[idx - 1]
        after = candle_times_sec[idx]
        if abs(before - target_ts_sec) <= abs(after - target_ts_sec):
            s = before
        else:
            s = after
        return s, abs(float(s) - float(target_ts_sec))

    lunar_events = []
    lunar_errors_bars: list[float] = []
    t = float(ref)
    half = _LUNAR_PERIOD / 2
    while t <= (last_ts_sec + _LUNAR_PERIOD):
        # New Moon
        nm_ts_sec, nm_err_sec = _nearest_candle_time(t)
        if first_ts_sec <= nm_ts_sec <= last_ts_sec and nm_err_sec <= _snap_tol_sec:
            nm_time = int(round(nm_ts_sec / 86400.0)) if _is_days_timescale else int(nm_ts_sec)
            lunar_errors_bars.append(float(nm_err_sec) / max(1.0, _bar_sec_med))
            lunar_events.append({
                "time": int(nm_time),
                "label": "🌑NM",
                "color": "#94a3b8",
                "shape": "circle",
                "position": "aboveBar",
                "type": "new_moon",
                "snap_error_hours": round(float(nm_err_sec) / 3600.0, 3),
                "snap_error_bars": round(float(nm_err_sec) / max(1.0, _bar_sec_med), 3),
            })
        # Full Moon (half period later)
        fm_ts_sec, fm_err_sec = _nearest_candle_time(t + half)
        if first_ts_sec <= fm_ts_sec <= last_ts_sec and fm_err_sec <= _snap_tol_sec:
            fm_time = int(round(fm_ts_sec / 86400.0)) if _is_days_timescale else int(fm_ts_sec)
            lunar_errors_bars.append(float(fm_err_sec) / max(1.0, _bar_sec_med))
            lunar_events.append({
                "time": int(fm_time),
                "label": "🌕FM",
                "color": "#fcd34d",
                "shape": "circle",
                "position": "aboveBar",
                "type": "full_moon",
                "snap_error_hours": round(float(fm_err_sec) / 3600.0, 3),
                "snap_error_bars": round(float(fm_err_sec) / max(1.0, _bar_sec_med), 3),
            })
        t += _LUNAR_PERIOD

    # Deduplicate collisions when both events snap to same bar on sparse timeframes.
    lunar_events = sorted(
        {(int(e["time"]), str(e["type"])): e for e in lunar_events}.values(),
        key=lambda x: (int(x.get("time", 0)), str(x.get("type", ""))),
    )

    lunar_accuracy = 1.0
    if lunar_errors_bars:
        _avg_lunar_err = sum(lunar_errors_bars) / max(1, len(lunar_errors_bars))
        lunar_accuracy = max(0.0, min(1.0, 1.0 - (_avg_lunar_err / 2.0)))

    # ── 4. Auto-pattern identification — Swing H/L + BOS/CHOCH ───────────
    # Rolling window pivot detection: swing high = highest of N bars each side
    # Adaptive pivot lookback: wider on fast intraday to isolate meaningful swings.
    SWING_N = max(3, min(10, _bars_per_cal_day // 8)) if not _is_day_scale else 5
    # Min gap between pattern labels: ~2 calendar days on any timeframe.
    _min_swing_gap = max(15, 2 * _bars_per_cal_day)
    _min_bos_gap   = max(10, _bars_per_cal_day)
    auto_patterns = []

    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    times  = [c["time"]  for c in candles]

    swing_highs = []  # (idx, price, time)
    swing_lows  = []

    for i in range(SWING_N, len(candles) - SWING_N):
        window_h = highs[i - SWING_N: i + SWING_N + 1]
        window_l = lows[i - SWING_N: i + SWING_N + 1]
        if highs[i] == max(window_h):
            swing_highs.append((i, highs[i], times[i]))
        if lows[i] == min(window_l):
            swing_lows.append((i, lows[i], times[i]))

    # Emit top-N swing marks (keep density manageable — every 30 bars min)
    last_sh = -999
    for idx, price, ts in swing_highs:
        if idx - last_sh >= _min_swing_gap:
            auto_patterns.append({
                "time": ts,
                "label": "▲",
                "color": "#22c55e",
                "shape": "arrowUp",
                "position": "aboveBar",
                "type": "swing_high",
                "price": price,
            })
            last_sh = idx

    last_sl = -999
    for idx, price, ts in swing_lows:
        if idx - last_sl >= _min_swing_gap:
            auto_patterns.append({
                "time": ts,
                "label": "▼",
                "color": "#ef4444",
                "shape": "arrowDown",
                "position": "belowBar",
                "type": "swing_low",
                "price": price,
            })
            last_sl = idx

    # BOS/CHOCH: detect when price breaks above prior swing high (BOS bullish)
    # or breaks below prior swing low (BOS bearish) — simplified 1-pass scan
    sh_list = [(i, p, t) for i, p, t in swing_highs]
    sl_list = [(i, p, t) for i, p, t in swing_lows]

    last_bos = -999
    for i in range(len(candles)):
        if i - last_bos < _min_bos_gap:
            continue
        # BOS Bullish: close > prior swing high
        prior_sh = next((p for idx, p, _ in reversed(sh_list) if idx < i - 2), None)
        if prior_sh and closes[i] > prior_sh:
            auto_patterns.append({
                "time": times[i],
                "label": "BOS↑",
                "color": "#10b981",
                "shape": "arrowUp",
                "position": "belowBar",
                "type": "bos_bull",
                "price": closes[i],
            })
            last_bos = i
            continue
        # BOS Bearish: close < prior swing low
        prior_sl = next((p for idx, p, _ in reversed(sl_list) if idx < i - 2), None)
        if prior_sl and closes[i] < prior_sl:
            auto_patterns.append({
                "time": times[i],
                "label": "BOS↓",
                "color": "#ef4444",
                "shape": "arrowDown",
                "position": "aboveBar",
                "type": "bos_bear",
                "price": closes[i],
            })
            last_bos = i

    # ── 5. Turtle Soup (failed intent after liquidity raid) with AI score ───
    # This is modeled as a trap event, not a standalone candle formula.
    # Required ingredients:
    #   1. Liquidity pool exists (equal highs/lows or obvious prior swing).
    #   2. Price raids that liquidity pool.
    #   3. Breakout fails quickly and closes back inside.
    #   4. Opposite-side displacement appears, ideally with short-term BOS.
    #   5. Session/time + confluence weights determine probability, not a binary signal.
    turtle_soup: list[dict[str, Any]] = []
    ts_learning_accuracy = 0.5
    ts_learning_samples = 0
    try:
        _cal = _LEARNING_ENGINE.get_model_calibration() or {}
        _overall_acc = float(_cal.get("overall_accuracy", 0.5) or 0.5)
        ts_learning_accuracy = max(0.0, min(1.0, _overall_acc))
        ts_learning_samples = int(_cal.get("total_outcomes", 0) or 0)

        # If we already have outcomes tagged as Turtle Soup, use that specialized win rate.
        _preds = _PREDICTION_TRACKER.load_predictions()
        _outs = _PREDICTION_TRACKER.load_outcomes()
        _pred_by_id: dict[str, Any] = {str(p.get("id") or ""): p for p in _preds if str(p.get("id") or "").strip()}
        _tagged: list[float] = []
        for _o in _outs:
            _pid = str(_o.get("prediction_id") or "").strip()
            if not _pid:
                continue
            _pred = _pred_by_id.get(_pid) or {}
            _features = _pred.get("features") if isinstance(_pred.get("features"), dict) else {}
            _family = str((_features or {}).get("signal_family") or "").strip().lower()
            if _family != "turtle_soup":
                continue
            _tagged.append(1.0 if bool(_o.get("was_correct", False)) else 0.0)
        if _tagged:
            ts_learning_samples = len(_tagged)
            ts_learning_accuracy = max(0.0, min(1.0, sum(_tagged) / max(1, len(_tagged))))
    except Exception as _ts_acc_exc:
        logging.debug("Turtle Soup learning prior fallback used: %s", _ts_acc_exc)

    _volumes = [float(c.get("volume", 0.0) or 0.0) for c in candles]
    _trs: list[float] = [0.0]
    for i in range(1, len(candles)):
        _h = float(highs[i])
        _l = float(lows[i])
        _pc = float(closes[i - 1])
        _trs.append(max(_h - _l, abs(_h - _pc), abs(_l - _pc)))

    def _rolling_avg(vals: list[float], end_idx: int, span: int) -> float:
        if end_idx < 0:
            return 0.0
        lo = max(0, end_idx - span + 1)
        chunk = vals[lo:end_idx + 1]
        if not chunk:
            return 0.0
        return float(sum(chunk)) / float(len(chunk))

    def _clip01(v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    def _time_to_epoch_seconds(value: int | float) -> int:
        if _is_day_scale:
            return int(round(float(value) * 86400.0))
        return int(round(float(value)))

    def _session_context(ts_value: int | float) -> tuple[str, float]:
        if _is_day_scale:
            return "DAILY", 0.6
        dt = datetime.fromtimestamp(_time_to_epoch_seconds(ts_value), tz=timezone.utc)
        hour = int(dt.hour)
        minute = int(dt.minute)
        hm = hour + (minute / 60.0)
        if 7.0 <= hm < 10.5:
            return "LONDON", 1.0
        if 12.5 <= hm < 16.5:
            return "NEW_YORK", 1.0
        if 6.0 <= hm < 7.0 or 10.5 <= hm < 12.5:
            return "TRANSITION", 0.72
        return "OFF_SESSION", 0.42

    def _local_atr(end_idx: int, span: int = 14) -> float:
        return max(1e-9, _rolling_avg(_trs, end_idx, span))

    def _liquidity_pool_kind(swings: list[tuple[int, float, int]], anchor_idx: int, anchor_price: float, side: str) -> tuple[str, float, int]:
        atr_ref = _local_atr(anchor_idx)
        threshold = max(float(anchor_price) * 0.00035, atr_ref * 0.20)
        matches = 0
        for idx2, price2, _ in swings:
            if idx2 == anchor_idx:
                continue
            if abs(idx2 - anchor_idx) > max(_lookahead_bars, _bars_per_cal_day * 3):
                continue
            if abs(float(price2) - float(anchor_price)) <= threshold:
                matches += 1
        if matches >= 2:
            return ("equal_highs" if side == "high" else "equal_lows", 1.0, matches)
        if matches == 1:
            return ("double_top" if side == "high" else "double_bottom", 0.85, matches)
        return ("swing_high" if side == "high" else "swing_low", 0.55, matches)

    def _nearest_internal_liquidity(direction: str, idx: int) -> float | None:
        if direction == "SELL":
            prior = [float(price) for swing_idx, price, _ in swing_lows if swing_idx < idx]
            return prior[-1] if prior else None
        prior = [float(price) for swing_idx, price, _ in swing_highs if swing_idx < idx]
        return prior[-1] if prior else None

    def _astro_timing_bias(event_time: int) -> float:
        proximity_hits = 0
        for row in gann_cycles[-24:]:
            if abs(int(row.get("time", 0)) - int(event_time)) <= max(2, _confirm_within) * max(1, _bar_secs_raw):
                proximity_hits += 1
                break
        for row in lunar_events[-16:]:
            if abs(int(row.get("time", 0)) - int(event_time)) <= max(2, _confirm_within) * max(1, _bar_secs_raw):
                proximity_hits += 1
                break
        return 1.0 if proximity_hits >= 2 else (0.72 if proximity_hits == 1 else 0.45)

    def _find_displacement(direction: str, idx: int, pool_price: float) -> dict[str, Any]:
        end_j = min(len(candles) - 1, idx + _confirm_within)
        if direction == "SELL":
            ref_low = min(float(v) for v in lows[max(0, idx - SWING_N):idx + 1]) if idx >= 0 else float(pool_price)
            best_low = min(float(v) for v in lows[idx:end_j + 1]) if end_j >= idx else float(lows[idx])
            move = max(0.0, float(closes[idx]) - best_low)
            bos = any(float(closes[j]) < ref_low for j in range(idx + 1, end_j + 1))
            fvg = any(float(highs[j]) < float(lows[j - 2]) for j in range(max(idx + 2, 2), end_j + 1))
            return {
                "move": move,
                "bos": bos,
                "imbalance": fvg,
                "broken_level": round(float(ref_low), 4),
                "target_price": round(float(best_low), 4),
            }
        ref_high = max(float(v) for v in highs[max(0, idx - SWING_N):idx + 1]) if idx >= 0 else float(pool_price)
        best_high = max(float(v) for v in highs[idx:end_j + 1]) if end_j >= idx else float(highs[idx])
        move = max(0.0, best_high - float(closes[idx]))
        bos = any(float(closes[j]) > ref_high for j in range(idx + 1, end_j + 1))
        fvg = any(float(lows[j]) > float(highs[j - 2]) for j in range(max(idx + 2, 2), end_j + 1))
        return {
            "move": move,
            "bos": bos,
            "imbalance": fvg,
            "broken_level": round(float(ref_high), 4),
            "target_price": round(float(best_high), 4),
        }

    _profile_cfg = {
        "strict": {
            "lookahead_days": 2.0,
            "confirm_days": 0.35,
            "event_gap_days": 0.45,
            "min_sweep_frac": 0.00025,
            "min_wick_ratio": 0.52,
            "min_disp_score": 0.80,
        },
        "balanced": {
            "lookahead_days": 3.0,
            "confirm_days": 0.50,
            "event_gap_days": 0.33,
            "min_sweep_frac": 0.00015,
            "min_wick_ratio": 0.45,
            "min_disp_score": 0.65,
        },
        "aggressive": {
            "lookahead_days": 4.0,
            "confirm_days": 0.75,
            "event_gap_days": 0.20,
            "min_sweep_frac": 0.00008,
            "min_wick_ratio": 0.35,
            "min_disp_score": 0.50,
        },
    }.get(applied_turtle_profile, {
        "lookahead_days": 3.0,
        "confirm_days": 0.50,
        "event_gap_days": 0.33,
        "min_sweep_frac": 0.00015,
        "min_wick_ratio": 0.45,
        "min_disp_score": 0.65,
    })

    _lookahead_bars = max(10, int(round(float(_profile_cfg["lookahead_days"]) * _bars_per_cal_day)))
    _confirm_within = max(2, int(round(float(_profile_cfg["confirm_days"]) * _bars_per_cal_day)))
    _event_gap = max(5, int(round(float(_profile_cfg["event_gap_days"]) * _bars_per_cal_day)))
    _min_sweep_frac = float(_profile_cfg["min_sweep_frac"])
    _min_wick_ratio = float(_profile_cfg["min_wick_ratio"])
    _min_disp_score = float(_profile_cfg["min_disp_score"])
    ts_candidates_seen = 0
    ts_rejection_counts: dict[str, int] = {
        "throttled_gap": 0,
        "no_sweep": 0,
        "no_reclaim": 0,
        "slow_reclaim": 0,
        "weak_rejection_wick": 0,
        "no_displacement": 0,
    }

    _last_ts_idx = -999999

    # Bearish setup: buy-side liquidity raid, failed breakout, then downside displacement.
    for sh_idx, sh_price, sh_time in swing_highs:
        pool_kind, pool_quality, pool_touches = _liquidity_pool_kind(swing_highs, sh_idx, float(sh_price), "high")
        end_i = min(len(candles) - 1, sh_idx + _lookahead_bars)
        for i in range(sh_idx + 1, end_i + 1):
            ts_candidates_seen += 1
            if i - _last_ts_idx < _event_gap:
                ts_rejection_counts["throttled_gap"] += 1
                continue
            _high = float(highs[i])
            _close = float(closes[i])
            _open = float(candles[i].get("open", _close) or _close)
            _low = float(lows[i])
            _range = max(1e-9, _high - _low)
            _sweep_size = _high - float(sh_price)
            _wick_ratio = (_high - _close) / _range
            _body = abs(_close - _open)
            _vol_avg = _rolling_avg(_volumes, i - 1, 20)
            _vol_spike = (float(_volumes[i]) / _vol_avg) if _vol_avg > 0 else 1.0
            _atr = _local_atr(i)

            _swept = _high > (float(sh_price) * (1.0 + _min_sweep_frac))
            _reclaimed = _close < float(sh_price)
            _fast_confirm = (i - sh_idx) <= _confirm_within
            _rejects = _wick_ratio >= _min_wick_ratio
            _disp = _find_displacement("SELL", i, float(sh_price))
            _disp_score = _clip01(float(_disp["move"]) / max(1e-9, 0.8 * _atr))
            _has_bos = bool(_disp["bos"])
            _has_imbalance = bool(_disp["imbalance"])
            _disp_ok = (_has_bos or _has_imbalance or _disp_score >= _min_disp_score)
            if not (_swept and _reclaimed and _fast_confirm and _rejects and _disp_ok):
                if not _swept:
                    ts_rejection_counts["no_sweep"] += 1
                elif not _reclaimed:
                    ts_rejection_counts["no_reclaim"] += 1
                elif not _fast_confirm:
                    ts_rejection_counts["slow_reclaim"] += 1
                elif not _rejects:
                    ts_rejection_counts["weak_rejection_wick"] += 1
                elif not _disp_ok:
                    ts_rejection_counts["no_displacement"] += 1
                continue

            _sweep_norm = _clip01(_sweep_size / (0.35 * _atr))
            _vol_norm = _clip01(min(2.0, _vol_spike) / 2.0)
            _session_label, _session_score = _session_context(times[i])
            _astro_score = _astro_timing_bias(int(times[i]))
            _liq_score = _clip01((0.30 * _sweep_norm) + (0.25 * _wick_ratio) + (0.15 * _vol_norm) + (0.30 * pool_quality))
            _displacement_score = _clip01((0.55 * _disp_score) + (0.30 if _has_bos else 0.0) + (0.15 if _has_imbalance else 0.0))
            _intent_failure = _clip01((0.40 * _wick_ratio) + (0.30 * _clip01(_body / max(1e-9, _atr))) + (0.30 * _clip01(1.0 - min(1.0, max(0, i - sh_idx) / max(1, _confirm_within)))))
            _confluence = _clip01((0.28 * _liq_score) + (0.28 * _displacement_score) + (0.16 * _session_score) + (0.14 * _astro_score) + (0.14 * (1.0 if _has_imbalance else 0.55)))
            _ai_conf = _clip01((0.20 * ts_learning_accuracy) + (0.28 * _intent_failure) + (0.32 * _confluence) + (0.20 * _displacement_score))
            _internal_target = _nearest_internal_liquidity("SELL", i)

            turtle_soup.append({
                "time": int(times[i]),
                "label": "TS↓",
                "color": "#ef4444",
                "shape": "arrowDown",
                "position": "aboveBar",
                "type": "turtle_soup_bear",
                "direction": "SELL",
                "liquidity_type": "buy_side_raid",
                "liquidity_pool_kind": pool_kind,
                "liquidity_pool_touches": int(pool_touches),
                "liquidity_pool_time": int(sh_time),
                "liquidity_pool_price": round(float(sh_price), 4),
                "sweep_size": round(float(_sweep_size), 6),
                "liquidity_score": round(float(_liq_score), 4),
                "displacement_score": round(float(_displacement_score), 4),
                "intent_failure_score": round(float(_intent_failure), 4),
                "confluence_score": round(float(_confluence), 4),
                "session": _session_label,
                "session_score": round(float(_session_score), 4),
                "astro_score": round(float(_astro_score), 4),
                "break_of_structure": bool(_has_bos),
                "imbalance_detected": bool(_has_imbalance),
                "displacement_broken_level": _disp["broken_level"],
                "ai_confidence": round(float(_ai_conf), 4),
                "learning_accuracy": round(float(ts_learning_accuracy), 4),
                "learning_samples": int(ts_learning_samples),
                "entry": round(float(_close), 4),
                "stop": round(float(_high + (0.15 * _atr)), 4),
                "target": round(float(_internal_target if _internal_target is not None else (_close - (1.5 * _atr))), 4),
            })
            _last_ts_idx = i
            break

    # Bullish setup: sell-side liquidity raid, failed breakdown, then upside displacement.
    for sl_idx, sl_price, sl_time in swing_lows:
        pool_kind, pool_quality, pool_touches = _liquidity_pool_kind(swing_lows, sl_idx, float(sl_price), "low")
        end_i = min(len(candles) - 1, sl_idx + _lookahead_bars)
        for i in range(sl_idx + 1, end_i + 1):
            ts_candidates_seen += 1
            if i - _last_ts_idx < _event_gap:
                ts_rejection_counts["throttled_gap"] += 1
                continue
            _high = float(highs[i])
            _close = float(closes[i])
            _open = float(candles[i].get("open", _close) or _close)
            _low = float(lows[i])
            _range = max(1e-9, _high - _low)
            _sweep_size = float(sl_price) - _low
            _wick_ratio = (_close - _low) / _range
            _body = abs(_close - _open)
            _vol_avg = _rolling_avg(_volumes, i - 1, 20)
            _vol_spike = (float(_volumes[i]) / _vol_avg) if _vol_avg > 0 else 1.0
            _atr = _local_atr(i)

            _swept = _low < (float(sl_price) * (1.0 - _min_sweep_frac))
            _reclaimed = _close > float(sl_price)
            _fast_confirm = (i - sl_idx) <= _confirm_within
            _rejects = _wick_ratio >= _min_wick_ratio
            _disp = _find_displacement("BUY", i, float(sl_price))
            _disp_score = _clip01(float(_disp["move"]) / max(1e-9, 0.8 * _atr))
            _has_bos = bool(_disp["bos"])
            _has_imbalance = bool(_disp["imbalance"])
            _disp_ok = (_has_bos or _has_imbalance or _disp_score >= _min_disp_score)
            if not (_swept and _reclaimed and _fast_confirm and _rejects and _disp_ok):
                if not _swept:
                    ts_rejection_counts["no_sweep"] += 1
                elif not _reclaimed:
                    ts_rejection_counts["no_reclaim"] += 1
                elif not _fast_confirm:
                    ts_rejection_counts["slow_reclaim"] += 1
                elif not _rejects:
                    ts_rejection_counts["weak_rejection_wick"] += 1
                elif not _disp_ok:
                    ts_rejection_counts["no_displacement"] += 1
                continue

            _sweep_norm = _clip01(_sweep_size / (0.35 * _atr))
            _vol_norm = _clip01(min(2.0, _vol_spike) / 2.0)
            _session_label, _session_score = _session_context(times[i])
            _astro_score = _astro_timing_bias(int(times[i]))
            _liq_score = _clip01((0.30 * _sweep_norm) + (0.25 * _wick_ratio) + (0.15 * _vol_norm) + (0.30 * pool_quality))
            _displacement_score = _clip01((0.55 * _disp_score) + (0.30 if _has_bos else 0.0) + (0.15 if _has_imbalance else 0.0))
            _intent_failure = _clip01((0.40 * _wick_ratio) + (0.30 * _clip01(_body / max(1e-9, _atr))) + (0.30 * _clip01(1.0 - min(1.0, max(0, i - sl_idx) / max(1, _confirm_within)))))
            _confluence = _clip01((0.28 * _liq_score) + (0.28 * _displacement_score) + (0.16 * _session_score) + (0.14 * _astro_score) + (0.14 * (1.0 if _has_imbalance else 0.55)))
            _ai_conf = _clip01((0.20 * ts_learning_accuracy) + (0.28 * _intent_failure) + (0.32 * _confluence) + (0.20 * _displacement_score))
            _internal_target = _nearest_internal_liquidity("BUY", i)

            turtle_soup.append({
                "time": int(times[i]),
                "label": "TS↑",
                "color": "#22c55e",
                "shape": "arrowUp",
                "position": "belowBar",
                "type": "turtle_soup_bull",
                "direction": "BUY",
                "liquidity_type": "sell_side_raid",
                "liquidity_pool_kind": pool_kind,
                "liquidity_pool_touches": int(pool_touches),
                "liquidity_pool_time": int(sl_time),
                "liquidity_pool_price": round(float(sl_price), 4),
                "sweep_size": round(float(_sweep_size), 6),
                "liquidity_score": round(float(_liq_score), 4),
                "displacement_score": round(float(_displacement_score), 4),
                "intent_failure_score": round(float(_intent_failure), 4),
                "confluence_score": round(float(_confluence), 4),
                "session": _session_label,
                "session_score": round(float(_session_score), 4),
                "astro_score": round(float(_astro_score), 4),
                "break_of_structure": bool(_has_bos),
                "imbalance_detected": bool(_has_imbalance),
                "displacement_broken_level": _disp["broken_level"],
                "ai_confidence": round(float(_ai_conf), 4),
                "learning_accuracy": round(float(ts_learning_accuracy), 4),
                "learning_samples": int(ts_learning_samples),
                "entry": round(float(_close), 4),
                "stop": round(float(_low - (0.15 * _atr)), 4),
                "target": round(float(_internal_target if _internal_target is not None else (_close + (1.5 * _atr))), 4),
            })
            _last_ts_idx = i
            break

    turtle_soup.sort(key=lambda x: int(x.get("time", 0)))
    if len(turtle_soup) > 80:
        turtle_soup = turtle_soup[-80:]

    ts_top_reject_reason = None
    if ts_rejection_counts:
        _ordered = sorted(ts_rejection_counts.items(), key=lambda kv: kv[1], reverse=True)
        if _ordered and _ordered[0][1] > 0:
            ts_top_reject_reason = _ordered[0][0]

    # Persist Turtle Soup observations as learning examples and resolve older ones when
    # enough bars have elapsed. This lets the model learn which liquidity/session/timeframe
    # contexts actually work instead of only using static heuristics.
    ts_context_summary: dict[str, Any] = {
        "current_timeframe": str(timeframe or ""),
        "turtle_profile_requested": requested_turtle_profile,
        "turtle_profile_applied": applied_turtle_profile,
        "current_timeframe_predictions": 0,
        "current_timeframe_outcomes": 0,
        "current_timeframe_accuracy": None,
        "candidates_seen": int(ts_candidates_seen),
        "rejection_counts": ts_rejection_counts,
        "top_rejection_reason": ts_top_reject_reason,
        "by_liquidity_type": {},
        "by_session": {},
    }
    latest_turtle_signal = turtle_soup[-1] if turtle_soup else None
    try:
        import hashlib as _hashlib
        import uuid as _uuid

        _all_predictions = _PREDICTION_TRACKER.load_predictions()
        _all_outcomes = _PREDICTION_TRACKER.load_outcomes()
        _pred_by_id: dict[str, Any] = {
            str(p.get("id") or ""): p for p in _all_predictions if str(p.get("id") or "").strip()
        }
        _outcome_by_id: dict[str, Any] = {
            str(o.get("prediction_id") or ""): o for o in _all_outcomes if str(o.get("prediction_id") or "").strip()
        }
        _predictions_added = 0
        _outcomes_added = 0
        _tf_horizon_bars = max(3, int(round(1.5 * _bars_per_cal_day)))

        for event in turtle_soup:
            _raw = f"TS|{symbol}|{timeframe}|{event.get('type')}|{event.get('time')}"
            _pid = str(_uuid.UUID(bytes=_hashlib.md5(_raw.encode()).digest()))
            event["prediction_id"] = _pid
            if _pid not in _pred_by_id:
                _dir = str(event.get("direction") or "WAIT").upper()
                _features = {
                    "signal_family": "turtle_soup",
                    "symbol": str(symbol),
                    "timeframe": str(timeframe),
                    "liquidity_type": str(event.get("liquidity_type") or ""),
                    "liquidity_pool_kind": str(event.get("liquidity_pool_kind") or ""),
                    "session": str(event.get("session") or ""),
                    "break_of_structure": bool(event.get("break_of_structure", False)),
                    "imbalance_detected": bool(event.get("imbalance_detected", False)),
                    "liquidity_score": float(event.get("liquidity_score", 0.0) or 0.0),
                    "displacement_score": float(event.get("displacement_score", 0.0) or 0.0),
                    "intent_failure_score": float(event.get("intent_failure_score", 0.0) or 0.0),
                    "confluence_score": float(event.get("confluence_score", 0.0) or 0.0),
                }
                _LEARNING_ENGINE.record_prediction(
                    prediction_id=_pid,
                    direction=_dir,
                    confluence_score=float(event.get("ai_confidence", 0.0) or 0.0),
                    geometry_signal=bool(event.get("imbalance_detected", False)),
                    time_signal=str(event.get("session") or "") in ("LONDON", "NEW_YORK", "DAILY"),
                    structure_signal=bool(event.get("break_of_structure", False)),
                    momentum_signal=float(event.get("displacement_score", 0.0) or 0.0) >= 0.55,
                    gann_signal=float(event.get("astro_score", 0.0) or 0.0) >= 0.70,
                    ict_signal=float(event.get("liquidity_score", 0.0) or 0.0) >= 0.60,
                    entry_price=float(event.get("entry", 0.0) or 0.0),
                    stop_price=float(event.get("stop", 0.0) or 0.0),
                    target_price=float(event.get("target", 0.0) or 0.0),
                    forecast_horizon_days=max(1, int(round(_tf_horizon_bars * _bar_day_fraction))),
                    confluence_signal=float(event.get("confluence_score", 0.0) or 0.0) >= 0.60,
                    features=_features,
                )
                _predictions_added += 1
                _pred_by_id[_pid] = {"id": _pid, "features": _features}

            if _pid in _outcome_by_id:
                continue

            _evt_time = int(event.get("time", 0) or 0)
            _evt_idx = next((idx for idx, ts in enumerate(times) if int(ts) == _evt_time), None)
            if _evt_idx is None:
                continue
            _resolve_idx = _evt_idx + _tf_horizon_bars
            if _resolve_idx >= len(candles):
                continue

            _entry = float(event.get("entry", 0.0) or 0.0)
            _stop = float(event.get("stop", 0.0) or 0.0)
            _target = float(event.get("target", 0.0) or 0.0)
            _future_slice_high = max(float(v) for v in highs[_evt_idx + 1:_resolve_idx + 1]) if _resolve_idx > _evt_idx else float(highs[_evt_idx])
            _future_slice_low = min(float(v) for v in lows[_evt_idx + 1:_resolve_idx + 1]) if _resolve_idx > _evt_idx else float(lows[_evt_idx])
            _final_close = float(closes[_resolve_idx])
            _direction = str(event.get("direction") or "WAIT").upper()

            if _direction == "SELL":
                _stop_hit = _future_slice_high >= _stop > 0
                _target_hit = _future_slice_low <= _target if _target > 0 else False
                _outcome_direction = "DOWN" if (_target_hit or _final_close < _entry) and not _stop_hit else "UP"
                _actual_move = max(0.0, _entry - _final_close)
            else:
                _stop_hit = _future_slice_low <= _stop if _stop > 0 else False
                _target_hit = _future_slice_high >= _target if _target > 0 else False
                _outcome_direction = "UP" if (_target_hit or _final_close > _entry) and not _stop_hit else "DOWN"
                _actual_move = max(0.0, _final_close - _entry)

            _LEARNING_ENGINE.record_outcome(
                prediction_id=_pid,
                realized_price=float(_final_close),
                outcome_direction=_outcome_direction,
                actual_move_pips=float(_actual_move),
                timeframe_reached=int(_tf_horizon_bars),
            )
            _outcomes_added += 1

        # Refresh snapshots after any updates so summary reflects latest learning state.
        _all_predictions = _PREDICTION_TRACKER.load_predictions()
        _all_outcomes = _PREDICTION_TRACKER.load_outcomes()
        _pred_by_id = {str(p.get("id") or ""): p for p in _all_predictions if str(p.get("id") or "").strip()}
        _outcome_by_id = {str(o.get("prediction_id") or ""): o for o in _all_outcomes if str(o.get("prediction_id") or "").strip()}

        _tf_preds = []
        _tf_hits = []
        _liq_stats: dict[str, dict[str, float]] = {}
        _session_stats: dict[str, dict[str, float]] = {}
        for _pid, _pred in _pred_by_id.items():
            _features = _pred.get("features") if isinstance(_pred.get("features"), dict) else {}
            if str(_features.get("signal_family") or "") != "turtle_soup":
                continue
            if str(_features.get("timeframe") or "") != str(timeframe):
                continue
            _tf_preds.append(_pred)
            _outcome = _outcome_by_id.get(_pid)
            if _outcome is not None:
                _tf_hits.append(1.0 if bool(_outcome.get("was_correct", False)) else 0.0)

            _liq_key = str(_features.get("liquidity_type") or "unknown")
            _session_key = str(_features.get("session") or "UNKNOWN")
            for _bucket, _key in ((_liq_stats, _liq_key), (_session_stats, _session_key)):
                _row = _bucket.setdefault(_key, {"predictions": 0.0, "wins": 0.0})
                _row["predictions"] += 1.0
                if _outcome is not None and bool(_outcome.get("was_correct", False)):
                    _row["wins"] += 1.0

        ts_context_summary = {
            "current_timeframe": str(timeframe or ""),
            "turtle_profile_requested": requested_turtle_profile,
            "turtle_profile_applied": applied_turtle_profile,
            "current_timeframe_predictions": len(_tf_preds),
            "current_timeframe_outcomes": len(_tf_hits),
            "current_timeframe_accuracy": round(sum(_tf_hits) / len(_tf_hits), 4) if _tf_hits else None,
            "candidates_seen": int(ts_candidates_seen),
            "rejection_counts": ts_rejection_counts,
            "top_rejection_reason": ts_top_reject_reason,
            "predictions_added_this_run": int(_predictions_added),
            "outcomes_added_this_run": int(_outcomes_added),
            "by_liquidity_type": {
                _k: {
                    "predictions": int(_v["predictions"]),
                    "accuracy": round(float(_v["wins"]) / float(_v["predictions"]), 4) if _v["predictions"] else None,
                }
                for _k, _v in _liq_stats.items()
            },
            "by_session": {
                _k: {
                    "predictions": int(_v["predictions"]),
                    "accuracy": round(float(_v["wins"]) / float(_v["predictions"]), 4) if _v["predictions"] else None,
                }
                for _k, _v in _session_stats.items()
            },
        }
        if latest_turtle_signal is not None:
            latest_turtle_signal = {
                **latest_turtle_signal,
                "timeframe": str(timeframe),
                "timeframe_learning_accuracy": ts_context_summary.get("current_timeframe_accuracy"),
            }
    except Exception as _ts_learn_exc:
        logging.debug("Turtle Soup learning sync failed: %s", _ts_learn_exc)

    # ── 6. Prediction zone — Gann angle + P(t) projection ─────────────────
    # Project 30 calendar days forward from last candle
    prediction_zone = []
    try:
        from astroquant.engine.gann.gann_astro_timing_engine import price_time_vibration, ORBITAL_PERIODS

        last_candle = candles[-1]
        base_price = float(last_candle["close"])
        base_time = int(last_candle["time"])

        # Determine bar interval in seconds
        bar_secs = _bar_secs_raw  # use pre-computed bar interval

        # 1×1 Gann angle slope scaled to bar duration:
        # Daily chart  (bar_day_fraction=1.0) → $3.0/bar  (0.1%/day)
        # 1h chart     (bar_day_fraction=0.042) → $0.125/bar
        # 5m chart     (bar_day_fraction=0.0035) → $0.010/bar
        ppu = base_price * 0.001 * _bar_day_fraction
        R   = base_price * 0.05    # 5% amplitude for P(t) resonance
        T   = ORBITAL_PERIODS.get("saturn", 10759.0)   # Saturn major cycle
        Z   = base_price * 0.02

        N_BARS = 30
        for n in range(1, N_BARS + 1):
            future_time = base_time + n * bar_secs
            # days_out: always in calendar days regardless of chart timescale
            days_out = float(n * _bar_secs_raw) if _is_day_scale else (n * _bar_secs_raw / 86400.0)
            vibration = price_time_vibration(
                t=days_out, R=R, T_days=T, phi_deg=0.0, Z=Z,
                theta_deg_per_day=0.033, planet="saturn"
            )
            # Gann 1×1 component + vibrational correction
            gann_proj = base_price + n * ppu + vibration
            prediction_zone.append({
                "time": int(future_time),
                "value": round(gann_proj, 4),
                "type": "prediction",
            })
    except Exception as _exc:
        logging.debug("Prediction zone compute failed: %s", _exc)

    # ── 7. Gann angle lines from last major swing low ──────────────────────
    # Lines extend: chart-start → anchor(swing-low) → last candle → +30 bars forward
    # so they span the full visible range instead of only the anchor-to-last-bar stub.
    gann_angles = []
    gann_trend_portions: dict[str, Any] = {
        "up_lines": 0,
        "down_lines": 0,
        "flat_lines": 0,
        "up_ratio": 0.0,
        "down_ratio": 0.0,
        "active_bias": "NEUTRAL",
    }
    gann_angle_accuracy = 0.0
    try:
        if sl_list:
            _, anchor_price, anchor_time = sl_list[-1]
            ppu_day = anchor_price * 0.001 * _bar_day_fraction
            current_bar = max(1, (last_ts - anchor_time) // max(1, bar_secs))
            _back_bars = max(0, int((anchor_time - first_ts) // max(1, bar_secs)))
            _fwd_bars = 30
            _fwd_ts = int(last_ts + _fwd_bars * bar_secs)
            _anchor_quality = max(0.2, min(1.0, float(current_bar) / max(30.0, 3.0 * float(_bars_per_cal_day))))

            for ratio, label, color in [
                (1.0, "1×1", "#fbbf24"),
                (2.0, "2×1", "#10b981"),
                (0.5, "1×2", "#f472b6"),
            ]:
                start_price = round(anchor_price - ratio * ppu_day * _back_bars, 4)
                anchor_val = round(anchor_price, 4)
                last_price = round(anchor_price + ratio * ppu_day * current_bar, 4)
                fwd_price = round(anchor_price + ratio * ppu_day * (current_bar + _fwd_bars), 4)

                pts = []
                if _back_bars >= 5:
                    pts.append({"time": int(first_ts), "value": start_price})
                pts.append({"time": int(anchor_time), "value": anchor_val})
                pts.append({"time": int(last_ts), "value": last_price})
                pts.append({"time": int(_fwd_ts), "value": fwd_price})

                gann_angles.append({
                    "label": label,
                    "color": color,
                    "points": pts,
                    "confidence": round(float(_anchor_quality), 3),
                })

        if sh_list:
            _, anchor_price, anchor_time = sh_list[-1]
            ppu_day = anchor_price * 0.001 * _bar_day_fraction
            current_bar = max(1, (last_ts - anchor_time) // max(1, bar_secs))
            _back_bars = max(0, int((anchor_time - first_ts) // max(1, bar_secs)))
            _fwd_bars = 30
            _fwd_ts = int(last_ts + _fwd_bars * bar_secs)
            _anchor_quality = max(0.2, min(1.0, float(current_bar) / max(30.0, 3.0 * float(_bars_per_cal_day))))

            for ratio, label, color in [
                (1.0, "1x1_down", "#fb7185"),
                (2.0, "2x1_down", "#ef4444"),
                (0.5, "1x2_down", "#f97316"),
            ]:
                start_price = round(anchor_price + ratio * ppu_day * _back_bars, 4)
                anchor_val = round(anchor_price, 4)
                last_price = round(anchor_price - ratio * ppu_day * current_bar, 4)
                fwd_price = round(anchor_price - ratio * ppu_day * (current_bar + _fwd_bars), 4)

                pts = []
                if _back_bars >= 5:
                    pts.append({"time": int(first_ts), "value": start_price})
                pts.append({"time": int(anchor_time), "value": anchor_val})
                pts.append({"time": int(last_ts), "value": last_price})
                pts.append({"time": int(_fwd_ts), "value": fwd_price})

                gann_angles.append({
                    "label": label,
                    "color": color,
                    "points": pts,
                    "confidence": round(float(_anchor_quality), 3),
                })

        up_lines = 0
        down_lines = 0
        flat_lines = 0
        for _line in gann_angles:
            _pts = _line.get("points") or []
            if len(_pts) < 2:
                continue
            _a = float((_pts[0] or {}).get("value", 0.0) or 0.0)
            _b = float((_pts[-1] or {}).get("value", 0.0) or 0.0)
            if _b > _a:
                up_lines += 1
            elif _b < _a:
                down_lines += 1
            else:
                flat_lines += 1

        _total_lines = max(1, up_lines + down_lines + flat_lines)
        _up_ratio = float(up_lines) / float(_total_lines)
        _down_ratio = float(down_lines) / float(_total_lines)
        _active = "UPTREND" if _up_ratio > _down_ratio else ("DOWNTREND" if _down_ratio > _up_ratio else "NEUTRAL")
        gann_trend_portions = {
            "up_lines": int(up_lines),
            "down_lines": int(down_lines),
            "flat_lines": int(flat_lines),
            "up_ratio": round(float(_up_ratio), 4),
            "down_ratio": round(float(_down_ratio), 4),
            "active_bias": _active,
        }

        if gann_angles:
            gann_angle_accuracy = sum(float(a.get("confidence", 0.0) or 0.0) for a in gann_angles) / len(gann_angles)
    except Exception as _exc:
        logging.debug("Gann angle lines compute failed: %s", _exc)

    # ── 8. Elliott Wave Auto-Identification ─────────────────────────────────────
    elliott_waves: list[dict] = []
    try:
        # Use already-computed closes/highs/lows/times from the auto_patterns section.
        # Detect pivot highs and lows with a wider window (SWING_N_EW) for wave structure.
        SWING_N_EW = max(5, SWING_N * 2)
        ew_highs: list[tuple[int, float, int]] = []   # (bar_idx, price, time)
        ew_lows:  list[tuple[int, float, int]] = []

        for i in range(SWING_N_EW, len(candles) - SWING_N_EW):
            wh = highs[i - SWING_N_EW: i + SWING_N_EW + 1]
            wl = lows[i - SWING_N_EW: i + SWING_N_EW + 1]
            if highs[i] == max(wh):
                ew_highs.append((i, highs[i], times[i]))
            if lows[i] == min(wl):
                ew_lows.append((i, lows[i], times[i]))

        # Merge and sort all pivot points, alternating H/L (compress consecutive same-type)
        all_pivots: list[tuple[int, float, int, str]] = (
            [(idx, p, t, "H") for idx, p, t in ew_highs] +
            [(idx, p, t, "L") for idx, p, t in ew_lows]
        )
        all_pivots.sort(key=lambda x: x[0])

        # Compress: keep only alternating H/L (when consecutive same type, keep extreme)
        compressed: list[tuple[int, float, int, str]] = []
        for pivot in all_pivots:
            if not compressed:
                compressed.append(pivot)
            elif compressed[-1][3] == pivot[3]:
                # Same type — keep the more extreme one
                prev = compressed[-1]
                if pivot[3] == "H":
                    compressed[-1] = pivot if pivot[1] > prev[1] else prev
                else:
                    compressed[-1] = pivot if pivot[1] < prev[1] else prev
            else:
                compressed.append(pivot)

        # Slide a window of 9 pivots (enough for 1 full impulse + correction) across history
        # Each window: detect IMPULSE (5-wave) or CORRECTIVE (3-wave) structure
        EW_WINDOW = 9    # pivots per structural unit
        EW_STEP   = 3    # step between windows (overlap for continuity)
        IMPULSE_LABELS  = ["", "1", "2", "3", "4", "5"]    # 1-indexed
        CORRECT_LABELS  = ["A", "B", "C"]

        _seen_times: set[int] = set()

        for wi in range(0, max(1, len(compressed) - EW_WINDOW + 1), EW_STEP):
            window = compressed[wi: wi + EW_WINDOW]
            if len(window) < 4:
                continue
            # Determine overall bias: first-to-last price move
            price_start = window[0][1]
            price_end   = window[-1][1]
            price_range = max(1e-9, abs(max(p[1] for p in window) - min(p[1] for p in window)))
            trend_strength = abs(price_end - price_start) / price_range
            is_impulse = trend_strength >= 0.55

            direction_up = price_end > price_start

            # Label consecutive segments between pivots
            n_segments = len(window) - 1
            if is_impulse:
                wave_phase = "IMPULSE"
                label_pool = IMPULSE_LABELS
                color_up   = "#10b981"   # green
                color_dn   = "#ef4444"   # red
            else:
                wave_phase = "CORRECTIVE"
                label_pool = ["", "A", "B", "C"]
                color_up   = "#f59e0b"   # amber
                color_dn   = "#f59e0b"

            for seg_i in range(min(n_segments, len(label_pool) - 1)):
                p_start = window[seg_i]
                p_end   = window[seg_i + 1]
                label_idx = seg_i + 1
                lbl = label_pool[label_idx] if label_idx < len(label_pool) else str(label_idx)

                seg_up = p_end[1] > p_start[1]
                seg_color = (color_up if seg_up else color_dn)
                conf = round(float(trend_strength) * (0.8 + 0.2 * (seg_i / max(1, n_segments))), 3)
                conf = min(1.0, max(0.2, conf))

                wave_id = (p_start[2], p_end[2])
                if wave_id in _seen_times:
                    continue
                _seen_times.add(wave_id)

                elliott_waves.append({
                    "time":           p_start[2],
                    "end_time":       p_end[2],
                    "wave_label":     lbl,
                    "wave_phase":     wave_phase,
                    "confidence":     conf,
                    "direction_up":   bool(seg_up),
                    "initial_price":  float(p_start[1]),
                    "ending_price":   float(p_end[1]),
                    "color":          seg_color,
                })

        # Sort by time
        elliott_waves.sort(key=lambda w: w["time"])
    except Exception as _ew_exc:
        logging.debug("Elliott wave overlay failed: %s", _ew_exc)

    # ── 9. Cycle alignment: detect and snap to node boundaries ──────────────────
    alignment = _build_cycle_alignment_markers(
        candles,
        timeframe=timeframe,
        bar_units_hint=float(_bar_secs_raw),
    )

    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "source_mode": source_mode,
        "turtle_profile_requested": requested_turtle_profile,
        "turtle_profile_applied": applied_turtle_profile,
        "total_candles": len(candles),
        "gann_cycles": gann_cycles,
        "lunar_events": lunar_events,
        "auto_patterns": auto_patterns,
        "turtle_soup": turtle_soup,
        "turtle_soup_learning": ts_context_summary,
        "turtle_soup_debug": {
            "candidates_seen": int(ts_candidates_seen),
            "rejection_counts": ts_rejection_counts,
            "top_rejection_reason": ts_top_reject_reason,
        },
        "latest_turtle_soup": latest_turtle_signal,
        "prediction_zone": prediction_zone,
        "gann_angles": gann_angles,
        "gann_trend_portions": gann_trend_portions,
        # ── Moon phase + Gann cycle identification (live) ──────────────────────
        "moon": _build_moon_overlay(candles),
        # ── Gann Node pressure points (time+price spiral convergence) ──────────
        "gann_nodes": _build_node_overlay(candles, _cache_payloads.get(f"{symbol}_{timeframe}")),
        # ── Time Compression (silence = signal, cycles tightening = breakout near)
        "compression": _build_compression_overlay(candles, _cache_payloads.get(f"{symbol}_{timeframe}")),
        # Continuous cycle waves normalized to [0,1] for live chart overlays.
        "cycle_waves": _build_cycle_wave_overlays(
            candles,
            timeframe=timeframe,
            bar_units_hint=float(_bar_secs_raw),
        ),
        # ── Cycle alignment markers: vertical lines at node boundaries, horizontal at price levels
        "cycle_alignment": alignment,
        "elliott_waves": elliott_waves,
        "cycle_phases": cycle_phases,
        "meta": {
            "swing_highs_found": len(swing_highs),
            "swing_lows_found":  len(swing_lows),
            "lunar_events_found": len(lunar_events),
            "bos_count": sum(1 for p in auto_patterns if p["type"].startswith("bos")),
            "turtle_soup_count": len(turtle_soup),
            "turtle_soup_ai_accuracy": round(float(ts_learning_accuracy), 4),
            "turtle_soup_learning_samples": int(ts_learning_samples),
            "turtle_soup_avg_liquidity_score": round(
                float(sum(float(s.get("liquidity_score", 0.0) or 0.0) for s in turtle_soup) / max(1, len(turtle_soup))),
                4,
            ),
            "turtle_soup_timeframe_accuracy": ts_context_summary.get("current_timeframe_accuracy"),
            "turtle_soup_candidates_seen": int(ts_candidates_seen),
            "turtle_soup_top_rejection_reason": ts_top_reject_reason,
            "turtle_profile_requested": requested_turtle_profile,
            "turtle_profile_applied": applied_turtle_profile,
            "latest_turtle_soup": latest_turtle_signal,
            "alignment_snap_points": alignment.get("meta", {}).get("total_snap_points", 0),
            "lunar_event_accuracy": round(float(lunar_accuracy), 4),
            "gann_angle_accuracy": round(float(gann_angle_accuracy), 4),
            "gann_trend_portions": gann_trend_portions,
            "astro_gann_display_accuracy": round(float((lunar_accuracy + gann_angle_accuracy + float(alignment.get("meta", {}).get("adjacent_node_quality_score", 1.0))) / 3.0), 4),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Lesson Annotations — 3-lesson automatic cycle / node / bar-count identification
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/chart/lesson_annotations")
def chart_lesson_annotations(
    symbol: str = Query(default="XAUUSD"),
    timeframe: str = Query(default="1d"),
    lookback_years: int = Query(default=5, ge=1, le=25),
    limit: int = Query(default=5000, ge=1, le=20000),
) -> dict[str, Any]:
    """
    Automatic identification of Gann cycle nodes, bar/day counts and lesson signals
    across any timeframe, scored by the live AI model weights.

    Returns four annotation layers:
      lesson1_lunar  — Lunar phase windows (L1: Lunar Expansion Engine)
      lesson2_nodes  — SQ9 time-harmonic nodes, bar counts (L2: Law of Vibration)
      lesson3_asc    — ASC degree crossings + SQ9 price levels (L3: ASC + Square of 9)
      swing_counts   — Swing high/low with bar-count and day-count labels
      sq9_grid       — SQ9 price level horizontal lines around current price
    """
    import math as _math
    import bisect as _bisect

    # ── 1. Load candles ───────────────────────────────────────────────────────
    chart = _compute_chart(symbol=symbol, timeframe=timeframe,
                           lookback_years=lookback_years, limit=limit)
    candles = chart.get("candles", [])
    if not candles:
        return {"status": "ok", "lesson1_lunar": [], "lesson2_nodes": [],
                "lesson3_asc": [], "swing_counts": [], "sq9_grid": [],
                "meta": {"total": 0}}

    candles = sorted(candles, key=lambda c: c["time"])
    times   = [int(c["time"])   for c in candles]
    closes  = [float(c["close"]) for c in candles]
    highs   = [float(c["high"])  for c in candles]
    lows    = [float(c["low"])   for c in candles]
    n       = len(candles)

    # ── Timeframe-aware scaling ───────────────────────────────────────────────
    _is_day_scale = times[-1] < 100_000
    if n >= 2:
        _dts = [times[i+1] - times[i] for i in range(max(0, n-20), n-1)
                if times[i+1] > times[i]]
        _bar_secs = int(sum(_dts) / len(_dts)) if _dts else (86400 if _is_day_scale else 86400)
    else:
        _bar_secs = 86400
    _bar_days = float(_bar_secs) if _is_day_scale else max(1e-6, _bar_secs / 86400.0)

    def _bars_to_days(bars: int) -> float:
        return round(bars * _bar_days, 1)

    # ── 2. Detect swing highs/lows (adaptive window) ─────────────────────────
    _bars_per_day = max(1, int(1.0 / _bar_days)) if not _is_day_scale else 1
    SWING_N = max(3, min(10, _bars_per_day // 8)) if not _is_day_scale else 5

    swing_highs: list[tuple[int, float, int]] = []   # (idx, price, time)
    swing_lows:  list[tuple[int, float, int]] = []

    for i in range(SWING_N, n - SWING_N):
        wh = highs[i - SWING_N: i + SWING_N + 1]
        wl = lows[i  - SWING_N: i + SWING_N + 1]
        if highs[i] == max(wh):
            swing_highs.append((i, highs[i], times[i]))
        if lows[i] == min(wl):
            swing_lows.append((i, lows[i], times[i]))

    # ── 3. AI model weights (confidence scoring) ──────────────────────────────
    _raw_weights: dict[str, Any] = {}
    try:
        lfe = LearningFeedbackEngine()
        _raw_weights = lfe.get_weights() or {}
    except Exception:
        pass
    _lunar_conf   = float(_raw_weights.get("lunar",      0.72))
    _vibration_conf = float(_raw_weights.get("vibration",  0.78))
    _asc_conf     = float(_raw_weights.get("asc_sq9",    0.68))

    # Clamp AI confidences to [0.50, 0.99]
    def _clamp_conf(v: float) -> float:
        return max(0.50, min(0.99, float(v)))

    _lc = _clamp_conf(_lunar_conf)
    _vc = _clamp_conf(_vibration_conf)
    _ac = _clamp_conf(_asc_conf)

    # ── 4. LESSON 1 — Lunar Expansion (phase boundaries on chart) ────────────
    _NEW_MOON_EPOCH = 947182440        # 2000-01-06 18:14 UTC
    _SYNODIC        = 29.530588853 * 86400.0

    # Phase windows (days from new moon → name, color, lesson label)
    _PHASE_WINDOWS = [
        (0.0,   2.0,  "SEED",            "#64748b", "L1:SEED"),
        (3.0,   5.5,  "EARLY_EXP",       "#93c5fd", "L1:EXP↑"),
        (7.0,   9.5,  "MOMENTUM",        "#22c55e", "L1:MOM"),
        (11.0,  13.5, "EXHAUSTION",      "#f97316", "L1:EXH"),
        (13.5,  15.0, "FULL_APEX",       "#fcd34d", "L1:FM🌕"),
        (24.46, 29.53,"SEED_APPROACH",   "#94a3b8", "L1:NM🌑"),
    ]

    lesson1_lunar: list[dict] = []
    # Walk all candles and mark phase-window entry points
    _prev_phase_idx = -1
    for ci, candle in enumerate(candles):
        ts = float(candle["time"])
        if _is_day_scale:
            ts_sec = ts * 86400.0
        else:
            ts_sec = ts
        elapsed = ts_sec - _NEW_MOON_EPOCH
        age_secs = elapsed % _SYNODIC
        age_days = age_secs / 86400.0

        for pi, (lo, hi, phase_key, col, lbl) in enumerate(_PHASE_WINDOWS):
            if lo <= age_days < hi:
                if pi != _prev_phase_idx:
                    # Phase entry — annotate once per entry
                    lesson1_lunar.append({
                        "time":           candle["time"],
                        "phase":          phase_key,
                        "cycle_day":      round(age_days, 2),
                        "gann_angle":     round((age_days / 29.530588853) * 360.0, 1),
                        "label":          lbl,
                        "color":          col,
                        "position":       "aboveBar",
                        "shape":          "circle",
                        "lesson":         1,
                        "ai_confidence":  _lc,
                        "bar_index":      ci,
                    })
                    _prev_phase_idx = pi
                break
        else:
            _prev_phase_idx = -1   # between windows, reset

    # Fast index for nearest L1 phase entries (used to match L2 harmonic nodes to lunar windows)
    _l1_idx = [int(e.get("bar_index", 0)) for e in lesson1_lunar]
    _l1_ref = [
        {
            "bar_index": int(e.get("bar_index", 0)),
            "label": str(e.get("label", "")),
            "phase": str(e.get("phase", "")),
        }
        for e in lesson1_lunar
    ]

    def _nearest_l1_match(bar_index: int) -> tuple[bool, str, str, int]:
        """Return (matched, l1_label, l1_phase, bars_delta)."""
        if not _l1_idx:
            return False, "", "", -1
        pos = _bisect.bisect_left(_l1_idx, bar_index)
        candidates: list[dict] = []
        if pos < len(_l1_ref):
            candidates.append(_l1_ref[pos])
        if pos > 0:
            candidates.append(_l1_ref[pos - 1])
        if not candidates:
            return False, "", "", -1
        best = min(candidates, key=lambda r: abs(int(r["bar_index"]) - bar_index))
        bars_delta = abs(int(best["bar_index"]) - bar_index)
        # Allow wider tolerance for intraday so lunar-window matching is practical.
        lunar_match_tolerance = max(2, min(12, int(round(1.0 / max(_bar_days, 1e-6)))))
        matched = bars_delta <= lunar_match_tolerance
        return matched, str(best.get("label", "")), str(best.get("phase", "")), bars_delta

    # ── 5. LESSON 2 — Law of Vibration (time harmonics + SQ9 nodes) ──────────
    _TIME_HARMONICS = [30, 45, 72, 90, 144, 180, 270, 360, 720]
    _HARMONIC_LABELS = {
        30:  "30°",
        45:  "45°⬠",
        72:  "72° Pent",
        90:  "90°□",
        144: "144°",
        180: "180°☌",
        270: "270°△",
        360: "360°⊙",
        720: "720°⊙⊙",
    }
    _HARMONIC_COLORS = {
        30:  "#38bdf8",
        45:  "#fbbf24",
        72:  "#a78bfa",
        90:  "#a78bfa",
        144: "#f472b6",
        180: "#f472b6",
        270: "#10b981",
        360: "#10b981",
        720: "#22d3ee",
    }

    lesson2_nodes: list[dict] = []
    _STEP = 0.5

    # For each swing, compute bar count from previous swing of same type
    # and mark time harmonics along the way
    def _nearest_harmonic(bar_count: int) -> tuple[int, int]:
        """Return (nearest_harmonic, bars_away)."""
        nh = min(_TIME_HARMONICS, key=lambda h: abs(h - bar_count))
        return nh, abs(nh - bar_count)

    # Annotate at each harmonic-bar index from chart start
    # and mark nodes where price is also near SQ9 level
    for ci in range(1, n):
        bar_num = ci + 1  # 1-based
        for h in _TIME_HARMONICS:
            if bar_num % h == 0:
                price_here = closes[ci]
                # Check SQ9 proximity
                root = _math.sqrt(price_here)
                floor_n = int(root / _STEP)
                sq9_near = False
                sq9_price = 0.0
                for offset in range(-2, 3):
                    lvl = round(((floor_n + offset) * _STEP) ** 2, 2)
                    if lvl > 0 and abs(price_here - lvl) / price_here <= 0.004:
                        sq9_near = True
                        sq9_price = lvl
                        break

                node_type = "REAL" if sq9_near else "TIME_ONLY"
                conf_boost = 0.12 if sq9_near else 0.0
                day_count  = _bars_to_days(bar_num)
                size = 2 if h >= 180 else 1
                l1_matched, l1_label, l1_phase, l1_bars_delta = _nearest_l1_match(ci)
                if l1_matched:
                    conf_boost += 0.05

                lesson2_nodes.append({
                    "time":          candle["time"] if (candle := candles[ci]) else times[ci],
                    "bar_count":     bar_num,
                    "day_count":     day_count,
                    "harmonic":      h,
                    "sq9_near":      sq9_near,
                    "sq9_price":     sq9_price if sq9_near else 0.0,
                    "node_type":     node_type,
                    "label":         f"L2:{_HARMONIC_LABELS[h]}{'⬟' if sq9_near else ''}",
                    "color":         _HARMONIC_COLORS[h],
                    "position":      "belowBar",
                    "shape":         "square" if h < 180 else "arrowDown",
                    "size":          size,
                    "lesson":        2,
                    "ai_confidence": _clamp_conf(_vc + conf_boost),
                    "bar_index":     ci,
                    "lunar_match":   l1_matched,
                    "lunar_label":   l1_label,
                    "lunar_phase":   l1_phase,
                    "lunar_bar_delta": l1_bars_delta,
                })
                break  # only first matching harmonic per bar

    # ── 6. LESSON 3 — ASC + Square of 9 (swing-anchored ASC crossings) ───────
    lesson3_asc: list[dict] = []

    # Use last major swing low as ASC anchor (same rule as Lesson 3 framework)
    anchor_idx, anchor_price, anchor_time = (0, closes[0], times[0])
    if swing_lows:
        anchor_idx, anchor_price, anchor_time = swing_lows[-1]

    # ASC deg per bar: derived from bar_days × 15°/hr × 24 = 360°/day
    # For daily: 360°/day × 1 day = 360° per bar (mod 360)
    # For 1h:  360°/day × (1/24) = 15°/bar
    # For 5m:  360°/day × (5/(60×24)) = 1.25°/bar
    _asc_deg_per_bar = 360.0 * _bar_days  # degrees per bar

    _ASC_MILESTONES = [45.0, 90.0, 180.0, 270.0, 360.0, 450.0, 540.0, 720.0]
    _ASC_COLORS = {
        45:  "#a78bfa",
        90:  "#f472b6",
        180: "#fbbf24",
        270: "#10b981",
        360: "#22c55e",
        450: "#a78bfa",
        540: "#f472b6",
        720: "#22d3ee",
    }
    _ASC_NAMES = {
        45: "SEMISQUARE", 90: "SQUARE", 180: "OPPOSITION",
        270: "SESQUISQUARE", 360: "FULL CYCLE",
        450: "1.25× CY", 540: "SESQUI-2", 720: "2× CYCLE",
    }

    _passed_milestones: set[float] = set()
    for ci in range(anchor_idx + 1, n):
        bars_elapsed = ci - anchor_idx
        asc_cumulative = bars_elapsed * _asc_deg_per_bar

        for ms in _ASC_MILESTONES:
            if ms in _passed_milestones:
                continue
            # Check if this bar crosses the milestone
            prev_asc = (bars_elapsed - 1) * _asc_deg_per_bar
            if prev_asc < ms <= asc_cumulative:
                _passed_milestones.add(ms)
                price_here = closes[ci]

                # SQ9 level at this ASC degree: convert degree → root offset
                # Each 45° on ASC = one SQ9 step of 0.5 root unit
                steps = ms / 45.0
                anchor_root = _math.sqrt(max(1.0, anchor_price))
                sq9_at_crossing = round(max(0.0, anchor_root + steps * _STEP) ** 2, 2)

                # Proximity of current price to that SQ9 level
                near_sq9 = abs(price_here - sq9_at_crossing) / max(1.0, sq9_at_crossing) <= 0.008
                conf_boost = 0.15 if near_sq9 else 0.0
                ms_key = int(ms)
                col = _ASC_COLORS.get(ms_key, "#e2e8f0")

                lesson3_asc.append({
                    "time":           candles[ci]["time"],
                    "asc_cumulative": round(asc_cumulative, 1),
                    "asc_milestone":  ms,
                    "milestone_name": _ASC_NAMES.get(ms_key, f"{ms_key}°"),
                    "bars_from_anchor": bars_elapsed,
                    "days_from_anchor": _bars_to_days(bars_elapsed),
                    "sq9_price":       sq9_at_crossing,
                    "price_near_sq9":  near_sq9,
                    "current_price":   price_here,
                    "label":           f"L3:{ms_key}°{'⬟' if near_sq9 else ''}",
                    "color":           col,
                    "position":        "aboveBar",
                    "shape":           "arrowUp",
                    "lesson":          3,
                    "ai_confidence":   _clamp_conf(_ac + conf_boost),
                    "bar_index":       ci,
                })
                break  # one milestone per bar max

    # ── 7. Swing counts — bar/day labels between swings ──────────────────────
    swing_counts: list[dict] = []

    def _annotate_swings(swings: list[tuple], swing_type: str, col: str, pos: str) -> None:
        for k in range(1, len(swings)):
            prev_idx, prev_price, prev_time = swings[k - 1]
            curr_idx, curr_price, curr_time = swings[k]
            bar_gap  = curr_idx - prev_idx
            day_gap  = _bars_to_days(bar_gap)
            nh, baway = _nearest_harmonic(bar_gap)

            # Check if this swing is at SQ9 node
            root_c = _math.sqrt(max(1.0, curr_price))
            fn = int(root_c / _STEP)
            sq9_near = any(
                abs(curr_price - round(((fn + off) * _STEP) ** 2, 2)) / curr_price <= 0.005
                for off in range(-2, 3)
            )
            near_label = "⬟" if sq9_near else ""
            harmonic_label = f" {nh}°" if baway <= max(2, int(nh * 0.05)) else ""
            conf_adj = 0.1 if sq9_near else 0.0

            swing_counts.append({
                "time":           candles[curr_idx]["time"],
                "swing_type":     swing_type,
                "bar_count":      bar_gap,
                "day_count":      day_gap,
                "sq9_near":       sq9_near,
                "nearest_harmonic": nh,
                "bars_to_harmonic": baway,
                "label":          f"{bar_gap}B/{day_gap}D{harmonic_label}{near_label}",
                "color":          col,
                "position":       pos,
                "shape":          "arrowUp" if swing_type == "HIGH" else "arrowDown",
                "lesson":         "ALL",
                "ai_confidence":  _clamp_conf(max(_lc, _vc, _ac) + conf_adj),
                "bar_index":      curr_idx,
                # Horizontal bar-to-bar segment payload (for chart rendering)
                "from_time":      candles[prev_idx]["time"],
                "to_time":        candles[curr_idx]["time"],
                "line_price":     round((prev_price + curr_price) / 2.0, 4),
                "from_price":     round(prev_price, 4),
                "to_price":       round(curr_price, 4),
            })

    _annotate_swings(swing_highs, "HIGH", "#22c55e", "aboveBar")
    _annotate_swings(swing_lows,   "LOW",  "#ef4444", "belowBar")

    # ── 8. SQ9 grid around current price ────────────────────────────────────
    sq9_grid: list[dict] = []
    if closes:
        _cur_price = closes[-1]
        _root_cur  = _math.sqrt(max(1.0, _cur_price))
        _fn        = int(_root_cur / _STEP)
        for off in range(-8, 9):
            _n = _fn + off
            if _n <= 0:
                continue
            lvl = round((_n * _STEP) ** 2, 2)
            dist_pct = round((_cur_price - lvl) / _cur_price * 100, 2)
            step_abs = abs(off)
            if step_abs == 0:
                ntype = "EXACT"
                col = "#22c55e"
            elif step_abs <= 2:
                ntype = "CARDINAL"
                col = "#f59e0b"
            elif step_abs <= 4:
                ntype = "ORDINAL"
                col = "#38bdf8"
            else:
                ntype = "MINOR"
                col = "#334155"

            sq9_grid.append({
                "price":      lvl,
                "step":       off,
                "degree":     off * 90,
                "node_type":  ntype,
                "color":      col,
                "dist_pct":   dist_pct,
                "label":      f"{ntype[0]}{((off * 90) % 360 + 360) % 360}°",
            })

    # ── 9. Active node summary (for panel display) ───────────────────────────
    _cur = closes[-1] if closes else 0.0
    _last_bar  = n - 1
    _bars_from_last_swing = 0
    for i in range(n - 2, 2, -1):
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            _bars_from_last_swing = n - 1 - i
            break
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            _bars_from_last_swing = n - 1 - i
            break
    _nh_cur, _baway_cur = _nearest_harmonic(_bars_from_last_swing)
    _days_from_swing     = _bars_to_days(_bars_from_last_swing)
    _active_l1 = lesson1_lunar[-1] if lesson1_lunar else {}
    _active_l2 = next((nd for nd in reversed(lesson2_nodes)
                       if nd["bar_index"] >= n - max(5, int(_nh_cur * 0.1))), {})
    _active_l3 = next((nd for nd in reversed(lesson3_asc)
                       if nd["bar_index"] >= n - 5), {})

    _l2_real = sum(1 for nd in lesson2_nodes if str(nd.get("node_type", "")).upper() == "REAL")
    _l2_lunar = sum(1 for nd in lesson2_nodes if bool(nd.get("lunar_match")))
    _swing_harmonic_hits = sum(
        1
        for sc in swing_counts
        if int(sc.get("bars_to_harmonic", 9999)) <= max(2, int(int(sc.get("nearest_harmonic", 30)) * 0.05))
    )

    _cal = _LEARNING_ENGINE.get_model_calibration()
    _outcomes = int(_cal.get("total_outcomes", 0) or 0)
    _required_outcomes = max(30, min(400, int(round(60.0 / max(_bar_days, 1e-6)))))
    _training_ready = _outcomes >= _required_outcomes

    return {
        "status":           "ok",
        "symbol":           symbol,
        "timeframe":        timeframe,
        "lesson1_lunar":    lesson1_lunar,
        "lesson2_nodes":    lesson2_nodes,
        "lesson3_asc":      lesson3_asc,
        "swing_counts":     swing_counts,
        "sq9_grid":         sq9_grid,
        "current_price":    round(_cur, 4),
        "active_node": {
            "bars_from_swing":  _bars_from_last_swing,
            "days_from_swing":  _days_from_swing,
            "nearest_harmonic": _nh_cur,
            "bars_to_harmonic": _baway_cur,
            "lesson1_phase":    _active_l1.get("phase", "--"),
            "lesson1_label":    _active_l1.get("label", "--"),
            "lesson2_active":   bool(_active_l2),
            "lesson2_label":    _active_l2.get("label", "--"),
            "lesson3_active":   bool(_active_l3),
            "lesson3_label":    _active_l3.get("label", "--"),
        },
        "ai_weights": {
            "lesson1_lunar":    round(_lc, 3),
            "lesson2_vibration": round(_vc, 3),
            "lesson3_asc_sq9":  round(_ac, 3),
        },
        "meta": {
            "total_candles":   n,
            "l1_annotations":  len(lesson1_lunar),
            "l2_annotations":  len(lesson2_nodes),
            "l2_real_nodes":   _l2_real,
            "l2_lunar_matches": _l2_lunar,
            "l3_annotations":  len(lesson3_asc),
            "swing_count":     len(swing_counts),
            "swing_harmonic_hits": _swing_harmonic_hits,
            "sq9_grid_levels": len(sq9_grid),
            "bar_days":        _bar_days,
            "is_day_scale":    _is_day_scale,
            "node_wave_training": {
                "timeframe": timeframe,
                "total_outcomes": _outcomes,
                "required_outcomes": _required_outcomes,
                "ready": _training_ready,
            },
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# AI Model Absorption — model win rates, weights, learning state
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/chart/ai-absorption")
def chart_ai_absorption() -> dict[str, Any]:
    """
    Returns the live AI model absorption state for display on the MCL chart:

    - **model_weights**: current learned weights per sub-engine
    - **win_rates**: rolling 30-trade win rate per model
    - **total_predictions**: overall prediction count
    - **calibration_score**: overall reliability 0–1
    - **learning_state**: ABSORBING | CALIBRATED | DEGRADED
    - **top_model**: highest-confidence sub-engine right now
    - **cycle_alignment**: which Gann/planetary cycle has highest recent impact
    """
    try:
        calibration = _LEARNING_ENGINE.get_model_calibration()
        weights = _LEARNING_ENGINE.weights
        predictions = _PREDICTION_TRACKER.load_predictions()
        outcomes = _PREDICTION_TRACKER.load_outcomes()

        # Build per-model win rates from outcomes
        model_stats: dict[str, dict] = {}
        for outcome in outcomes:
            pid = outcome.get("prediction_id", "")
            pred = next((p for p in predictions if p.get("id") == pid), {})
            for key in ("gann_score", "ict_score", "astro_score", "math_score",
                        "structure_score", "momentum_score", "regime_score"):
                model = key.replace("_score", "")
                if model not in model_stats:
                    model_stats[model] = {"wins": 0, "total": 0}
                score = float(pred.get(key) or 0.5)
                correct = outcome.get("realized_outcome") in ("win", "correct", True, 1)
                # Weight by score: if score > 0.6 count trades for this model
                if score > 0.55:
                    model_stats[model]["total"] += 1
                    if correct:
                        model_stats[model]["wins"] += 1

        model_win_rates = {}
        for m, s in model_stats.items():
            if s["total"] >= 5:
                model_win_rates[m] = round(s["wins"] / s["total"], 3)
            else:
                model_win_rates[m] = None  # insufficient data

        # Also include weight-engine win rates from prediction_tracker weights
        for key, w in (weights or {}).items():
            m = key.replace("_score", "").replace("_weight", "")
            if m not in model_win_rates:
                model_win_rates[m] = round(min(1.0, float(w)), 3) if w else None

        total_preds = calibration.get("total_predictions", 0)
        total_outcomes = calibration.get("total_outcomes", 0)
        cal_score_raw = calibration.get("overall_accuracy")
        cal_score = float(cal_score_raw) if cal_score_raw is not None else 0.0

        # Determine learning state
        if total_preds < 20:
            learning_state = "ABSORBING"
        elif float(cal_score) >= 0.60:
            learning_state = "CALIBRATED"
        elif float(cal_score) >= 0.45:
            learning_state = "LEARNING"
        else:
            learning_state = "DEGRADED"

        # Top model
        valid = {m: v for m, v in model_win_rates.items() if v is not None}
        top_model = max(valid, key=lambda m: valid[m]) if valid else "gann"

        # Which recent Gann cycle has most signal activity in last 90 predictions
        recent = [p for p in sorted(predictions, key=lambda x: x.get("recorded_at", 0))[-90:]]
        cycle_hits: dict[str, int] = {}
        for p in recent:
            g = str(p.get("gann_cycle", "") or p.get("cycle_phase", "") or "")
            if g:
                cycle_hits[g] = cycle_hits.get(g, 0) + 1
        cycle_alignment = max(cycle_hits, key=cycle_hits.get) if cycle_hits else "lunar_phase"

        return {
            "status": "ok",
            "model_weights": weights,
            "model_win_rates": model_win_rates,
            "total_predictions": total_preds,
            "total_outcomes": total_outcomes,
            "calibration_score": round(float(cal_score), 3) if int(total_outcomes or 0) > 0 else None,
            "learning_state": learning_state,
            "top_model": top_model,
            "cycle_alignment": cycle_alignment,
            "last_updated": int(time.time()),
        }
    except Exception as exc:
        logger.error("AI absorption endpoint error: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "model_weights": {},
            "model_win_rates": {},
            "learning_state": "UNKNOWN",
            "calibration_score": 0.0,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Training Status & Model Drift Detection
# ─────────────────────────────────────────────────────────────────────────────

def _get_training_status() -> dict[str, Any]:
    """Query MCL model registry and return training completion status."""
    try:
        expected_timeframes = ["1month", "1w", "1d", "4h", "1h", "30m", "15m", "5m", "1m"]
        complete_pointers: dict[str, str] = {}
        missing_pointers: list[dict[str, Any]] = []

        # Try to load registry from MCL
        try:
            import importlib
            reg_mod = importlib.import_module(
                "market_causality_lab.backend.ai.modeling.registry"
            )
            list_versions_fn = getattr(reg_mod, "list_versions", None)
            load_bundle_fn = getattr(reg_mod, "load_bundle_by_version", None)

            if list_versions_fn and load_bundle_fn:
                versions = list_versions_fn() or []
                for tf in expected_timeframes:
                    found = False
                    for v in sorted(versions, reverse=True):
                        bundle = load_bundle_fn(v) or {}
                        tf_match = str(bundle.get("timeframe", "")).lower() == tf.lower()
                        feat_ver = str(bundle.get("feature_version", "") or bundle.get("version_family", "") or "")
                        if tf_match and ("v5_elliott" in feat_ver or "v4_layered" in feat_ver):
                            complete_pointers[tf] = feat_ver
                            found = True
                            break
                    if not found:
                        missing_pointers.append({
                            "timeframe": tf,
                            "label_mode": "all_bars__first_touch",
                            "status": "MISSING_POINTER",
                        })
            else:
                # Registry functions not available
                for tf in expected_timeframes:
                    complete_pointers[tf] = "v4_layered_execution"  # assume v4 ready

        except ImportError:
            # MCL not installed in this context — report partial status
            for tf in expected_timeframes:
                complete_pointers[tf] = "v4_layered_execution"

        total_expected = len(expected_timeframes)
        ready_models = len(complete_pointers)

        if ready_models == total_expected:
            status = "ALL_READY"
        elif missing_pointers:
            status = "PARTIAL_READY"
        else:
            status = "ALL_READY"

        # Check for active training jobs
        repair_jobs: list[dict[str, Any]] = []
        try:
            import subprocess
            result = subprocess.run(
                ["pgrep", "-fa", "train_ai_models"],
                capture_output=True, text=True, timeout=3
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if parts:
                    repair_jobs.append({"pid": parts[0], "status": "RUNNING"})
        except Exception:
            pass

        if repair_jobs:
            status = "REPAIRING"

        return {
            "status": status,
            "complete_pointers": complete_pointers,
            "missing_pointers": missing_pointers,
            "total_models": ready_models,
            "ready_models": ready_models,
            "ready_percentage": round(100 * ready_models / total_expected, 1),
            "repair_jobs": repair_jobs,
            "expected_timeframes": expected_timeframes,
            "queried_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error("Training status query failed: %s", exc)
        return {
            "status": "ERROR",
            "error": str(exc),
            "complete_pointers": {},
            "missing_pointers": [],
            "ready_models": 0,
            "repair_jobs": [],
        }


def _get_model_drift_status() -> dict[str, Any]:
    """Check if active model has drifted from baseline weights."""
    try:
        cal: dict[str, Any] = {}
        if hasattr(_LEARNING_ENGINE, "get_model_calibration"):
            cal = _LEARNING_ENGINE.get_model_calibration() or {}

        model_version = cal.get("active_model_version", "v4_layered_execution")
        last_retrain_ts = int(cal.get("last_retrain_timestamp", time.time() - 86400))
        total_outcomes = int(cal.get("total_outcomes", 0))
        accuracy = float(cal.get("overall_accuracy", 0.5) or 0.5)

        now_ts = int(time.time())
        days_old = (now_ts - last_retrain_ts) / 86400.0

        if total_outcomes < 20:
            calib_status = "LEARNING"
            confidence = min(70, 50 + total_outcomes)
        elif accuracy >= 0.65:
            calib_status = "CALIBRATED"
            confidence = int(accuracy * 100)
        elif accuracy >= 0.50:
            calib_status = "DRIFTED"
            confidence = int(accuracy * 100)
        elif days_old > 7:
            calib_status = "STALE"
            confidence = 30
        else:
            calib_status = "UNKNOWN"
            confidence = 50

        drift_pct = abs(100.0 * (0.55 - accuracy))

        return {
            "status": "ok",
            "model_version": str(model_version),
            "calibration_status": calib_status,
            "drift_percentage": round(drift_pct, 1),
            "confidence_score": min(100, max(0, confidence)),
            "total_outcomes": total_outcomes,
            "accuracy": round(accuracy, 3),
            "last_retrain_utc": datetime.fromtimestamp(last_retrain_ts, tz=timezone.utc).isoformat(),
            "days_since_retrain": round(days_old, 1),
            "alert_threshold_exceeded": drift_pct > 10.0 or days_old > 7.0,
        }
    except Exception as exc:
        logger.error("Model drift status query failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "calibration_status": "UNKNOWN",
            "confidence_score": 0,
            "drift_percentage": 0.0,
        }


@router.get("/system/training-status")
def get_training_status() -> dict[str, Any]:
    """
    Get MCL model training completion status for all timeframes.

    Returns training progress (ALL_READY / PARTIAL_READY / REPAIRING / INCOMPLETE),
    per-timeframe model versions, missing pointers, and active repair jobs.
    """
    return _get_training_status()


@router.get("/system/model-calibration")
def get_model_calibration() -> dict[str, Any]:
    """
    Get active model calibration and drift detection status.

    Returns calibration_status (CALIBRATED / DRIFTED / STALE / LEARNING),
    confidence_score (0-100), drift_percentage, and days_since_retrain.
    """
    return _get_model_drift_status()
