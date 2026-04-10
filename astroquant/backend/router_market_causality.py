from __future__ import annotations

import concurrent.futures
import importlib.util
import inspect
import logging
import multiprocessing as mp
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Query

from astroquant.backend.mathematical_engines import LearningFeedbackEngine, MathematicalQuestionChecker
from astroquant.backend.prediction_tracker import PredictionTracker


router = APIRouter(prefix="/market_causality", tags=["market-causality"])

_module_lock = threading.Lock()
_module = None
_cache_lock = threading.Lock()
_cache_payloads: dict[str, dict[str, Any]] = {}
_cache_ts_by_key: dict[str, float] = {}
_CACHE_TTL_SECONDS = 300.0  # 5-minute cache — summaries take 40-90s to compute
_SUMMARY_TIMEOUT_SECONDS = max(5.0, float(os.getenv("MCL_SUMMARY_TIMEOUT_SECONDS", "90")))
_MATRIX_TIMEFRAMES = ("1d", "4h", "1h", "30m", "15m", "5m", "1m", "1w", "1month")
_MATRIX_MAX_WORKERS = max(1, int(os.getenv("MCL_MATRIX_MAX_WORKERS", "9")))
_PREDICTION_TRACKER = PredictionTracker()
_LEARNING_ENGINE = LearningFeedbackEngine(tracker=_PREDICTION_TRACKER)

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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


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


def _normalize_source_mode(source_mode: str | None) -> str:
    value = str(source_mode or "historical_first").strip().lower()
    allowed = {"historical_first", "historical_only", "live_first", "live_only", "hybrid", "combined"}
    return value if value in allowed else "historical_first"


def _normalize_lookback_years(lookback_years: int | None) -> int:
    years = int(lookback_years) if lookback_years is not None else 25
    return max(1, min(100, years))


def _cache_key(symbol: str, timeframe: str, lookback_years: int, source_mode: str) -> str:
    return f"{symbol}|{timeframe}|{lookback_years}|{source_mode}"


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

    payload = full_system(**call_kwargs)

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
    queue: mp.Queue = mp.Queue(maxsize=1)
    proc = mp.Process(
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
    key = _cache_key(symbol, timeframe, lookback_years, source_mode)

    now = time.time()
    if not refresh:
        with _cache_lock:
            cached = _cache_payloads.get(key)
            cached_ts = _cache_ts_by_key.get(key)
            if cached is not None and cached_ts is not None and (now - cached_ts) <= _CACHE_TTL_SECONDS:
                return cached

    started_at = time.time()
    with _cache_lock:
        previous_for_key = _cache_payloads.get(key)

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
                timeout_seconds=_SUMMARY_TIMEOUT_SECONDS,
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
            "reasoning_display": payload.get("reasoning_display"),
            "reasoning_tone": ((payload.get("reasoning_display") or {}).get("tone")),
            "reasoning_summary": ((payload.get("reasoning_display") or {}).get("summary")),
            "reasoning_chain": ((payload.get("reasoning_display") or {}).get("chain")),
            "reasoning_top_drivers": ((payload.get("reasoning_display") or {}).get("top_drivers")),
            "ai_model": payload.get("ai_model"),
            "ai_model_used": bool(((payload.get("ai_model") or {}).get("used_model"))),
            "ai_model_version": ((payload.get("ai_model") or {}).get("version")),
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
            summary = {
                "status": "timeout",
                "error": str(exc),
                "cache_fallback_used": False,
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

    with _cache_lock:
        _cache_payloads[key] = summary
        _cache_ts_by_key[key] = time.time()

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
            "ai_decision": summary.get("ai_decision"),
            "reasoning_summary": summary.get("reasoning_summary"),
            "reasoning_top_drivers": summary.get("reasoning_top_drivers"),
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
        }

    by_tf: dict[str, dict[str, Any]] = {}
    # Use one worker per timeframe so all run concurrently; each worker's
    # subprocess already has its own _SUMMARY_TIMEOUT_SECONDS cap.
    worker_count = max(1, min(len(_MATRIX_TIMEFRAMES), _MATRIX_MAX_WORKERS))
    # Wait at most summary_timeout + 15 s for the slowest parallel result.
    matrix_wait = _SUMMARY_TIMEOUT_SECONDS + 15.0

    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
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
            for future in concurrent.futures.as_completed(future_map, timeout=matrix_wait):
                tf = future_map[future]
                try:
                    summary = future.result()
                    status = str(summary.get("status") or "").lower()
                    if status in {"ok", "stale_timeout"}:
                        ok_count += 1
                    by_tf[tf] = _summary_to_row(tf, summary)
                except Exception as exc:
                    by_tf[tf] = {
                        "timeframe": tf,
                        "status": "error",
                        "error": str(exc),
                    }
        except concurrent.futures.TimeoutError:
            # Some timeframes did not finish in time; mark them as timeout.
            for fut, tf in future_map.items():
                if tf not in by_tf:
                    by_tf[tf] = {
                        "timeframe": tf,
                        "status": "timeout",
                        "error": f"matrix_timeout>{matrix_wait:.0f}s",
                    }

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
    lookback_years: int = 25,
    limit: int = 12000,
) -> dict[str, Any]:
    symbol = _normalize_symbol(symbol)
    timeframe = _normalize_timeframe(timeframe)
    lookback_years = _normalize_lookback_years(lookback_years)
    limit = max(100, min(int(limit), 50000))

    started_at = time.time()
    try:
        module = _load_module()
        data_dir = str(_repo_root() / "market-causality-lab" / "data")

        load_with_fallback = getattr(module, "_load_historical_with_fallback", None)
        if callable(load_with_fallback):
            df, _dataset_path, applied_timeframe, fallback_meta = load_with_fallback(
                symbol=symbol,
                timeframe=timeframe,
                lookback_years=lookback_years,
                data_dir=data_dir,
            )
        else:
            resolve_timeframe_file = getattr(module, "_resolve_timeframe_file", None)
            load_data = getattr(module, "load_data", None)
            apply_lookback = getattr(module, "_apply_lookback_years", None)
            if not callable(resolve_timeframe_file) or not callable(load_data) or not callable(apply_lookback):
                raise RuntimeError("market-causality-lab historical chart helpers are unavailable")

            path = resolve_timeframe_file(timeframe=timeframe, symbol=symbol, data_dir=data_dir)
            raw_df = load_data(str(path))
            df = apply_lookback(raw_df, lookback_years)
            applied_timeframe = timeframe
            fallback_meta = {
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "fallback_applied": False,
                "fallback_reason": None,
            }

        if "time" not in df.columns:
            raise RuntimeError("historical dataset is missing required time column")

        rows = []
        subset = df[["time", "open", "high", "low", "close", "volume"]].copy()
        subset = subset.dropna(subset=["time", "open", "high", "low", "close"])
        subset = subset.sort_values("time")
        if len(subset) > limit:
            subset = subset.tail(limit)

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
            if historical_last_epoch is not None:
                import os as _os
                from datetime import datetime as _dt, timezone as _tz, timedelta as _td
                import pandas as _pd

                _gap_est = int(max(0, time.time() - historical_last_epoch))
                tf_seconds = _timeframe_seconds(applied_timeframe)
                if _gap_est >= max(60, tf_seconds // 2):
                    _api_key = str(_os.getenv("DATABENTO_API_KEY", "")).strip()
                    if not _api_key:
                        raise RuntimeError("DATABENTO_API_KEY not configured")
                    import databento as _db

                    _start = _dt.fromtimestamp(historical_last_epoch + 1, tz=_tz.utc)
                    # Stay 2h behind "now" to avoid Databento available-end errors
                    _end = _dt.now(_tz.utc) - _td(hours=2)
                    if _end <= _start:
                        raise RuntimeError("gap too small or data too fresh for backfill")

                    _tf_norm = str(applied_timeframe).lower().strip()
                    if _tf_norm in ("1m", "1min", "5m", "15m", "30m"):
                        _schema, _resample_rule = "ohlcv-1m", None
                    elif _tf_norm in ("1h",):
                        _schema, _resample_rule = "ohlcv-1h", None
                    elif _tf_norm in ("4h",):
                        _schema, _resample_rule = "ohlcv-1h", "4h"
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

        historical_depth_fn = getattr(module, "_historical_depth_years", None)
        depth_years = float(historical_depth_fn(df)) if callable(historical_depth_fn) and not df.empty else None

        return {
            "status": "ok",
            "symbol": symbol,
            "requested_timeframe": timeframe,
            "applied_timeframe": str(applied_timeframe),
            "lookback_years": lookback_years,
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
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "symbol": symbol,
            "requested_timeframe": timeframe,
            "lookback_years": lookback_years,
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
    source_mode: str = Query(default="historical_first"),
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


@router.get("/chart")
def market_causality_chart(
    symbol: str = Query(default="XAUUSD"),
    timeframe: str = Query(default="1d"),
    lookback_years: int = Query(default=25, ge=1, le=100),
    limit: int = Query(default=12000, ge=100, le=50000),
) -> dict[str, Any]:
    """Historical candlestick data for the MCL dashboard chart."""
    return _compute_chart(
        symbol=symbol,
        timeframe=timeframe,
        lookback_years=lookback_years,
        limit=limit,
    )


@router.get("/live_price")
def market_causality_live_price(
    symbol: str = Query(default="XAUUSD"),
) -> dict[str, Any]:
    """Return the most recent XAUUSD live spot price.

    Priority chain (XAUUSD spot first, futures proxy as last resort):
      1. Maven broker DOM (real-time XAUUSD spot via CDP bridge)
      2. stooq.com  XAUUSD spot  (free, no API key, ~seconds delay)
      3. Databento Historical API GC.c.1 (CME Gold futures, ~15 min lag)
    Used by the MCL dashboard for periodic live price polling.
    """
    import pandas as _pd
    import urllib.request as _urllib_req

    symbol = _normalize_symbol(symbol)
    started_at = time.time()

    # --- attempt 1: Maven broker DOM spot quote (real-time XAUUSD spot) ---
    try:
        from astroquant.backend.services.runner import get_runner
        _runner = get_runner()
        if _runner is not None:
            _quote = _runner.get_broker_spot_quote("XAUUSD")
            _price = (_quote or {}).get("price") if isinstance(_quote, dict) else getattr(_quote, "price", None)
            if _price and float(_price) > 0 and not (_quote or {}).get("stale", True):
                return {
                    "status": "ok",
                    "symbol": symbol,
                    "price": round(float(_price), 4),
                    "source": "broker_dom_spot",
                    "spot": True,
                    "ts": int(time.time()),
                    "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
                }
    except Exception:
        pass  # fall through to stooq

    # --- attempt 2: stooq.com XAUUSD spot (free, no key, true OTC spot price) ---
    try:
        _req = _urllib_req.Request(
            "https://stooq.com/q/l/?s=xauusd&f=sd2t2ohlcv&h&e=csv",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with _urllib_req.urlopen(_req, timeout=6) as _r:
            _lines = _r.read().decode().strip().split("\n")
        # CSV: Symbol,Date,Time,Open,High,Low,Close,Volume
        if len(_lines) >= 2 and not _lines[1].startswith("N/A"):
            _fields = _lines[1].split(",")
            _price = float(_fields[6])             # Close
            _dt_str = f"{_fields[1]} {_fields[2]}"  # "2026-04-06 04:39:08"
            _ts = int(_pd.Timestamp(_dt_str).timestamp())
            if _price > 0:
                return {
                    "status": "ok",
                    "symbol": symbol,
                    "price": round(_price, 4),
                    "source": "stooq_xauusd_spot",
                    "spot": True,
                    "ts": _ts,
                    "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
                }
    except Exception:
        pass  # fall through to Databento futures proxy

    # --- attempt 3: Databento Historical API (GC.c.1 CME futures, ~15 min lag) ---
    try:
        from astroquant.backend.services.databento_utility import fetch_candles_unified
        candles, _meta = fetch_candles_unified(symbol=symbol, limit=5, minutes=90)
        if candles:
            last = candles[-1]
            price = float(last.get("close") or last.get("open") or 0.0)
            if price > 0:
                _raw_ts = last.get("time") or last.get("timestamp") or last.get("t") or last.get("ts")
                try:
                    _ts = int(_pd.Timestamp(_raw_ts).timestamp()) if _raw_ts is not None else None
                except Exception:
                    _ts = None
                return {
                    "status": "ok",
                    "symbol": symbol,
                    "price": round(price, 4),
                    "source": f"databento_futures/{_meta.get('resolved_symbol','GC.c.1')}",
                    "spot": False,
                    "fallback": True,
                    "ts": _ts,
                    "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
                }
        raise RuntimeError("No candles returned from unified fetch")
    except Exception as exc:
        return {
            "status": "unavailable",
            "symbol": symbol,
            "price": None,
            "source": None,
            "error": str(exc),
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
        }


@router.get("/timeframe_matrix")
def market_causality_timeframe_matrix(
    refresh: bool = Query(default=False),
    symbol: str = Query(default="XAUUSD"),
    lookback_years: int = Query(default=25, ge=1, le=100),
    source_mode: str = Query(default="historical_first"),
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
    _KNOWN_NEW_MOON_TS = 947167440.0   # 2000-01-06 18:14 UTC in epoch seconds
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


@router.get("/chart/overlays")
def chart_overlays(
    symbol: str = Query(default="XAUUSD"),
    timeframe: str = Query(default="1d"),
    lookback_years: int = Query(default=25, ge=1, le=100),
    limit: int = Query(default=12000, ge=100, le=50000),
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
    chart = _compute_chart(symbol=symbol, timeframe=timeframe,
                            lookback_years=lookback_years, limit=limit)
    candles = chart.get("candles", [])
    if not candles:
        return {"status": "ok", "gann_cycles": [], "lunar_events": [],
                "auto_patterns": [], "prediction_zone": [], "gann_angles": [],
                "meta": {"swing_highs_found": 0, "swing_lows_found": 0,
                         "lunar_events_found": 0, "bos_count": 0}}

    # Sort by time
    candles = sorted(candles, key=lambda c: c["time"])

    # ── 2. Gann cycle markers (bar multiples of key cycles) ────────────────
    GANN_CYCLES = [
        (30,  "30°",  "#38bdf8", "circle"),
        (45,  "45°",  "#fbbf24", "square"),
        (90,  "90°",  "#a78bfa", "square"),
        (180, "180°", "#f472b6", "arrowDown"),
        (360, "🔵360°", "#10b981", "arrowDown"),
        (720, "🔵720°", "#22d3ee", "arrowDown"),
    ]
    gann_cycles = []
    for idx, candle in enumerate(candles):
        bar_num = idx + 1
        for cycle, label, color, shape in GANN_CYCLES:
            if bar_num % cycle == 0:
                gann_cycles.append({
                    "time": candle["time"],
                    "label": label,
                    "color": color,
                    "shape": shape,
                    "position": "belowBar",
                    "cycle": cycle,
                })

    # ── 3. Lunar events (New Moon / Full Moon) ─────────────────────────────
    # Known New Moon reference: 2026-03-29 UTC
    _NEW_MOON_EPOCH = 1774828800  # 2026-03-29 00:00 UTC
    _LUNAR_PERIOD = 29.53058 * 86400  # seconds

    first_ts = candles[0]["time"]
    last_ts = candles[-1]["time"]

    # Walk backward from reference to find New Moon before chart start
    ref = _NEW_MOON_EPOCH
    while ref > first_ts:
        ref -= _LUNAR_PERIOD
    while ref < first_ts:
        ref += _LUNAR_PERIOD

    # Build a set of candle timestamps (seconds) for fast lookup
    candle_times = sorted(c["time"] for c in candles)

    def _nearest_candle_time(target_ts):
        """Snap a lunar event timestamp to the nearest candle bar."""
        import bisect
        idx = bisect.bisect_left(candle_times, int(target_ts))
        if idx >= len(candle_times):
            return candle_times[-1]
        if idx == 0:
            return candle_times[0]
        before = candle_times[idx - 1]
        after = candle_times[idx]
        return before if abs(before - target_ts) <= abs(after - target_ts) else after

    lunar_events = []
    t = ref
    half = _LUNAR_PERIOD / 2
    while t <= last_ts + _LUNAR_PERIOD:
        # New Moon
        nm_ts = _nearest_candle_time(t)
        if first_ts <= nm_ts <= last_ts:
            lunar_events.append({
                "time": int(nm_ts),
                "label": "🌑NM",
                "color": "#94a3b8",
                "shape": "circle",
                "position": "aboveBar",
                "type": "new_moon",
            })
        # Full Moon (half period later)
        fm_ts = _nearest_candle_time(t + half)
        if first_ts <= fm_ts <= last_ts:
            lunar_events.append({
                "time": int(fm_ts),
                "label": "🌕FM",
                "color": "#fcd34d",
                "shape": "circle",
                "position": "aboveBar",
                "type": "full_moon",
            })
        t += _LUNAR_PERIOD

    # ── 4. Auto-pattern identification — Swing H/L + BOS/CHOCH ───────────
    # Rolling window pivot detection: swing high = highest of N bars each side
    SWING_N = 5   # pivot bars each side
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
        if idx - last_sh >= 30:
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
        if idx - last_sl >= 30:
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
        if i - last_bos < 20:
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

    # ── 5. Prediction zone — Gann angle + P(t) projection ─────────────────
    # Project 30 calendar days forward from last candle
    prediction_zone = []
    try:
        from astroquant.engine.gann.gann_astro_timing_engine import price_time_vibration, ORBITAL_PERIODS

        last_candle = candles[-1]
        base_price = float(last_candle["close"])
        base_time = int(last_candle["time"])

        # Determine bar interval in seconds
        if len(candles) >= 2:
            dts = [candles[i+1]["time"] - candles[i]["time"]
                   for i in range(max(0, len(candles)-20), len(candles)-1)
                   if candles[i+1]["time"] > candles[i]["time"]]
            bar_secs = int(sum(dts) / len(dts)) if dts else 86400
        else:
            bar_secs = 86400

        # 1×1 Gann angle: 1 price unit per time unit (normalised to daily)
        ppu = base_price * 0.001   # ~0.1% per bar as Gann 1×1 daily
        R   = base_price * 0.05    # 5% amplitude for P(t) resonance
        T   = ORBITAL_PERIODS.get("saturn", 10759.0)   # Saturn major cycle
        Z   = base_price * 0.02

        N_BARS = 30
        for n in range(1, N_BARS + 1):
            future_time = base_time + n * bar_secs
            days_out = (n * bar_secs) / 86400.0
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

    # ── 6. Gann angle lines from last major swing low ──────────────────────
    gann_angles = []
    try:
        if sl_list:
            anchor_idx, anchor_price, anchor_time = sl_list[-1]  # last swing low
            ppu_day = anchor_price * 0.001  # normalised per-bar move
            bar_span = max(1, (last_ts - anchor_time) // max(1, bar_secs))
            current_bar = bar_span

            for ratio, label, color in [
                (1.0, "1×1", "#fbbf24"),
                (2.0, "2×1", "#10b981"),
                (0.5, "1×2", "#f472b6"),
            ]:
                # Line from anchor → end of history
                gann_angles.append({
                    "label": label,
                    "color": color,
                    "points": [
                        {"time": int(anchor_time), "value": round(anchor_price, 4)},
                        {"time": int(last_ts),     "value": round(anchor_price + ratio * ppu_day * current_bar, 4)},
                    ],
                })
    except Exception as _exc:
        logging.debug("Gann angle lines compute failed: %s", _exc)

    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "total_candles": len(candles),
        "gann_cycles": gann_cycles,
        "lunar_events": lunar_events,
        "auto_patterns": auto_patterns,
        "prediction_zone": prediction_zone,
        "gann_angles": gann_angles,
        # ── Moon phase + Gann cycle identification (live) ──────────────────────
        "moon": _build_moon_overlay(candles),
        # ── Gann Node pressure points (time+price spiral convergence) ──────────
        "gann_nodes": _build_node_overlay(candles, _cache_payloads.get(f"{symbol}_{timeframe}")),
        # ── Time Compression (silence = signal, cycles tightening = breakout near)
        "compression": _build_compression_overlay(candles, _cache_payloads.get(f"{symbol}_{timeframe}")),
        "meta": {
            "swing_highs_found": len(swing_highs),
            "swing_lows_found":  len(swing_lows),
            "lunar_events_found": len(lunar_events),
            "bos_count": sum(1 for p in auto_patterns if p["type"].startswith("bos")),
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
        cal_score = calibration.get("overall_accuracy") or 0.0

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
            "calibration_score": round(float(cal_score), 3),
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
