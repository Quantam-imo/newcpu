from __future__ import annotations

import copy
import concurrent.futures
import csv
import json
import math
import os
import random
import shutil
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.ai.mentor_engine import MentorEngine
from backend.config import (
    ADMIN_API_TOKEN,
    ADMIN_DEFAULT_ROLE,
    DATABENTO_STRICT_STARTUP,
    symbol_dataset,
    EXECUTION_BROWSER_AUTO_ATTACH,
    EXECUTION_BROWSER_CDP_URL,
    EXECUTION_BROWSER_HEADLESS,
    EXECUTION_BROWSER_TIMEOUT_MS,
    EXECUTION_BROWSER_URL,
    EXECUTION_BROWSER_USER_DATA_DIR,
)
from backend.governance.dynamic_prop_engine import DynamicPropEngine
from backend.governance.prop_governance import PropConfig, PropGovernance
from backend.integration.broker_sync import fetch_equity_from_browser
from backend.integration.telegram_notify import build_daily_summary, daily_metrics_from_journal, send_daily_summary
from backend.journal.ai_trade_journal import init_journal, recent_trades
from backend.reports.monthly_report import generate_monthly_report
from backend.router_admin import build_admin_router
from core.prop_profiles import profile_risk_pct, supported_account_keys, supported_modes
from engine.multi_symbol_runner import MultiSymbolRunner
from engine.delta_engine import DeltaEngine
from engine.dom_engine import DomEngine
from engine.orderflow_summary_engine import OrderflowSummaryEngine
from engine.time_sales_engine import TimeSalesEngine
from execution.playwright_engine import PlaywrightEngine

BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BASE_DIR / "frontend"

symbols = ["XAUUSD", "NQ", "EURUSD", "BTC", "US30"]
prop_engine = PropGovernance(PropConfig())
runner = MultiSymbolRunner(symbols, prop_engine=prop_engine)
time_sales_engine = TimeSalesEngine(getattr(getattr(runner, "signal_manager", None), "orderflow_engine", None))
delta_engine = DeltaEngine()
dom_engine = DomEngine()
orderflow_summary_engine = OrderflowSummaryEngine()
dynamic_prop_engine = DynamicPropEngine()
mentor_engine = MentorEngine()
runner_thread = None

SELECTOR_PROFILE_PATH = Path("data/matchtrader_selectors.json")
EXECUTION_BROWSER_LOCK = threading.Lock()
runtime_browser_engine = None
CHART_CANDLE_CACHE_LOCK = threading.Lock()
CHART_CANDLE_CACHE: dict[str, list[dict]] = {}
CHART_FEED_GUARD_LOCK = threading.Lock()
CHART_FEED_GUARD: dict[str, dict] = {}
EXECUTION_RECONNECT_STATE_LOCK = threading.Lock()
EXECUTION_RECONNECT_STATE = {
    "in_progress": False,
    "started_at": None,
    "finished_at": None,
    "last_result": None,
}
APP_STARTED_AT = time.time()
JOURNAL_EXPORT_DIR = BASE_DIR / "reports" / "journal_dayend"
JOURNAL_EXPORT_EVENT = threading.Event()
JOURNAL_EXPORT_THREAD = None
LAST_PHASE_EVENT = None
TIMEOUT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=12, thread_name_prefix="aq-timeout")


def _phase_base_confidence_threshold(phase: str) -> float:
    key = str(phase or "PHASE1").upper()
    if key == "PHASE2":
        return 77.0
    if key == "FUNDED":
        return 72.0
    return 75.0


def _dynamic_summary_text(snapshot: dict, phase: str) -> str:
    primary = snapshot.get("primary_profile", {}) if isinstance(snapshot, dict) else {}
    portfolio = snapshot.get("portfolio", {}) if isinstance(snapshot, dict) else {}
    active_accounts = list(snapshot.get("active_accounts", []) or [])
    risk_pct = float(portfolio.get("strict_risk_pct", 0.0) or 0.0) * 100.0
    return (
        "🏛 Dynamic Prop Engine Recalibrated\n"
        f"Primary: {primary.get('account_key', '--')} {primary.get('mode', 'STANDARD')}\n"
        f"Active: {', '.join(active_accounts) if active_accounts else '--'}\n"
        f"Phase: {phase}\n"
        f"Risk/Trade: {risk_pct:.2f}%\n"
        f"Daily Max Loss: ${float(primary.get('daily_max_loss', 0.0) or 0.0):.2f}\n"
        f"Total Max Loss: ${float(primary.get('total_max_loss', 0.0) or 0.0):.2f}"
    )


def _apply_dynamic_prop_runtime(send_telegram_update: bool = False):
    phase = str(getattr(prop_engine, "phase", "PHASE1") or "PHASE1").upper()
    snapshot = dynamic_prop_engine.snapshot(phase=phase)
    primary = dict(snapshot.get("primary_profile", {}) or {})
    portfolio = dict(snapshot.get("portfolio", {}) or {})
    profiles = list(portfolio.get("profiles", []) or [])

    if not primary:
        return snapshot

    prop_engine.apply_profile(primary)
    prop_engine.phase = phase

    if profiles:
        strict_phase_risk = {
            "PHASE1": min(profile_risk_pct(item, "PHASE1") for item in profiles),
            "PHASE2": min(profile_risk_pct(item, "PHASE2") for item in profiles),
            "FUNDED": min(profile_risk_pct(item, "FUNDED") for item in profiles),
        }
    else:
        strict_phase_risk = {
            "PHASE1": profile_risk_pct(primary, "PHASE1"),
            "PHASE2": profile_risk_pct(primary, "PHASE2"),
            "FUNDED": profile_risk_pct(primary, "FUNDED"),
        }

    prop_engine.phase_risk_pct = strict_phase_risk

    strict_daily_dd_pct = float(portfolio.get("strict_daily_dd_pct", primary.get("daily_dd_pct", 4.0)) or 4.0)
    strict_max_dd_pct = float(portfolio.get("strict_max_dd_pct", primary.get("max_dd_pct", 8.0)) or 8.0)

    prop_engine.config.internal_daily_guard_pct = max(0.005, min(0.3, strict_daily_dd_pct / 100.0))
    prop_engine.config.static_dd_pct = max(0.01, min(0.5, strict_max_dd_pct / 100.0))
    prop_engine.static_floor = float(prop_engine.config.account_size) * (1.0 - float(prop_engine.config.static_dd_pct))

    runner.risk.max_risk_per_trade = max(0.0001, min(0.03, strict_phase_risk.get(phase, strict_phase_risk.get("PHASE1", 0.005))))
    runner.risk.daily_loss_limit = float(prop_engine.config.account_size) * float(prop_engine.config.internal_daily_guard_pct)
    runner.risk.max_drawdown_floor = float(prop_engine.static_floor)

    primary_clawbot = dict(primary.get("clawbot", {}) or {})
    if primary_clawbot and hasattr(runner, "clawbot") and runner.clawbot:
        runner.clawbot.configure(primary_clawbot)

    confidence_shift = float(primary.get("confidence_shift", 0.0) or 0.0)
    runner.min_confidence_threshold = max(50.0, min(90.0, _phase_base_confidence_threshold(phase) + confidence_shift))
    runner.dynamic_prop_state = snapshot

    if send_telegram_update:
        try:
            runner.telegram.send(_dynamic_summary_text(snapshot, phase))
        except Exception:
            pass
    return snapshot


def _handle_phase_event(status: str | None):
    global LAST_PHASE_EVENT
    event = str(status or "").upper().strip()
    if not event.startswith("PHASE_UPGRADED_"):
        return

    _apply_dynamic_prop_runtime(send_telegram_update=False)
    if LAST_PHASE_EVENT == event:
        return

    LAST_PHASE_EVENT = event
    try:
        runner.telegram.send(
            f"✅ Phase Auto-Upgrade\n"
            f"Event: {event}\n"
            f"New Phase: {prop_engine.phase}\n"
            f"Dynamic risk profile auto-recalibrated."
        )
    except Exception:
        pass


def _runner_prop_status_callback(status: str | None):
    _handle_phase_event(status)


def _timestamp_to_utc_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
        except Exception:
            return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).date()
    except Exception:
        pass
    try:
        return datetime.fromtimestamp(float(raw), tz=timezone.utc).date()
    except Exception:
        return None


def _export_journal_day(day: date) -> Path | None:
    rows = _journal_rows_for_symbol(symbol=None, limit=100000)
    filtered = [row for row in (rows or []) if _timestamp_to_utc_date(row[0] if isinstance(row, (list, tuple)) and row else None) == day]

    JOURNAL_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = JOURNAL_EXPORT_DIR / f"journal_{day.isoformat()}.csv"

    with out_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(["timestamp", "symbol", "model", "result", "r_multiple", "pnl", "phase"])
        for row in filtered:
            writer.writerow(list(row))
    return out_path


def _journal_dayend_worker():
    last_seen_day = datetime.now(timezone.utc).date()
    while not JOURNAL_EXPORT_EVENT.wait(45):
        now_day = datetime.now(timezone.utc).date()
        if now_day == last_seen_day:
            continue
        try:
            _export_journal_day(last_seen_day)
        except Exception:
            pass
        last_seen_day = now_day


def _start_journal_dayend_worker():
    global JOURNAL_EXPORT_THREAD
    JOURNAL_EXPORT_EVENT.clear()
    if JOURNAL_EXPORT_THREAD is not None and JOURNAL_EXPORT_THREAD.is_alive():
        return
    JOURNAL_EXPORT_THREAD = threading.Thread(target=_journal_dayend_worker, daemon=True)
    JOURNAL_EXPORT_THREAD.start()


def _stop_journal_dayend_worker():
    global JOURNAL_EXPORT_THREAD
    JOURNAL_EXPORT_EVENT.set()
    thread = JOURNAL_EXPORT_THREAD
    JOURNAL_EXPORT_THREAD = None
    if thread is not None and thread.is_alive():
        thread.join(timeout=1.2)


def _run_with_timeout(seconds: float, func, fallback):
    timeout_seconds = max(0.05, float(seconds or 0.05))
    future = TIMEOUT_EXECUTOR.submit(func)
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        try:
            future.cancel()
        except Exception:
            pass
        return fallback
    except Exception:
        return fallback


def _chart_feed_guard_snapshot(symbol: str) -> dict:
    key = str(symbol or "").upper()
    now = time.time()
    with CHART_FEED_GUARD_LOCK:
        state = dict(CHART_FEED_GUARD.get(key, {}))
    cooldown_until = float(state.get("cooldown_until", 0.0) or 0.0)
    cooldown_remaining = max(0.0, cooldown_until - now)
    return {
        "symbol": key,
        "miss_count": int(state.get("miss_count", 0) or 0),
        "last_miss_at": state.get("last_miss_at"),
        "last_success_at": state.get("last_success_at"),
        "last_reason": state.get("last_reason"),
        "cooldown_until": cooldown_until,
        "cooldown_active": cooldown_remaining > 0.0,
        "cooldown_seconds": round(cooldown_remaining, 2),
    }


def _chart_feed_guard_success(symbol: str):
    key = str(symbol or "").upper()
    now = time.time()
    with CHART_FEED_GUARD_LOCK:
        CHART_FEED_GUARD[key] = {
            "miss_count": 0,
            "last_miss_at": CHART_FEED_GUARD.get(key, {}).get("last_miss_at"),
            "last_success_at": now,
            "last_reason": None,
            "cooldown_until": 0.0,
        }


def _chart_feed_guard_miss(symbol: str, reason: str | None = None):
    key = str(symbol or "").upper()
    now = time.time()
    with CHART_FEED_GUARD_LOCK:
        previous = dict(CHART_FEED_GUARD.get(key, {}))
        miss_count = int(previous.get("miss_count", 0) or 0) + 1
        cooldown_until = float(previous.get("cooldown_until", 0.0) or 0.0)
        if miss_count >= 3:
            cooldown_span = min(30.0, 4.0 + float(miss_count - 3) * 3.0)
            cooldown_until = max(cooldown_until, now + cooldown_span)
        CHART_FEED_GUARD[key] = {
            "miss_count": miss_count,
            "last_miss_at": now,
            "last_success_at": previous.get("last_success_at"),
            "last_reason": str(reason or previous.get("last_reason") or "feed_unavailable"),
            "cooldown_until": cooldown_until,
        }


def _float_value(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _latest_trade_for_symbol(symbol: str):
    trade_log = Path("logs/trade_log.json")
    if not trade_log.exists():
        return None
    lines = trade_log.read_text(encoding="utf-8").splitlines()
    for raw_line in reversed(lines):
        try:
            row = json.loads(raw_line)
        except Exception:
            continue
        if str(row.get("symbol", "")).upper() == str(symbol).upper():
            return row
    return None


def selector_profile_status():
    if not SELECTOR_PROFILE_PATH.exists():
        return {
            "calibrated": False,
            "profile_file": str(SELECTOR_PROFILE_PATH),
            "updated_at": None,
            "selector_counts": {},
        }
    try:
        payload = json.loads(SELECTOR_PROFILE_PATH.read_text(encoding="utf-8"))
        selectors = payload.get("selectors", {}) if isinstance(payload, dict) else {}
        selector_counts = {
            key: len(value) if isinstance(value, list) else 0
            for key, value in selectors.items()
        } if isinstance(selectors, dict) else {}
        updated_raw = payload.get("updated_at") if isinstance(payload, dict) else None
        updated_iso = None
        if isinstance(updated_raw, (int, float)) and updated_raw > 0:
            updated_iso = datetime.fromtimestamp(float(updated_raw), tz=timezone.utc).isoformat()
        return {
            "calibrated": bool(selector_counts),
            "profile_file": str(SELECTOR_PROFILE_PATH),
            "updated_at": updated_iso,
            "selector_counts": selector_counts,
        }
    except Exception as exc:
        return {
            "calibrated": False,
            "profile_file": str(SELECTOR_PROFILE_PATH),
            "updated_at": None,
            "selector_counts": {},
            "error": str(exc),
        }


def execution_connection_status():
    execution_health = runner.execution.execution_health()
    return {
        "connected": bool(runner.execution.playwright.page),
        "auto_attach_enabled": bool(EXECUTION_BROWSER_AUTO_ATTACH),
        "cdp_configured": bool(EXECUTION_BROWSER_CDP_URL),
        "user_data_dir_configured": bool(EXECUTION_BROWSER_USER_DATA_DIR),
        "reconnect_attempts": int(execution_health.get("reconnect_attempts") or 0),
        "last_reconnect_attempt": execution_health.get("last_reconnect_attempt"),
    }


def _connect_execution_browser(force: bool = False):
    global runtime_browser_engine

    with EXECUTION_BROWSER_LOCK:
        current_page = runner.execution.playwright.page
        if current_page is not None and not force:
            return {"status": "connected", "connected": True, "mode": "existing", "page": current_page}

        if not (EXECUTION_BROWSER_CDP_URL or EXECUTION_BROWSER_USER_DATA_DIR):
            return {
                "status": "not_configured",
                "connected": bool(current_page),
                "reason": "Set EXECUTION_BROWSER_CDP_URL or EXECUTION_BROWSER_USER_DATA_DIR",
                "page": current_page,
            }

        try:
            if force and runtime_browser_engine is not None:
                runtime_browser_engine.close()
                runtime_browser_engine = None

            if runtime_browser_engine is None:
                runtime_browser_engine = PlaywrightEngine(
                    headless=EXECUTION_BROWSER_HEADLESS,
                    timeout_ms=EXECUTION_BROWSER_TIMEOUT_MS,
                    user_data_dir=EXECUTION_BROWSER_USER_DATA_DIR or None,
                    cdp_url=EXECUTION_BROWSER_CDP_URL or None,
                )

            page = runtime_browser_engine.start()
            if page is None:
                return {"status": "error", "connected": False, "reason": "Playwright returned no page", "page": None}

            if EXECUTION_BROWSER_URL and not EXECUTION_BROWSER_CDP_URL:
                try:
                    runtime_browser_engine.goto(EXECUTION_BROWSER_URL)
                except Exception:
                    pass

            runner.execution.set_page(page)
            return {
                "status": "connected",
                "connected": True,
                "mode": "cdp" if EXECUTION_BROWSER_CDP_URL else "persistent",
                "page": page,
            }
        except Exception as exc:
            import traceback, logging
            logging.basicConfig(level=logging.ERROR)
            logging.error("Playwright/browser startup failed: %s\n%s", str(exc), traceback.format_exc())
            return {
                "status": "error",
                "connected": bool(getattr(runner.execution.playwright, 'page', False)),
                "reason": f"{exc}",
                "traceback": traceback.format_exc(),
                "page": getattr(runner.execution.playwright, 'page', None),
            }


def _execution_reconnect_handler():
    result = _connect_execution_browser(force=True)
    return result.get("page")


def _execution_reconnect_snapshot():
    with EXECUTION_RECONNECT_STATE_LOCK:
        return copy.deepcopy(EXECUTION_RECONNECT_STATE)


def _trigger_execution_reconnect(force: bool = True):
    with EXECUTION_RECONNECT_STATE_LOCK:
        if EXECUTION_RECONNECT_STATE.get("in_progress"):
            return False
        EXECUTION_RECONNECT_STATE["in_progress"] = True
        EXECUTION_RECONNECT_STATE["started_at"] = int(time.time())
        EXECUTION_RECONNECT_STATE["finished_at"] = None
        EXECUTION_RECONNECT_STATE["last_result"] = None

    def worker():
        result = _connect_execution_browser(force=force)
        payload = {
            "status": result.get("status"),
            "connected": bool(result.get("connected")),
            "mode": result.get("mode"),
            "reason": result.get("reason"),
        }
        with EXECUTION_RECONNECT_STATE_LOCK:
            EXECUTION_RECONNECT_STATE["in_progress"] = False
            EXECUTION_RECONNECT_STATE["finished_at"] = int(time.time())
            EXECUTION_RECONNECT_STATE["last_result"] = payload

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return True


def _chart_overlays(candles: list[dict]):
    if not candles:
        return {
            "liquidity": [],
            "order_blocks": [],
            "fvg": [],
            "iceberg": [],
            "vwap": [],
            "atr_band": {"upper": [], "lower": []},
            "gann_lines": [],
            "astro_markers": [],
            "session_separators": [],
        }

    vwap = []
    cum_pv = 0.0
    cum_vol = 0.0
    trs = []
    atr_upper = []
    atr_lower = []
    liquidity = []
    order_blocks = []
    fvg = []
    iceberg = []
    gann_lines = []
    astro_markers = []
    session_separators = []
    prev_close = _float_value(candles[0].get("close"))

    highs = []
    lows = []
    volumes = []

    last_session_bucket = None

    for idx, row in enumerate(candles):
        ts = int(row.get("time", 0))
        high = _float_value(row.get("high"))
        low = _float_value(row.get("low"))
        close = _float_value(row.get("close"))
        open_px = _float_value(row.get("open"))
        volume = max(0.0, _float_value(row.get("volume"), 0.0))
        highs.append(high)
        lows.append(low)
        volumes.append(volume)

        session_bucket = ts // (6 * 60 * 60)
        if last_session_bucket is None or session_bucket != last_session_bucket:
            session_separators.append({"time": ts, "session": "SESSION"})
            last_session_bucket = session_bucket

        if idx > 0 and idx % 20 == 0:
            astro_markers.append({"time": ts, "label": "AST"})

        typical = (high + low + close) / 3.0
        cum_pv += typical * volume
        cum_vol += volume
        vwap.append({"time": ts, "value": (cum_pv / cum_vol) if cum_vol > 0 else close})

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        window = trs[max(0, len(trs) - 14):]
        atr = sum(window) / max(1, len(window))
        atr_upper.append({"time": ts, "value": close + atr * 1.5})
        atr_lower.append({"time": ts, "value": close - atr * 1.5})

        lookback = candles[max(0, idx - 20):idx]
        if lookback:
            prev_high = max(_float_value(c.get("high")) for c in lookback)
            prev_low = min(_float_value(c.get("low")) for c in lookback)
            if high >= prev_high:
                liquidity.append({"time": ts, "price": round(high, 5), "strength": "BUY_SIDE"})
            if low <= prev_low:
                liquidity.append({"time": ts, "price": round(low, 5), "strength": "SELL_SIDE"})

        recent_vol = volumes[max(0, len(volumes) - 20):]
        avg_vol = (sum(recent_vol[:-1]) / max(1, len(recent_vol) - 1)) if len(recent_vol) > 1 else recent_vol[-1]
        spread = max(1e-9, high - low)
        if avg_vol > 0 and volume > avg_vol * 1.8 and spread <= max(1e-6, (sum(highs[max(0, len(highs) - 10):]) / max(1, len(highs[max(0, len(highs) - 10):])) - sum(lows[max(0, len(lows) - 10):]) / max(1, len(lows[max(0, len(lows) - 10):]))) * 0.8):
            iceberg.append({"time": ts, "price": round(close, 5), "absorption_strength": round(volume / max(1.0, avg_vol), 2)})

        body = abs(close - open_px)
        candle_range = max(1e-9, high - low)
        if body >= candle_range * 0.55:
            direction = "BULLISH" if close >= open_px else "BEARISH"
            order_blocks.append(
                {
                    "time": ts,
                    "high": round(high, 5),
                    "low": round(low, 5),
                    "direction": direction,
                }
            )

        if idx >= 2:
            c0 = candles[idx - 2]
            c2 = row
            high0 = _float_value(c0.get("high"))
            low0 = _float_value(c0.get("low"))
            high2 = _float_value(c2.get("high"))
            low2 = _float_value(c2.get("low"))
            if low2 > high0:
                fvg.append({"time": ts, "high": round(low2, 5), "low": round(high0, 5), "direction": "BULLISH"})
            elif high2 < low0:
                fvg.append({"time": ts, "high": round(low0, 5), "low": round(high2, 5), "direction": "BEARISH"})

        prev_close = close

    if highs and lows:
        high_ext = max(highs)
        low_ext = min(lows)
        span = max(1e-9, high_ext - low_ext)
        for ratio, label in ((0.25, "Gann 25%"), (0.5, "Gann 50%"), (0.75, "Gann 75%")):
            gann_lines.append({"price": round(low_ext + span * ratio, 5), "label": label})

    if not fvg and len(candles) >= 6:
        mid = len(candles) // 2
        left = candles[max(1, mid - 2)]
        right = candles[min(len(candles) - 1, mid + 2)]
        left_high = _float_value(left.get("high"))
        right_low = _float_value(right.get("low"))
        gap_top = max(left_high, right_low)
        gap_bottom = min(left_high, right_low)
        if gap_top > gap_bottom:
            fvg.append(
                {
                    "time": int(right.get("time", 0)),
                    "high": round(gap_top, 5),
                    "low": round(gap_bottom, 5),
                    "direction": "BULLISH" if right_low >= left_high else "BEARISH",
                }
            )

    if not iceberg and candles:
        max_idx = max(range(len(candles)), key=lambda i: _float_value(candles[i].get("volume", 0.0)))
        row = candles[max_idx]
        iceberg.append(
            {
                "time": int(row.get("time", 0)),
                "price": round(_float_value(row.get("close")), 5),
                "absorption_strength": 1.0,
            }
        )

    price_span = max(1e-6, (max(highs) - min(lows)) if highs and lows else 1.0)
    level_gap = max(1e-4, price_span * 0.006)

    def _thin_price_rows(rows: list[dict], max_items: int, price_key: str = "price"):
        accepted = []
        for row in reversed(rows or []):
            price = _float_value(row.get(price_key), None)
            if price is None:
                continue
            too_close = any(abs(_float_value(existing.get(price_key), 0.0) - price) < level_gap for existing in accepted)
            if too_close:
                continue
            accepted.append(row)
            if len(accepted) >= max_items:
                break
        accepted.reverse()
        return accepted

    def _thin_zone_rows(rows: list[dict], max_items: int):
        accepted = []
        for row in reversed(rows or []):
            zone_mid = (_float_value(row.get("high"), 0.0) + _float_value(row.get("low"), 0.0)) / 2.0
            too_close = False
            for existing in accepted:
                existing_mid = (_float_value(existing.get("high"), 0.0) + _float_value(existing.get("low"), 0.0)) / 2.0
                if abs(existing_mid - zone_mid) < level_gap:
                    too_close = True
                    break
            if too_close:
                continue
            accepted.append(row)
            if len(accepted) >= max_items:
                break
        accepted.reverse()
        return accepted

    liquidity = _thin_price_rows(liquidity, max_items=22, price_key="price")
    order_blocks = _thin_zone_rows(order_blocks, max_items=16)
    fvg = _thin_zone_rows(fvg, max_items=12)
    iceberg = _thin_price_rows(iceberg, max_items=10, price_key="price")
    astro_markers = list((astro_markers or [])[-12:])
    session_separators = list((session_separators or [])[-12:])

    return {
        "liquidity": liquidity,
        "order_blocks": order_blocks,
        "fvg": fvg,
        "iceberg": iceberg,
        "vwap": vwap,
        "atr_band": {"upper": atr_upper, "lower": atr_lower},
        "gann_lines": gann_lines,
        "astro_markers": astro_markers,
        "session_separators": session_separators,
    }


def _chart_meta(symbol: str):
    market_ctx = market_context(symbol)
    execution_health = runner.execution.execution_health()
    paused_reasons = []
    if str(execution_health.get("execution_status", "OK")).upper() == "HALTED":
        paused_reasons.append("Execution halted")
    if not prop_engine.can_trade():
        paused_reasons.append("Prop governance lock")
    if bool(runner.state.news_halt):
        paused_reasons.append("News halt")
    return {
        "confidence": round(_float_value(market_ctx.get("confidence"), 0.0), 2),
        "phase": prop_engine.phase,
        "risk_percent": round(_float_value(market_ctx.get("risk_percent"), prop_engine.get_phase_risk()) * 100.0, 3),
        "volatility_state": prop_engine.volatility_mode,
        "auto_mode": "AUTO" if (prop_engine.can_trade() and str(execution_health.get("execution_status", "OK")).upper() != "HALTED") else "PAUSED",
        "news": "HALT" if runner.state.news_halt else "NONE",
        "system_paused": len(paused_reasons) > 0,
        "pause_reason": " | ".join(paused_reasons) if paused_reasons else None,
        "position": market_ctx.get("position"),
        "data_source": "LIVE",
    }


def _synthetic_candles(limit: int = 120, base_price: float = 2325.0):
    points = max(30, min(int(limit or 120), 1000))
    now = int(time.time() // 60) * 60
    seed = int(now // 60) ^ int(float(base_price) * 100)
    rng = random.Random(seed)
    out = []
    prev_close = float(base_price)
    for i in range(points):
        t = now - ((points - i - 1) * 60)
        trend = 0.01 * math.sin(i / 18.0)
        shock = rng.uniform(-0.22, 0.22)
        step = trend + shock

        o = max(1.0, prev_close)
        c = max(1.0, o + step)
        wick_up = abs(rng.uniform(0.02, 0.16))
        wick_dn = abs(rng.uniform(0.02, 0.16))
        h = max(o, c) + wick_up
        l = max(0.01, min(o, c) - wick_dn)

        base_vol = 90 + (i % 24) * 2
        vol_noise = rng.randint(0, 40)
        v = int(base_vol + vol_noise)

        o = round(o, 4)
        c = round(c, 4)
        h = round(max(h, o, c), 4)
        l = round(min(l, o, c), 4)
        out.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v})
        prev_close = c
    return out


def _timeframe_to_minutes(timeframe: str) -> int:
    key = str(timeframe or "1m").strip().lower()
    mapping = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
    }
    return int(mapping.get(key, 1))


def _aggregate_candles(candles: list[dict], timeframe_minutes: int) -> list[dict]:
    tf = max(1, int(timeframe_minutes or 1))
    if not candles:
        return []

    bucket_seconds = max(60, tf * 60)
    cleaned = []
    for row in candles:
        ts = int(row.get("time", 0) or 0)
        if ts <= 0:
            continue

        o = _float_value(row.get("open", 0.0))
        h = _float_value(row.get("high", 0.0))
        l = _float_value(row.get("low", 0.0))
        c = _float_value(row.get("close", 0.0))
        v = max(0.0, _float_value(row.get("volume", 0.0)))

        if o <= 0.0 or h <= 0.0 or l <= 0.0 or c <= 0.0:
            continue

        high = max(h, o, c)
        low = min(l, o, c)
        if high < low:
            continue

        cleaned.append({
            "time": ts,
            "open": o,
            "high": high,
            "low": low,
            "close": c,
            "volume": v,
        })

    if not cleaned:
        return []

    cleaned.sort(key=lambda x: int(x.get("time", 0)))

    out = []
    current = None
    for row in cleaned:
        ts = int(row.get("time", 0))
        bucket = (ts // bucket_seconds) * bucket_seconds
        o = _float_value(row.get("open", 0.0))
        h = _float_value(row.get("high", 0.0))
        l = _float_value(row.get("low", 0.0))
        c = _float_value(row.get("close", 0.0))
        v = max(0.0, _float_value(row.get("volume", 0.0)))

        if current is None or int(current.get("time", 0)) != bucket:
            if current is not None:
                out.append(current)
            current = {
                "time": bucket,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
            continue

        current["high"] = max(_float_value(current.get("high", h)), h)
        current["low"] = min(_float_value(current.get("low", l)), l)
        current["close"] = c
        current["volume"] = _float_value(current.get("volume", 0.0)) + v

    if current is not None:
        out.append(current)
    return out


def _journal_model_stats(limit: int = 500):
    rows = []
    try:
        conn = sqlite3.connect("ai_trade_journal.db")
        cur = conn.cursor()
        cur.execute("SELECT model, result FROM trades ORDER BY id DESC LIMIT ?", (int(limit),))
        rows = cur.fetchall() or []
        conn.close()
    except Exception:
        rows = []

    stats = {}
    for model, result in rows:
        name = str(model or "UNKNOWN")
        bucket = stats.setdefault(name, {"wins": 0, "losses": 0})
        if str(result or "").upper() in {"WIN", "TP_HIT", "PROFIT"}:
            bucket["wins"] += 1
        else:
            bucket["losses"] += 1
    return stats


def _canonical_symbol(symbol: str | None) -> str | None:
    if not symbol:
        return None
    feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
    return feed_to_canonical.get(symbol, symbol)


def _journal_model_stats_for_symbol(symbol: str | None, limit: int = 500):
    canonical = _canonical_symbol(symbol)
    if not canonical:
        return _journal_model_stats(limit=limit)

    rows = []
    try:
        conn = sqlite3.connect("ai_trade_journal.db")
        cur = conn.cursor()
        cur.execute(
            "SELECT model, result FROM trades WHERE UPPER(symbol)=UPPER(?) ORDER BY id DESC LIMIT ?",
            (str(canonical), int(limit)),
        )
        rows = cur.fetchall() or []
        conn.close()
    except Exception:
        rows = []

    stats = {}
    for model, result in rows:
        name = str(model or "UNKNOWN")
        bucket = stats.setdefault(name, {"wins": 0, "losses": 0})
        if str(result or "").upper() in {"WIN", "TP_HIT", "PROFIT"}:
            bucket["wins"] += 1
        else:
            bucket["losses"] += 1
    return stats


def _journal_rows_for_symbol(symbol: str | None, limit: int = 50):
    canonical = _canonical_symbol(symbol)
    rows = []
    try:
        conn = sqlite3.connect("ai_trade_journal.db")
        cur = conn.cursor()
        if canonical:
            cur.execute(
                "SELECT timestamp, symbol, model, result, r_multiple, pnl, phase FROM trades WHERE UPPER(symbol)=UPPER(?) ORDER BY id DESC LIMIT ?",
                (str(canonical), int(limit)),
            )
        else:
            cur.execute(
                "SELECT timestamp, symbol, model, result, r_multiple, pnl, phase FROM trades ORDER BY id DESC LIMIT ?",
                (int(limit),),
            )
        rows = cur.fetchall() or []
        conn.close()
    except Exception:
        rows = []
    return rows


def _multi_symbol_row(symbol: str):
    market_data = _run_with_timeout(1.5, lambda: runner.get_market_data(symbol) or {}, {})
    latest_trade = _latest_trade_for_symbol(symbol) or {}
    basis = _normalize_basis_snapshot(runner.get_basis_snapshot(symbol))
    resolver = runner.contract_resolver.snapshot(symbol)
    behavior = runner.prop_behavior_snapshot(symbol)
    return {
        "symbol": symbol,
        "market": {
            "htf_bias": market_data.get("trend", "--"),
            "ltf_structure": "TREND" if market_data.get("trend") in {"UP", "DOWN"} else "RANGE",
            "news_state": "HALT" if runner.state.news_halt else "NORMAL",
        },
        "model": {
            "active_model": latest_trade.get("model", "--"),
            "confidence": _float_value(latest_trade.get("confidence"), 0.0),
        },
        "risk": {
            "risk_percent": prop_engine.get_phase_risk() * 100.0,
            "phase": prop_engine.phase,
        },
        "prop_behavior": behavior,
        "basis": basis,
        "resolver": {
            "status": resolver.get("last_status", "UNRESOLVED"),
            "watch_only": runner.resolver_watch_snapshot(symbol).get("watch_only", False),
        },
        "execution_halted": str(runner.execution.execution_health().get("execution_status", "OK")).upper() == "HALTED",
    }


def market_context(symbol: str):
    behavior = runner.prop_behavior_snapshot(symbol)
    position = runner.state.open_positions.get(symbol)
    market_data = _run_with_timeout(1.0, lambda: runner.get_market_data(symbol) or {}, {})
    return {
        "risk_percent": prop_engine.get_phase_risk(),
        "confidence": 0.0,
        "position": position,
        "spot_fidelity": {
            "pricing_source": (market_data or {}).get("pricing_source"),
        },
        "session": prop_engine.get_session(),
        "volatility_mode": prop_engine.volatility_mode,
        "prop_behavior": behavior,
    }


def _prime_symbol_runtime(symbol: str):
    canonical_symbol = _canonical_symbol(symbol) or str(symbol)
    _run_with_timeout(1.5, lambda: runner.get_market_data(canonical_symbol) or {}, {})

    behavior = runner.prop_behavior_snapshot(canonical_symbol)
    if str((behavior or {}).get("mode") or "").upper() == "UNINITIALIZED":
        simulated = prop_engine.compute_auto_behavior_profile(
            equity=float(runner.state.balance),
            daily_loss=float(runner.state.daily_loss),
            drawdown=float(runner.capital.get_drawdown(runner.state.balance)),
            news_mode=("HALT" if bool(runner.state.news_halt) else "NORMAL"),
            phase=str(prop_engine.phase),
            volatility_mode=str(prop_engine.volatility_mode),
            trading_enabled=bool(prop_engine.trading_enabled),
            cooldown_active=bool(prop_engine.cooldown_active),
        )
        behavior = runner.apply_behavior_override(canonical_symbol, simulated)
        runner.last_prop_behavior[canonical_symbol] = behavior

    return canonical_symbol


def _normalize_basis_snapshot(snapshot: dict | None):
    row = dict(snapshot or {})
    status = str(row.get("status") or "UNINITIALIZED").upper()
    if status == "UNINITIALIZED":
        row["status"] = "NO_FEED"
        row["guard_reason"] = row.get("guard_reason") or "Awaiting feed data"
        row["safety_block"] = bool(row.get("safety_block", False))
        row["smooth_bps"] = row.get("smooth_bps") if row.get("smooth_bps") is not None else 0.0
        row["zscore"] = row.get("zscore") if row.get("zscore") is not None else 0.0
    return row


def _mentor_model_data(symbol: str, market_data: dict):
    latest_trade = _latest_trade_for_symbol(symbol) or {}
    model_name = latest_trade.get("model") or "MONITOR"
    confidence = round(_float_value(latest_trade.get("confidence"), 0.0), 2)
    trend = str((market_data or {}).get("trend") or "").upper()
    reason = latest_trade.get("entry_reason") or (
        "Trend alignment" if trend in {"UP", "DOWN"} else "Range conditions"
    )
    rr = latest_trade.get("rr") or "1.5:1"
    invalid_if = latest_trade.get("invalid_if") or "Structure breaks against trade direction"
    entry_logic = latest_trade.get("entry_reason") or "AI-ranked signal selection"
    if str(model_name or "").upper() in mentor_engine.disabled_models:
        reason = f"{reason} | Model currently disabled"
    return {
        "name": model_name,
        "confidence": confidence,
        "reason": reason,
        "rr": rr,
        "invalid_if": invalid_if,
        "entry_logic": entry_logic,
    }


def _trade_row_to_dict(row):
    if isinstance(row, dict):
        return dict(row)
    if isinstance(row, (list, tuple)):
        values = list(row)
        return {
            "time": values[0] if len(values) > 0 else None,
            "model": values[1] if len(values) > 1 else None,
            "result": values[2] if len(values) > 2 else None,
            "r_multiple": values[3] if len(values) > 3 else None,
            "pnl": values[4] if len(values) > 4 else None,
            "phase": values[5] if len(values) > 5 else None,
        }
    return {}


def _mentor_risk_data():
    base_size = max(1.0, float(prop_engine.config.account_size))
    daily_guard_pct = float(getattr(prop_engine.config, "internal_daily_guard_pct", 0.045) or 0.045)
    daily_guard_amount = max(1.0, base_size * daily_guard_pct)
    daily_buffer = max(0.0, daily_guard_amount - float(runner.state.daily_loss))
    static_floor = float(getattr(prop_engine, "static_floor", 0.0))
    cooldown = "ON" if bool(getattr(prop_engine, "cooldown_active", False)) else "OFF"
    return {
        "risk_percent": round(float(prop_engine.get_phase_risk()) * 100.0, 2),
        "daily_buffer": round((daily_buffer / base_size) * 100.0, 2),
        "static_floor": round(static_floor, 2),
        "cooldown": cooldown,
    }


def _mentor_phase_data(symbol: str):
    journal_rows = recent_trades(limit=50)
    top_rows = list(journal_rows or [])[:5]

    formatted_trades = []
    for raw_row in top_rows:
        row = _trade_row_to_dict(raw_row)
        time_raw = row.get("time") or row.get("timestamp")
        if isinstance(time_raw, (int, float)):
            trade_time = datetime.fromtimestamp(float(time_raw), tz=timezone.utc).isoformat()
        else:
            trade_time = str(time_raw or "--")
        formatted_trades.append(
            {
                "time": trade_time,
                "model": row.get("model") or "--",
                "result": row.get("result") or row.get("status") or "--",
                "r_multiple": row.get("r_multiple") if row.get("r_multiple") is not None else row.get("rr"),
                "pnl": row.get("pnl") if row.get("pnl") is not None else row.get("profit"),
            }
        )

    latest = _trade_row_to_dict(top_rows[0]) if top_rows else {}
    exit_data = {
        "last_result": latest.get("result") or latest.get("status") or "--",
        "reason": mentor_engine.infer_exit_reason(
            latest,
            bool(runner.state.news_halt),
            str(prop_engine.volatility_mode),
        ) if latest else "--",
    }

    account_size = float(prop_engine.config.account_size)
    current_balance = float(runner.state.balance)
    target_pct = float(getattr(prop_engine, "phase_target_pct", 0.08)) if str(prop_engine.phase).upper() == "PHASE1" else float(getattr(prop_engine, "phase2_target_pct", 0.05))
    phase_target = account_size * (1.0 + target_pct)
    target_left = max(0.0, phase_target - current_balance)
    drawdown_remaining = max(0.0, current_balance - float(getattr(prop_engine, "static_floor", 0.0)))

    phase_data = {
        "phase": prop_engine.phase,
        "prop_audit": {
            "profitable_days_completed": int(getattr(prop_engine, "profitable_days", 0)),
            "target_left": round(target_left, 2),
            "drawdown_remaining": round(drawdown_remaining, 2),
        },
        "last_trades": formatted_trades,
        "model_stats": model_stats(),
    }
    return phase_data, exit_data


_apply_dynamic_prop_runtime(send_telegram_update=False)
runner.prop_status_callback = _runner_prop_status_callback


@asynccontextmanager
async def lifespan(app: FastAPI):
    feed_health = runner.feed.health()
    init_journal()
    runner.execution.set_reconnect_handler(_execution_reconnect_handler)
    if EXECUTION_BROWSER_AUTO_ATTACH:
        _connect_execution_browser(force=False)
    _start_journal_dayend_worker()
    _run_with_timeout(2.0, lambda: runner.warmup_contracts(force_probe=False, max_candidates=1, max_probe_seconds=0.8), {})
    if DATABENTO_STRICT_STARTUP and not feed_health.get("configured"):
        raise RuntimeError("DATABENTO_STRICT_STARTUP enabled but DATABENTO_API_KEY is missing")
    try:
        yield
    finally:
        _stop_journal_dayend_worker()
        try:
            runner.feed.stop_live()
        except Exception:
            pass
        global runtime_browser_engine
        if runtime_browser_engine is not None:
            try:
                runtime_browser_engine.close()
            except Exception:
                pass
            runtime_browser_engine = None
        runner.execution.set_page(None)


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8080",
        "http://localhost:8080",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(build_admin_router(runner, prop_engine, admin_token=ADMIN_API_TOKEN, default_role=ADMIN_DEFAULT_ROLE))
app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


@app.get("/")
def dashboard_page():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/admin")
def admin_control_panel_page():
    return FileResponse(str(FRONTEND_DIR / "admin.html"))


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/status")
def status():
    capital_data = runner.capital.data
    return {
        "balance": runner.state.balance,
        "daily_loss": runner.state.daily_loss,
        "phase": runner.state.phase,
        "news_halt": runner.state.news_halt,
        "capital": {
            "equity_peak": capital_data.get("equity_peak"),
            "max_drawdown": capital_data.get("max_drawdown"),
            "current_drawdown": runner.capital.get_drawdown(runner.state.balance),
            "reduce_risk": runner.state.reduce_risk,
        },
        "next_news": [
            {"title": e["title"], "currency": e["currency"], "time": e["time"].isoformat()}
            for e in runner.governance.news.events[:5]
        ],
        "open_positions": runner.positions.get_positions(),
        "feed": runner.feed.health(),
        "basis": runner.basis_summary(),
        "resolver_watch": runner.resolver_watch_summary(),
        "reconciliation": runner.last_reconciliation,
        "equity_verification": runner.last_equity_verification,
        "prop_auto_behavior": runner.prop_behavior_summary(),
        "prop_auto_behavior_overrides": runner.behavior_override_summary(),
        "strict_startup": DATABENTO_STRICT_STARTUP,
    }


@app.get("/status/feed")
def feed_status():
    return runner.feed_status()


@app.get("/status/reconciliation")
def reconciliation_status():
    return runner.reconcile_positions()


@app.get("/status/equity_verification")
def equity_verification_status():
    return runner.verify_broker_equity()


@app.get("/status/execution")
def execution_status():
    execution_health = runner.execution.execution_health()
    broker_quote = runner.execution.broker_quote_snapshot(expected_symbols=["XAUUSD", "XAU/USD"]) or {}
    selector_profile = selector_profile_status()
    connection_status = execution_connection_status()
    configured = bool(connection_status.get("cdp_configured") or connection_status.get("user_data_dir_configured"))
    connected = bool(connection_status.get("connected"))
    raw_execution_status = str(execution_health.get("execution_status", "OK")).upper()
    if not configured:
        effective_execution_status = "NOT_CONFIGURED"
    elif not connected and raw_execution_status == "OK":
        effective_execution_status = "DISCONNECTED"
    else:
        effective_execution_status = raw_execution_status

    status_reason = None
    if effective_execution_status == "NOT_CONFIGURED":
        status_reason = "Set EXECUTION_BROWSER_CDP_URL or EXECUTION_BROWSER_USER_DATA_DIR to attach Playwright"
    elif effective_execution_status == "DISCONNECTED":
        status_reason = "Playwright browser is configured but not currently attached"

    heartbeat = int(execution_health.get("last_browser_heartbeat") or 0)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    heartbeat_age = (now_ts - heartbeat) if heartbeat > 0 else None
    return {
        "connected": connected,
        "order_in_progress": runner.execution.playwright.order_in_progress,
        "last_trade_time": runner.execution.playwright.last_trade_time,
        "last_error": runner.execution.playwright.last_error,
        "execution_status": effective_execution_status,
        "execution_status_raw": raw_execution_status,
        "status_reason": status_reason,
        "execution_halted_at": execution_health.get("halted_at"),
        "max_slippage": execution_health.get("max_slippage"),
        "execution_timeout": execution_health.get("execution_timeout"),
        "reconnect_attempts": execution_health.get("reconnect_attempts", 0),
        "last_reconnect_attempt": execution_health.get("last_reconnect_attempt"),
        "selector_halted": bool(execution_health.get("selector_halted")),
        "selector_last_reason": execution_health.get("selector_last_reason"),
        "selector_failure_count": execution_health.get("selector_failure_count", 0),
        "selector_failure_limit": execution_health.get("selector_failure_limit", 0),
        "browser_heartbeat": heartbeat,
        "browser_heartbeat_status": "STALE" if (heartbeat_age is not None and heartbeat_age > 20) else ("OK" if heartbeat else "UNKNOWN"),
        "browser_heartbeat_age_seconds": heartbeat_age,
        "broker_quote": broker_quote,
        "selector_profile": selector_profile,
        "connection": connection_status,
        "reconnect": _execution_reconnect_snapshot(),
    }


@app.post("/execution/reconnect")
def execution_reconnect(
    async_mode: bool = Query(default=True),
    force: bool = Query(default=False),
):
    if async_mode:
        if not force and runner.execution.playwright.page is not None:
            return {
                "status": "connected",
                "connected": True,
                "connection": execution_connection_status(),
                "reconnect": _execution_reconnect_snapshot(),
            }
        started = _trigger_execution_reconnect(force=force)
        snapshot = _execution_reconnect_snapshot()
        return {
            "status": "accepted" if started else "in_progress",
            "connected": bool(runner.execution.playwright.page),
            "connection": execution_connection_status(),
            "reconnect": snapshot,
        }

    result = _connect_execution_browser(force=force)
    return {
        "status": result.get("status"),
        "connected": bool(result.get("connected")),
        "mode": result.get("mode"),
        "reason": result.get("reason"),
        "connection": execution_connection_status(),
        "reconnect": _execution_reconnect_snapshot(),
    }


@app.post("/execution/recover")
def execution_recover(force_reconnect: bool = Query(default=False)):
    recovery = runner.execution.playwright.recover_from_selector_failure(force_reconnect=force_reconnect)
    return {
        "status": "ok" if recovery.get("ok") else "failed",
        "recovery": recovery,
        "execution": runner.execution.execution_health(),
        "connection": execution_connection_status(),
    }


@app.get("/prop_status")
def prop_status():
    dynamic_state = dynamic_prop_engine.snapshot(phase=prop_engine.phase)
    primary_profile = dynamic_state.get("primary_profile", {})
    portfolio = dynamic_state.get("portfolio", {})
    balance = float(runner.state.balance)
    daily_loss = float(runner.state.daily_loss)
    account_size = float(prop_engine.config.account_size)
    daily_guard = max(1.0, account_size * float(prop_engine.config.internal_daily_guard_pct))
    overall_dd_limit = max(1.0, account_size * float(prop_engine.config.static_dd_pct))
    daily_dd_pct = (daily_loss / daily_guard) * 100.0
    overall_dd_pct = (max(0.0, account_size - balance) / overall_dd_limit) * 100.0
    remaining_room = max(0.0, balance - float(prop_engine.static_floor))
    lock_status = "LOCK_OK"
    if str(prop_engine.phase).upper() == "FUNDED":
        lock_status = "LOCK_BREACH" if balance < float(prop_engine.funded_lock_level) else "LOCK_OK"
    return {
        "phase": prop_engine.phase,
        "account_size": account_size,
        "trading_enabled": prop_engine.trading_enabled,
        "current_balance": balance,
        "current_equity": balance,
        "daily_drawdown_pct": round(daily_dd_pct, 2),
        "overall_drawdown_pct": round(overall_dd_pct, 2),
        "lock_rule_status": lock_status,
        "remaining_room_to_breach": round(remaining_room, 2),
        "static_floor": prop_engine.static_floor,
        "funded_lock_level": prop_engine.funded_lock_level,
        "funded_base_floor": prop_engine.funded_base_floor,
        "profitable_days": prop_engine.profitable_days,
        "daily_high": prop_engine.daily_high,
        "volatility_mode": prop_engine.volatility_mode,
        "volatility_session": prop_engine.get_session(),
        "phase_completion_status": prop_engine.phase_completion_status,
        "consecutive_losses": prop_engine.consecutive_losses,
        "cooldown_active": prop_engine.cooldown_active,
        "cooldown_end": prop_engine.cooldown_end.isoformat() if prop_engine.cooldown_end else None,
        "primary_account": dynamic_state.get("primary_account"),
        "active_accounts": dynamic_state.get("active_accounts", []),
        "profile_mode": primary_profile.get("mode", "STANDARD"),
        "risk_per_trade_pct": round(float(prop_engine.phase_limits(prop_engine.phase).get("risk_pct", 0.0)) * 100.0, 3),
        "daily_max_loss": primary_profile.get("daily_max_loss"),
        "total_max_loss": primary_profile.get("total_max_loss"),
        "phase1_target": primary_profile.get("phase1_target"),
        "phase2_target": primary_profile.get("phase2_target"),
        "strict_daily_dd_pct": portfolio.get("strict_daily_dd_pct"),
        "strict_max_dd_pct": portfolio.get("strict_max_dd_pct"),
    }


@app.get("/equity")
def equity_status():
    dynamic_state = dynamic_prop_engine.snapshot(phase=prop_engine.phase)
    primary_profile = dynamic_state.get("primary_profile", {})
    phase = prop_engine.phase
    if phase == "PHASE1":
        target = prop_engine.config.account_size * (1.0 + float(getattr(prop_engine, "phase_target_pct", 0.08)))
    elif phase == "PHASE2":
        target = prop_engine.config.account_size * (1.0 + float(getattr(prop_engine, "phase2_target_pct", 0.05)))
    else:
        target = prop_engine.funded_lock_level
    return {
        "equity": runner.state.balance,
        "base": prop_engine.config.account_size,
        "target": target,
        "static_floor": prop_engine.static_floor,
        "primary_account": dynamic_state.get("primary_account"),
        "mode": primary_profile.get("mode", "STANDARD"),
    }


@app.get("/admin/prop_engine/state")
def admin_prop_engine_state():
    return {
        "state": dynamic_prop_engine.snapshot(phase=prop_engine.phase),
        "supported_accounts": supported_account_keys(),
        "supported_modes": supported_modes(),
        "phase": prop_engine.phase,
    }


@app.get("/model_stats")
def model_stats(symbol: str | None = None):
    canonical = _canonical_symbol(symbol)
    if canonical:
        return _journal_model_stats_for_symbol(canonical)
    if prop_engine.model_stats:
        return prop_engine.model_stats
    if runner.state.model_performance:
        return runner.state.model_performance
    return _journal_model_stats()


@app.get("/news_severity")
def news_severity():
    now = datetime.now(timezone.utc)
    upcoming = None
    minutes_to_news = None
    for event in runner.governance.news.events:
        delta_minutes = (event["time"] - now).total_seconds() / 60.0
        if delta_minutes >= 0 and (upcoming is None or delta_minutes < minutes_to_news):
            upcoming = event
            minutes_to_news = delta_minutes
    return {
        "halt_active": runner.state.news_halt,
        "upcoming_title": upcoming.get("title") if upcoming else None,
        "upcoming_currency": upcoming.get("currency") if upcoming else None,
        "minutes_to_news": round(minutes_to_news, 1) if minutes_to_news is not None else None,
    }


@app.get("/system_health")
def system_health():
    feed = runner.feed.health()
    execution_health = runner.execution.execution_health()
    equity_verification = runner.verify_broker_equity()
    reconciliation = runner.reconcile_positions()
    playwright_ok = bool(runner.execution.playwright.page)
    databento_ok = bool(feed.get("healthy") or feed.get("configured"))
    governance_ok = bool(prop_engine.trading_enabled)
    execution_status = str(execution_health.get("execution_status", "OK") or "OK").upper()
    execution_ok = execution_status != "HALTED"
    equity_halt = bool(equity_verification.get("hard_halt"))
    reconciliation_halt = bool(reconciliation.get("hard_halt"))

    cpu_cores = int(os.cpu_count() or 0)
    cpu_load_1m = None
    try:
        cpu_load_1m = float(os.getloadavg()[0])
    except Exception:
        cpu_load_1m = None

    memory_used_pct = None
    try:
        mem_total = None
        mem_avail = None
        with Path("/proc/meminfo").open("r", encoding="utf-8") as fp:
            for line in fp:
                if line.startswith("MemTotal:"):
                    mem_total = float(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_avail = float(line.split()[1])
        if mem_total and mem_avail is not None and mem_total > 0:
            memory_used_pct = round(max(0.0, min(100.0, ((mem_total - mem_avail) / mem_total) * 100.0)), 2)
    except Exception:
        memory_used_pct = None

    disk_used_pct = None
    try:
        usage = shutil.disk_usage(str(BASE_DIR))
        if usage.total > 0:
            disk_used_pct = round((usage.used / usage.total) * 100.0, 2)
    except Exception:
        disk_used_pct = None

    uptime_seconds = int(max(0, time.time() - APP_STARTED_AT))

    issues = []
    if not playwright_ok:
        issues.append("PLAYWRIGHT_DOWN")
    if not databento_ok:
        issues.append("DATABENTO_DOWN")
    if not governance_ok:
        issues.append("GOVERNANCE_LOCKED")
    if not execution_ok:
        issues.append("EXECUTION_HALTED")
    if equity_halt:
        issues.append("EQUITY_HALT")
    if reconciliation_halt:
        issues.append("RECONCILIATION_HALT")
    if cpu_load_1m is not None and cpu_cores > 0 and cpu_load_1m > cpu_cores * 1.15:
        issues.append("CPU_LOAD_HIGH")
    if memory_used_pct is not None and memory_used_pct >= 90.0:
        issues.append("MEMORY_HIGH")
    if disk_used_pct is not None and disk_used_pct >= 90.0:
        issues.append("DISK_HIGH")

    score = 100
    score -= 15 if not playwright_ok else 0
    score -= 15 if not databento_ok else 0
    score -= 10 if not governance_ok else 0
    score -= 20 if not execution_ok else 0
    score -= 15 if equity_halt else 0
    score -= 10 if reconciliation_halt else 0
    score -= 8 if (cpu_load_1m is not None and cpu_cores > 0 and cpu_load_1m > cpu_cores * 1.15) else 0
    score -= 8 if (memory_used_pct is not None and memory_used_pct >= 90.0) else 0
    score -= 8 if (disk_used_pct is not None and disk_used_pct >= 90.0) else 0
    score = max(0, min(100, score))

    if score >= 85:
        state = "HEALTHY"
    elif score >= 65:
        state = "DEGRADED"
    else:
        state = "CRITICAL"

    return {
        "playwright": playwright_ok,
        "databento": databento_ok,
        "governance": governance_ok,
        "execution_status": execution_health.get("execution_status", "OK"),
        "execution_error": execution_health.get("last_error"),
        "equity_verification_status": equity_verification.get("status", "UNINITIALIZED"),
        "equity_verification_halt": equity_halt,
        "reconciliation_status": reconciliation.get("status", "UNINITIALIZED"),
        "reconciliation_halt": reconciliation_halt,
        "cpu_cores": cpu_cores,
        "cpu_load_1m": cpu_load_1m,
        "memory_used_pct": memory_used_pct,
        "disk_used_pct": disk_used_pct,
        "uptime_seconds": uptime_seconds,
        "issues": issues,
        "health_score": score,
        "health_state": state,
    }


@app.get("/volatility_status")
def volatility_status():
    return {"mode": prop_engine.volatility_mode, "session": prop_engine.get_session()}


@app.get("/journal")
def get_journal(symbol: str | None = None):
    return _journal_rows_for_symbol(symbol=symbol, limit=50)


@app.get("/dashboard/multi_symbol")
def dashboard_multi_symbol():
    rows = [_multi_symbol_row(symbol) for symbol in symbols]
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "feed": runner.feed.health(),
        "rows": rows,
    }


@app.get("/chart/data")
def chart_data(symbol: str, timeframe: str = "1m", limit: int = 300):
    feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
    canonical_symbol = feed_to_canonical.get(symbol, symbol)
    timeframe_minutes = _timeframe_to_minutes(timeframe)
    requested_limit = max(30, min(int(limit or 300), 1000))
    base_record_limit = max(300, min(4000, requested_limit * timeframe_minutes * 2))
    base_lookback_minutes = max(240, min(3 * 24 * 60, requested_limit * timeframe_minutes * 3))
    preferred_active_symbol = runner.SYMBOL_MAP.get(canonical_symbol, canonical_symbol)
    dataset = symbol_dataset(canonical_symbol)
    guard_snapshot = _chart_feed_guard_snapshot(canonical_symbol)
    guard_cooldown_active = bool(guard_snapshot.get("cooldown_active"))
    if timeframe_minutes >= 15:
        primary_record_limit = max(1200, min(base_record_limit, 2200 if guard_cooldown_active else 3000))
        primary_lookback_minutes = max(12 * 60, min(base_lookback_minutes, 18 * 60 if guard_cooldown_active else 24 * 60))
    else:
        primary_record_limit = max(600, min(base_record_limit, 1200 if guard_cooldown_active else 1800))
        primary_lookback_minutes = max(240, min(base_lookback_minutes, 12 * 60 if guard_cooldown_active else 24 * 60))
    resolved_active_symbol = runner.resolve_active_feed_symbol(canonical_symbol)

    root = str(preferred_active_symbol or canonical_symbol).split(".")[0]
    candidate_symbols = []
    if resolved_active_symbol:
        candidate_symbols.append(resolved_active_symbol)
    if str(preferred_active_symbol).endswith(".FUT"):
        candidate_symbols.extend([f"{root}.c.1", f"{root}.c.0"])
    candidate_symbols.extend(runner.candidate_feed_symbols(canonical_symbol, include_contracts=True))

    unique_candidates = []
    seen_candidates = set()
    for candidate in candidate_symbols:
        key = str(candidate or "").strip()
        if not key or key in seen_candidates:
            continue
        seen_candidates.add(key)
        unique_candidates.append(key)

    active_symbol, candles = str(resolved_active_symbol or preferred_active_symbol), []
    feed_error = runner.feed.last_error or guard_snapshot.get("last_reason")

    if timeframe_minutes >= 15:
        prefetch_active, prefetch_candles = _run_with_timeout(
            10.0,
            lambda: runner.get_futures_candles(
                canonical_symbol,
                lookback_minutes=max(primary_lookback_minutes, 12 * 60),
                record_limit=max(primary_record_limit, 1800),
                prefer_cached=True,
            ),
            (active_symbol, []),
        )
        if prefetch_candles:
            active_symbol = prefetch_active
            candles = prefetch_candles
            feed_error = None

    attempted_candidates = []
    max_primary_candidates = 2 if timeframe_minutes >= 15 else 3
    for index, candidate in enumerate(unique_candidates[:max_primary_candidates]):
        if candles:
            break
        attempted_candidates.append(candidate)
        if timeframe_minutes >= 15:
            candidate_timeout = 5.5 if index == 0 else 4.5
        else:
            candidate_timeout = 8.0 if index == 0 else 7.0
        candidate_candles = _run_with_timeout(
            candidate_timeout,
            lambda c=candidate: runner.feed.get_ohlcv(
                dataset=dataset,
                symbol=c,
                lookback_minutes=primary_lookback_minutes,
                record_limit=primary_record_limit,
            ),
            [],
        )
        if candidate_candles:
            active_symbol = candidate
            candles = candidate_candles
            feed_error = None
            try:
                runner.contract_resolver.set_active(
                    canonical_symbol,
                    candidate,
                    sample_count=len(candidate_candles),
                    candidates_tried=attempted_candidates,
                    ttl_seconds=4 * 3600,
                )
            except Exception:
                pass
            break

    if not candles:
        try:
            runner.contract_resolver.mark_miss(canonical_symbol, failed_symbol=active_symbol)
        except Exception:
            pass
        feed_error = runner.feed.last_error or feed_error
    try:
        runner.feed.ensure_live_subscription_async(dataset=dataset, symbol=active_symbol, stype_in="continuous")
        runner.feed.ensure_live_subscription_async(dataset=dataset, symbol=active_symbol, stype_in="parent")
    except Exception:
        pass
    live_quote = runner.feed.get_live_quote(dataset=dataset, symbol=active_symbol, stype_in="raw_symbol", max_age_seconds=20)
    candles = _aggregate_candles(candles or [], timeframe_minutes)
    candles = candles[-requested_limit:]

    min_candle_target = max(20, min(120, requested_limit // 2)) if timeframe_minutes >= 5 else max(40, min(180, requested_limit))
    if candles and len(candles) < min_candle_target:
        try:
            extended_history = _run_with_timeout(
                8.5,
                lambda: runner.feed.get_ohlcv(
                    dataset=dataset,
                    symbol=active_symbol,
                    lookback_minutes=max(base_lookback_minutes, 36 * 60 if timeframe_minutes >= 15 else 24 * 60),
                    record_limit=max(base_record_limit, 2600 if timeframe_minutes >= 15 else 1800),
                ),
                [],
            )
            extended_candles = _aggregate_candles(extended_history or [], timeframe_minutes)
            if len(extended_candles) > len(candles):
                candles = extended_candles[-requested_limit:]
        except Exception:
            pass

    data_source = "LIVE_HYBRID" if live_quote else "HISTORICAL"
    cache_key = f"{canonical_symbol}:{timeframe_minutes}"
    if candles:
        with CHART_CANDLE_CACHE_LOCK:
            CHART_CANDLE_CACHE[cache_key] = list(candles)
    if not candles:
        if timeframe_minutes > 1:
            try:
                resample_record_limit = max(500, min(4000, requested_limit * timeframe_minutes * 5))
                resample_lookback = max(720, min(3 * 24 * 60, requested_limit * timeframe_minutes * 8))
                _, base_1m = _run_with_timeout(
                    4.5,
                    lambda: runner.get_futures_candles(
                        canonical_symbol,
                        lookback_minutes=resample_lookback,
                        record_limit=resample_record_limit,
                        prefer_cached=False,
                    ),
                    (preferred_active_symbol, []),
                )
                resampled = _aggregate_candles(base_1m or [], timeframe_minutes)
                if resampled:
                    candles = resampled[-requested_limit:]
                    data_source = "HISTORICAL_RESAMPLED"
                    with CHART_CANDLE_CACHE_LOCK:
                        CHART_CANDLE_CACHE[cache_key] = list(candles)
            except Exception:
                pass

    if not candles:
        try:
            _, probed_history = _run_with_timeout(
                5.5,
                lambda: runner.get_futures_candles(
                    canonical_symbol,
                    lookback_minutes=max(base_lookback_minutes, 12 * 60),
                    record_limit=max(base_record_limit, requested_limit * timeframe_minutes * 3),
                    prefer_cached=False,
                ),
                (preferred_active_symbol, []),
            )
            probed_candles = _aggregate_candles(probed_history or [], timeframe_minutes)
            if probed_candles:
                candles = probed_candles[-requested_limit:]
                data_source = "HISTORICAL_PROBED"
                with CHART_CANDLE_CACHE_LOCK:
                    CHART_CANDLE_CACHE[cache_key] = list(candles)
        except Exception:
            pass

    if not candles:
        cached_rows = []
        with CHART_CANDLE_CACHE_LOCK:
            cached_rows = list(CHART_CANDLE_CACHE.get(cache_key, []) or [])
        if cached_rows:
            candles = cached_rows[-requested_limit:]
            data_source = "CACHE_FALLBACK_AUTH" if str(feed_error or "").lower().find("auth") >= 0 else "CACHE_FALLBACK"
        elif timeframe_minutes == 1:
            try:
                _, long_history = _run_with_timeout(
                    4.5,
                    lambda: runner.get_futures_candles(
                        canonical_symbol,
                        lookback_minutes=3 * 24 * 60,
                        record_limit=4000,
                        prefer_cached=False,
                    ),
                    (preferred_active_symbol, []),
                )
                long_candles = _aggregate_candles(long_history or [], timeframe_minutes)
                if long_candles:
                    candles = long_candles[-requested_limit:]
                    data_source = "HISTORICAL_EXTENDED"
                    with CHART_CANDLE_CACHE_LOCK:
                        CHART_CANDLE_CACHE[cache_key] = list(candles)
            except Exception:
                pass

    if not candles:
        recent_candidates = []
        for candidate in [active_symbol, resolved_active_symbol, f"{root}.c.1", f"{root}.c.0", preferred_active_symbol]:
            key = str(candidate or "").strip()
            if key and key not in recent_candidates:
                recent_candidates.append(key)
        for index, candidate in enumerate(recent_candidates[:3]):
            recent_1m = _run_with_timeout(
                6.0 if index == 0 else 5.0,
                lambda c=candidate: runner.feed.get_ohlcv(
                    dataset=dataset,
                    symbol=c,
                    lookback_minutes=max(12 * 60, min(base_lookback_minutes, 24 * 60)),
                    record_limit=max(1200, min(base_record_limit, 2200)),
                ),
                [],
            )
            recent_agg = _aggregate_candles(recent_1m or [], timeframe_minutes)
            if recent_agg:
                candles = recent_agg[-requested_limit:]
                data_source = "HISTORICAL_RECENT"
                active_symbol = candidate
                with CHART_CANDLE_CACHE_LOCK:
                    CHART_CANDLE_CACHE[cache_key] = list(candles)
                break

    if not candles:
            fallback_base_price = 2325.0
            with CHART_CANDLE_CACHE_LOCK:
                for cache_symbol_key, cache_rows in CHART_CANDLE_CACHE.items():
                    if not str(cache_symbol_key).startswith(f"{canonical_symbol}:"):
                        continue
                    if not cache_rows:
                        continue
                    try:
                        candidate_price = float((cache_rows[-1] or {}).get("close"))
                        if candidate_price > 0:
                            fallback_base_price = candidate_price
                            break
                    except Exception:
                        continue
            data_source = "SYNTHETIC_FALLBACK_AUTH" if str(feed_error or "").lower().find("auth") >= 0 else "SYNTHETIC_FALLBACK"
            base_synthetic = _synthetic_candles(
                limit=max(120, min(base_record_limit, 2000)),
                base_price=fallback_base_price,
            )
            candles = _aggregate_candles(base_synthetic, timeframe_minutes)[-requested_limit:]

    if live_quote and candles:
        try:
            live_px = float((live_quote or {}).get("price"))
            ref_close = float(candles[-1].get("close"))
            if ref_close <= 0 or live_px <= 0 or abs(live_px - ref_close) / ref_close > 0.05:
                live_quote = None
        except Exception:
            live_quote = None

    if str(data_source).startswith("SYNTHETIC_FALLBACK") or str(data_source).startswith("CACHE_FALLBACK"):
        live_quote = None
    overlays = _chart_overlays(candles)
    trades = []
    try:
        if getattr(getattr(runner, "signal_manager", None), "orderflow_engine", None):
            trades = _run_with_timeout(
                1.8,
                lambda: runner.signal_manager.orderflow_engine.get_recent_trades(
                    dataset=dataset,
                    symbol=active_symbol,
                ),
                [],
            )
    except Exception:
        trades = []

    time_sales_rows = time_sales_engine.build(trades=trades, candles=candles, limit=40)
    delta_payload = delta_engine.build(
        time_sales_rows=time_sales_rows,
        candles=candles,
        timeframe_minutes=timeframe_minutes,
        limit=max(32, requested_limit),
    )
    dom_payload = dom_engine.build(
        time_sales_rows=time_sales_rows,
        candles=candles,
        depth=12,
    )
    orderflow_summary = orderflow_summary_engine.build(
        delta_summary=delta_payload.get("summary", {}),
        dom_summary=dom_payload.get("summary", {}),
        iceberg_rows=(overlays or {}).get("iceberg", []),
        time_sales_rows=time_sales_rows,
        regime_mode=getattr(prop_engine, "active_mode", "STANDARD"),
        volatility_mode=getattr(prop_engine, "volatility_mode", "NORMAL"),
    )
    volume = [
        {
            "time": int(c.get("time", 0)),
            "value": _float_value(c.get("volume", 0.0)),
            "color": "#22c55e66" if _float_value(c.get("close")) >= _float_value(c.get("open")) else "#ef444466",
        }
        for c in candles
    ]
    payload = {
        "candles": candles,
        "volume": volume,
        "overlays": overlays,
        "signals": [],
        "meta": _chart_meta(canonical_symbol),
    }
    payload["meta"]["timeframe"] = str(timeframe or "1m")
    payload["meta"]["timeframe_minutes"] = timeframe_minutes
    payload["meta"]["data_source"] = data_source
    payload["meta"]["requested_symbol"] = str(symbol or canonical_symbol)
    payload["meta"]["canonical_symbol"] = canonical_symbol
    payload["meta"]["active_feed_symbol"] = active_symbol
    payload["meta"]["feed_last_error"] = runner.feed.last_error
    payload["meta"]["live_quote"] = live_quote
    payload["meta"]["live_last_error"] = runner.feed.live_last_error
    payload["meta"]["live_started"] = bool(getattr(runner.feed, "live_started", False))
    payload["meta"]["time_sales"] = time_sales_rows
    payload["meta"]["delta_summary"] = delta_payload.get("summary", {})
    payload["meta"]["delta_candles"] = delta_payload.get("candles", [])
    payload["meta"]["dom_ladder"] = dom_payload.get("levels", [])
    payload["meta"]["dom_summary"] = dom_payload.get("summary", {})
    payload["meta"]["orderflow_summary"] = orderflow_summary
    payload["overlays"]["cumulative_delta"] = [
        {"time": int(row.get("time", 0)), "value": float(row.get("cum_delta", 0.0))}
        for row in (delta_payload.get("candles", []) or [])
    ]

    degraded_data = str(data_source).startswith("SYNTHETIC_FALLBACK") or str(data_source).startswith("CACHE_FALLBACK")
    degraded_reason = str(feed_error or runner.feed.last_error or runner.feed.live_last_error or "")

    if degraded_data:
        _chart_feed_guard_miss(canonical_symbol, reason=degraded_reason)
    else:
        _chart_feed_guard_success(canonical_symbol)

    updated_guard = _chart_feed_guard_snapshot(canonical_symbol)
    payload["meta"]["degraded_data"] = degraded_data
    payload["meta"]["degraded_reason"] = degraded_reason or None
    payload["meta"]["feed_guard"] = updated_guard
    payload["meta"]["feed_cooldown_active"] = bool(updated_guard.get("cooldown_active"))
    payload["meta"]["feed_cooldown_seconds"] = float(updated_guard.get("cooldown_seconds", 0.0) or 0.0)
    payload["meta"]["feed_miss_count"] = int(updated_guard.get("miss_count", 0) or 0)
    if degraded_data:
        payload["meta"]["degraded_message"] = (
            f"Degraded feed: {data_source}"
            + (f" · cooldown {payload['meta']['feed_cooldown_seconds']:.1f}s" if payload["meta"]["feed_cooldown_active"] else "")
        )
    else:
        payload["meta"]["degraded_message"] = None
    return payload


@app.get("/market/time_sales")
def market_time_sales(symbol: str, limit: int = 40):
    feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
    canonical_symbol = feed_to_canonical.get(symbol, symbol)
    dataset = symbol_dataset(canonical_symbol)
    active_symbol = runner.resolve_active_feed_symbol(canonical_symbol) or runner.SYMBOL_MAP.get(canonical_symbol, canonical_symbol)

    trades = []
    try:
        if getattr(getattr(runner, "signal_manager", None), "orderflow_engine", None):
            trades = _run_with_timeout(
                2.2,
                lambda: runner.signal_manager.orderflow_engine.get_recent_trades(
                    dataset=dataset,
                    symbol=active_symbol,
                ),
                [],
            )
    except Exception:
        trades = []

    candles = []
    try:
        _, candles = _run_with_timeout(
            2.2,
            lambda: runner.get_futures_candles(
                canonical_symbol,
                lookback_minutes=180,
                record_limit=max(120, min(500, int(limit or 40) * 6)),
                prefer_cached=True,
            ),
            (active_symbol, []),
        )
    except Exception:
        candles = []

    rows = time_sales_engine.build(trades=trades, candles=candles, limit=max(5, min(120, int(limit or 40))))
    return {
        "status": "ok",
        "symbol": canonical_symbol,
        "active_feed_symbol": active_symbol,
        "dataset": dataset,
        "time_sales": rows,
        "source": "TRADES" if trades else "CANDLE_FALLBACK",
    }


@app.get("/market/delta")
def market_delta(symbol: str, timeframe: str = "1m", limit: int = 120):
    feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
    canonical_symbol = feed_to_canonical.get(symbol, symbol)
    dataset = symbol_dataset(canonical_symbol)
    timeframe_minutes = _timeframe_to_minutes(timeframe)
    active_symbol = runner.resolve_active_feed_symbol(canonical_symbol) or runner.SYMBOL_MAP.get(canonical_symbol, canonical_symbol)

    trades = []
    try:
        if getattr(getattr(runner, "signal_manager", None), "orderflow_engine", None):
            trades = _run_with_timeout(
                2.2,
                lambda: runner.signal_manager.orderflow_engine.get_recent_trades(
                    dataset=dataset,
                    symbol=active_symbol,
                ),
                [],
            )
    except Exception:
        trades = []

    candles = []
    try:
        _, candles = _run_with_timeout(
            2.4,
            lambda: runner.get_futures_candles(
                canonical_symbol,
                lookback_minutes=max(180, min(72 * 60, int(limit or 120) * timeframe_minutes * 2)),
                record_limit=max(200, min(1600, int(limit or 120) * timeframe_minutes * 3)),
                prefer_cached=True,
            ),
            (active_symbol, []),
        )
    except Exception:
        candles = []

    tape = time_sales_engine.build(trades=trades, candles=candles, limit=max(20, min(200, int(limit or 120))))
    delta_payload = delta_engine.build(
        time_sales_rows=tape,
        candles=candles,
        timeframe_minutes=timeframe_minutes,
        limit=max(20, min(400, int(limit or 120))),
    )

    return {
        "status": "ok",
        "symbol": canonical_symbol,
        "active_feed_symbol": active_symbol,
        "dataset": dataset,
        "timeframe": timeframe,
        "timeframe_minutes": timeframe_minutes,
        "summary": delta_payload.get("summary", {}),
        "candles": delta_payload.get("candles", []),
    }


@app.get("/market/dom")
def market_dom(symbol: str, timeframe: str = "1m", depth: int = 12, limit: int = 120):
    feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
    canonical_symbol = feed_to_canonical.get(symbol, symbol)
    dataset = symbol_dataset(canonical_symbol)
    timeframe_minutes = _timeframe_to_minutes(timeframe)
    active_symbol = runner.resolve_active_feed_symbol(canonical_symbol) or runner.SYMBOL_MAP.get(canonical_symbol, canonical_symbol)

    trades = []
    try:
        if getattr(getattr(runner, "signal_manager", None), "orderflow_engine", None):
            trades = _run_with_timeout(
                2.0,
                lambda: runner.signal_manager.orderflow_engine.get_recent_trades(
                    dataset=dataset,
                    symbol=active_symbol,
                ),
                [],
            )
    except Exception:
        trades = []

    candles = []
    try:
        _, candles = _run_with_timeout(
            2.3,
            lambda: runner.get_futures_candles(
                canonical_symbol,
                lookback_minutes=max(180, min(72 * 60, int(limit or 120) * timeframe_minutes * 2)),
                record_limit=max(220, min(1800, int(limit or 120) * timeframe_minutes * 3)),
                prefer_cached=True,
            ),
            (active_symbol, []),
        )
    except Exception:
        candles = []

    tape = time_sales_engine.build(trades=trades, candles=candles, limit=max(20, min(220, int(limit or 120))))
    dom_payload = dom_engine.build(
        time_sales_rows=tape,
        candles=candles,
        depth=max(6, min(40, int(depth or 12))),
    )

    return {
        "status": "ok",
        "symbol": canonical_symbol,
        "active_feed_symbol": active_symbol,
        "dataset": dataset,
        "timeframe": timeframe,
        "timeframe_minutes": timeframe_minutes,
        "depth": max(6, min(40, int(depth or 12))),
        "summary": dom_payload.get("summary", {}),
        "levels": dom_payload.get("levels", []),
    }


@app.get("/market/orderflow_summary")
def market_orderflow_summary(symbol: str, timeframe: str = "1m", limit: int = 120):
    feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
    canonical_symbol = feed_to_canonical.get(symbol, symbol)
    timeframe_minutes = _timeframe_to_minutes(timeframe)

    chart_payload = chart_data(symbol=symbol, timeframe=timeframe, limit=max(60, min(400, int(limit or 120))))
    overlays = dict(chart_payload.get("overlays") or {})
    meta = dict(chart_payload.get("meta") or {})

    summary = orderflow_summary_engine.build(
        delta_summary=meta.get("delta_summary", {}),
        dom_summary=meta.get("dom_summary", {}),
        iceberg_rows=overlays.get("iceberg", []),
        time_sales_rows=meta.get("time_sales", []),
        regime_mode=getattr(prop_engine, "active_mode", "STANDARD"),
        volatility_mode=getattr(prop_engine, "volatility_mode", "NORMAL"),
    )

    return {
        "status": "ok",
        "symbol": canonical_symbol,
        "timeframe": timeframe,
        "timeframe_minutes": timeframe_minutes,
        "summary": summary,
        "delta_summary": meta.get("delta_summary", {}),
        "dom_summary": meta.get("dom_summary", {}),
        "iceberg": overlays.get("iceberg", []),
    }


@app.get("/market/basis")
def market_basis(symbol: str, refresh: bool = False):
    feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
    canonical_symbol = feed_to_canonical.get(symbol, symbol)
    if refresh:
        _prime_symbol_runtime(canonical_symbol)
    snapshot = runner.get_basis_snapshot(canonical_symbol)
    if str(snapshot.get("status") or "").upper() == "UNINITIALIZED":
        _prime_symbol_runtime(canonical_symbol)
        snapshot = runner.get_basis_snapshot(canonical_symbol)
    return _normalize_basis_snapshot(snapshot)


@app.get("/market/contracts")
def market_contracts(symbol: str):
    feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
    canonical_symbol = feed_to_canonical.get(symbol, symbol)
    active = runner.resolve_active_feed_symbol(canonical_symbol)
    resolver = runner.contract_resolver.snapshot(canonical_symbol)
    return {
        "symbol": canonical_symbol,
        "active_symbol": active,
        "resolver": resolver,
    }


@app.post("/market/contracts/warmup")
def warmup_contracts(
    force_refresh: bool = Query(default=False),
    max_candidates: int = Query(default=2, ge=1, le=6),
    max_probe_seconds: float = Query(default=2.0, ge=0.5, le=10.0),
):
    return runner.warmup_contracts(force_probe=force_refresh, max_candidates=max_candidates, max_probe_seconds=max_probe_seconds)


@app.get("/market/symbol_probe")
def market_symbol_probe(
    symbol: str,
    lookback_minutes: int = Query(default=240, ge=60, le=4320),
    include_contracts: bool = Query(default=False),
    max_candidates: int = Query(default=4, ge=1, le=12),
):
    feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
    canonical_symbol = feed_to_canonical.get(symbol, symbol)
    candidates = runner.candidate_feed_symbols(canonical_symbol, include_contracts=include_contracts)[:max_candidates]
    dataset = runner.dataset
    out = []
    for candidate in candidates:
        candles = runner.feed.get_ohlcv(dataset=dataset, symbol=candidate, lookback_minutes=lookback_minutes, record_limit=600)
        out.append({"candidate": candidate, "count": len(candles or [])})
    return {"symbol": canonical_symbol, "dataset": dataset, "results": out}


@app.get("/market/context")
def market_context_endpoint(symbol: str):
    feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
    canonical_symbol = feed_to_canonical.get(symbol, symbol)
    _prime_symbol_runtime(canonical_symbol)
    basis_snapshot = _normalize_basis_snapshot(runner.get_basis_snapshot(canonical_symbol))
    resolver_snapshot = runner.contract_resolver.snapshot(canonical_symbol)
    return {
        "symbol": canonical_symbol,
        "basis_policy": runner.basis_safety_policy(canonical_symbol, basis_snapshot=basis_snapshot, resolver_snapshot=resolver_snapshot),
        "resolver_watch": runner.resolver_watch_snapshot(canonical_symbol),
        "prop_behavior": runner.prop_behavior_snapshot(canonical_symbol),
    }


@app.get("/mentor/context")
def mentor_context(symbol: str = "GC.FUT"):
    feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
    canonical_symbol = feed_to_canonical.get(symbol, symbol)

    market_data_raw = _run_with_timeout(1.5, lambda: runner.get_market_data(canonical_symbol) or {}, {})
    candles = list((market_data_raw or {}).get("candles") or [])
    last_candle = candles[-1] if candles else {}
    last_open = _float_value((last_candle or {}).get("open"), 0.0)
    last_high = _float_value((last_candle or {}).get("high"), 0.0)
    last_low = _float_value((last_candle or {}).get("low"), 0.0)
    last_close = _float_value((last_candle or {}).get("close"), 0.0)
    range_points = max(0.0, last_high - last_low)
    midpoint = (last_high + last_low) / 2.0 if last_high > 0.0 or last_low > 0.0 else 0.0
    htf_bias = mentor_engine.derive_htf_bias(candles)
    ltf_structure = mentor_engine.derive_ltf_structure(candles)
    iceberg = mentor_engine.derive_iceberg(candles)
    overlays = _chart_overlays(candles)
    gann_lines = list((overlays or {}).get("gann_lines") or [])
    astro_markers = list((overlays or {}).get("astro_markers") or [])
    time_sales_rows = time_sales_engine.build(trades=[], candles=candles, limit=40)
    delta_payload = delta_engine.build(
        time_sales_rows=time_sales_rows,
        candles=candles,
        timeframe_minutes=1,
        limit=120,
    )
    dom_payload = dom_engine.build(
        time_sales_rows=time_sales_rows,
        candles=candles,
        depth=12,
    )
    orderflow_summary = orderflow_summary_engine.build(
        delta_summary=delta_payload.get("summary", {}),
        dom_summary=dom_payload.get("summary", {}),
        iceberg_rows=(overlays or {}).get("iceberg", []),
        time_sales_rows=time_sales_rows,
        regime_mode=getattr(prop_engine, "active_mode", "STANDARD"),
        volatility_mode=getattr(prop_engine, "volatility_mode", "NORMAL"),
    )
    gann_prices = []
    for line in gann_lines:
        price = _float_value((line or {}).get("price"), None)
        if price is not None and price > 0:
            gann_prices.append(price)

    support_candidates = [p for p in gann_prices if p <= last_close] if last_close > 0 else []
    resistance_candidates = [p for p in gann_prices if p >= last_close] if last_close > 0 else []
    nearest_support = max(support_candidates) if support_candidates else None
    nearest_resistance = min(resistance_candidates) if resistance_candidates else None

    market_data = {
        "symbol": symbol,
        "canonical_symbol": canonical_symbol,
        "pricing_source": market_data_raw.get("pricing_source") if isinstance(market_data_raw, dict) else None,
        "spot_fidelity": {
            "spot_primary": bool((market_data_raw or {}).get("spot_primary")),
            "strict": bool((market_data_raw or {}).get("spot_fidelity_strict")),
            "spot_data_available": bool((market_data_raw or {}).get("spot_source") or (market_data_raw or {}).get("pricing_source")),
        },
        "htf_bias": htf_bias,
        "ltf_structure": ltf_structure,
        "session": prop_engine.get_session(),
        "volatility": prop_engine.volatility_mode,
        "news_state": "HALT" if bool(runner.state.news_halt) else "NORMAL",
        "iceberg": iceberg,
    }

    model_data = _mentor_model_data(canonical_symbol, market_data_raw if isinstance(market_data_raw, dict) else {})
    risk_data = _mentor_risk_data()
    phase_data, exit_data = _mentor_phase_data(canonical_symbol)
    context = mentor_engine.build_context(market_data, model_data, risk_data, phase_data)
    context["exit"] = exit_data
    context["gann"] = gann_lines
    context["astro"] = astro_markers
    context["prices"] = {
        "last": round(last_close, 4) if last_close > 0 else None,
        "open": round(last_open, 4) if last_open > 0 else None,
        "high": round(last_high, 4) if last_high > 0 else None,
        "low": round(last_low, 4) if last_low > 0 else None,
        "midpoint": round(midpoint, 4) if midpoint > 0 else None,
        "range_points": round(range_points, 4) if range_points > 0 else None,
        "nearest_support": round(nearest_support, 4) if nearest_support is not None else None,
        "nearest_resistance": round(nearest_resistance, 4) if nearest_resistance is not None else None,
    }
    context["orderflow_summary"] = orderflow_summary
    return context


@app.post("/mentor/action")
def mentor_action(data: dict):
    payload = data or {}
    action = str(payload.get("action") or "").strip().lower()

    if action == "disable_model":
        return mentor_engine.disable_model(payload.get("model_name"))

    if action == "reduce_risk":
        return mentor_engine.reduce_risk_mode()

    if action == "aggressive_mode":
        return mentor_engine.set_aggressive_mode(bool(payload.get("enabled", True)), str(payload.get("password") or ""))

    if action == "last_trades":
        symbol = str(payload.get("symbol") or "XAUUSD")
        rows = [_trade_row_to_dict(row) for row in recent_trades(limit=5)]
        return {"status": "ok", "symbol": symbol, "last_trades": rows}

    if action == "model_stats":
        return {"status": "ok", "model_stats": model_stats()}

    return {"status": "error", "message": f"unknown action: {action}"}


@app.get("/prop/auto_behavior")
def prop_auto_behavior(symbol: str | None = None):
    if symbol:
        feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
        canonical_symbol = feed_to_canonical.get(symbol, symbol)
        _prime_symbol_runtime(canonical_symbol)
        return {
            "symbol": canonical_symbol,
            "behavior": runner.prop_behavior_snapshot(canonical_symbol),
            "override": runner.behavior_override_snapshot(canonical_symbol),
        }
    return {
        "symbols": symbols,
        "summary": runner.prop_behavior_summary(),
        "overrides": runner.behavior_override_summary(),
    }


@app.post("/prop/auto_behavior/override")
def prop_auto_behavior_override(data: dict):
    if bool(getattr(runner, "strict_challenge_mode", False)):
        return {"status": "blocked", "reason": "Manual override disabled in automated challenge mode"}
    payload = data or {}
    symbol = str(payload.get("symbol", "")).strip()
    if not symbol:
        return {"status": "error", "message": "symbol is required"}
    feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
    canonical_symbol = feed_to_canonical.get(symbol, symbol)
    snapshot = runner.set_behavior_override(
        canonical_symbol,
        mode=payload.get("mode"),
        risk_multiplier=payload.get("risk_multiplier"),
        hard_block=payload.get("hard_block"),
        reasons=payload.get("reasons") if isinstance(payload.get("reasons"), list) else [],
        expires_minutes=payload.get("expires_minutes"),
    )
    return {"status": "ok", "override": snapshot}


@app.post("/prop/auto_behavior/override/clear")
def prop_auto_behavior_override_clear(data: dict):
    if bool(getattr(runner, "strict_challenge_mode", False)):
        return {"status": "blocked", "reason": "Manual override disabled in automated challenge mode"}
    payload = data or {}
    symbol = payload.get("symbol")
    if symbol:
        feed_to_canonical = {v: k for k, v in runner.SYMBOL_MAP.items()}
        symbol = feed_to_canonical.get(symbol, symbol)
    return runner.clear_behavior_override(symbol=symbol)


@app.post("/prop/auto_behavior/simulate")
def prop_auto_behavior_simulate(data: dict):
    payload = data or {}
    symbol = str(payload.get("symbol") or "XAUUSD")
    simulated = prop_engine.compute_auto_behavior_profile(
        equity=float(payload.get("equity", runner.state.balance)),
        daily_loss=float(payload.get("daily_loss", runner.state.daily_loss)),
        drawdown=float(payload.get("drawdown", runner.capital.get_drawdown(runner.state.balance))),
        news_mode=str(payload.get("news_mode") or "NORMAL"),
        phase=str(payload.get("phase") or prop_engine.phase),
        volatility_mode=str(payload.get("volatility_mode") or prop_engine.volatility_mode),
        trading_enabled=bool(payload.get("trading_enabled", prop_engine.trading_enabled)),
        cooldown_active=bool(payload.get("cooldown_active", prop_engine.cooldown_active)),
    )
    simulated_with_override = runner.apply_behavior_override(symbol, simulated)
    return {"simulated": simulated, "simulated_with_override": simulated_with_override}


@app.post("/set_phase")
def set_phase(data: dict):
    open_positions_count = len(runner.positions.get_positions())
    if open_positions_count > 0:
        return {"error": "Cannot change phase during open trade", "open_positions": open_positions_count}
    phase = (data or {}).get("phase", "PHASE1")
    prop_engine.set_phase(phase)
    runner.prop.set_phase(phase)
    runner.state.phase = phase
    _apply_dynamic_prop_runtime(send_telegram_update=False)
    return {"status": "Phase updated", "phase": prop_engine.phase}


@app.post("/admin/set_phase")
def set_phase_admin(data: dict):
    return set_phase(data)


@app.post("/admin/set_account_size")
def set_account_size_admin(data: dict):
    payload = data or {}
    raw = payload.get("account_size", "50K")
    mode = str(payload.get("mode") or "STANDARD").upper().strip()

    account_key = str(raw).upper().strip()
    if account_key.isdigit():
        account_key = f"{int(float(account_key) / 1000)}K"
    elif account_key.endswith(".0") and account_key[:-2].isdigit():
        account_key = f"{int(float(account_key)) // 1000}K"
    elif account_key.endswith("K") and account_key[:-1].isdigit():
        account_key = account_key
    else:
        try:
            size = float(raw)
            account_key = f"{int(size // 1000)}K"
        except Exception:
            return {"error": "Invalid account_size"}

    if account_key not in set(supported_account_keys()):
        return {"error": f"Supported account sizes are {', '.join(supported_account_keys())}"}

    if len(runner.positions.get_positions()) > 0:
        return {"error": "Cannot change account size during open trades"}

    dynamic_prop_engine.configure(
        active_accounts=[account_key],
        primary_account=account_key,
        mode_map={account_key: mode},
    )
    snapshot = _apply_dynamic_prop_runtime(send_telegram_update=True)
    primary = snapshot.get("primary_profile", {})
    return {
        "status": "Account size updated",
        "account_size": prop_engine.config.account_size,
        "account_key": primary.get("account_key"),
        "mode": primary.get("mode"),
        "static_floor": prop_engine.static_floor,
        "funded_lock_level": prop_engine.funded_lock_level,
        "phase": prop_engine.phase,
        "active_accounts": snapshot.get("active_accounts", []),
    }


@app.post("/admin/prop_engine/configure")
def configure_dynamic_prop_engine(data: dict):
    payload = data or {}

    if len(runner.positions.get_positions()) > 0:
        return {"error": "Cannot reconfigure prop engine during open trades"}

    active_accounts = payload.get("active_accounts") if isinstance(payload.get("active_accounts"), list) else None
    primary_account = payload.get("primary_account")
    default_mode = payload.get("default_mode")
    mode_map = payload.get("mode_map") if isinstance(payload.get("mode_map"), dict) else {}

    normalized_active = [] if active_accounts is None else [str(item).upper().strip() for item in active_accounts]
    normalized_mode_map = {str(key).upper().strip(): str(value).upper().strip() for key, value in mode_map.items()}
    normalized_primary = str(primary_account).upper().strip() if primary_account is not None else None
    normalized_default_mode = str(default_mode).upper().strip() if default_mode is not None else None

    dynamic_prop_engine.configure(
        active_accounts=normalized_active if active_accounts is not None else None,
        primary_account=normalized_primary,
        mode_map=normalized_mode_map,
        default_mode=normalized_default_mode,
    )

    snapshot = _apply_dynamic_prop_runtime(send_telegram_update=True)
    return {
        "status": "ok",
        "phase": prop_engine.phase,
        "state": snapshot,
    }


@app.post("/engine/start")
def start_engine():
    global runner_thread
    if runner_thread and runner_thread.is_alive():
        return {"status": "Already Running"}
    runner_thread = threading.Thread(target=runner.start, daemon=True)
    runner_thread.start()
    return {"status": "Engine Started"}


@app.post("/engine/stop")
def stop_engine():
    runner.stop()
    return {"status": "Engine Stopped"}


@app.get("/download_monthly_report")
def download_report():
    path = generate_monthly_report()
    return FileResponse(path, media_type="text/csv", filename=path)


@app.post("/notify/daily_summary")
def notify_daily_summary():
    metrics = daily_metrics_from_journal()
    summary_text = build_daily_summary(
        equity=runner.state.balance,
        pnl=metrics["pnl"],
        trades=metrics["trades"],
        win_rate=metrics["win_rate"],
        phase=prop_engine.phase,
        volatility_mode=prop_engine.volatility_mode,
    )
    send_result = send_daily_summary(summary_text)
    return {"metrics": metrics, "summary": summary_text, "telegram": send_result}


@app.get("/telegram/status")
def telegram_status():
    telegram_engine = getattr(runner, "telegram", None)
    if telegram_engine is None:
        return {"active": False, "configured": False, "reason": "Telegram engine unavailable"}
    return telegram_engine.status()


@app.post("/telegram/test")
def telegram_test(data: dict | None = None):
    payload = data or {}
    message = str(payload.get("message") or "AstroQuant test alert")
    telegram_engine = getattr(runner, "telegram", None)
    if telegram_engine is None:
        return {"ok": False, "reason": "Telegram engine unavailable"}
    ok = bool(telegram_engine.send(message))
    status = telegram_engine.status()
    return {"ok": ok, "status": status}


@app.get("/clawbot/status")
def clawbot_status():
    if not hasattr(runner, "clawbot_status"):
        return {"active": False, "mode": "UNKNOWN", "reason": "Clawbot unavailable"}
    snapshot = runner.clawbot_status()
    return {
        "active": True,
        **snapshot,
    }


@app.post("/broker/equity")
def broker_equity(data: dict):
    equity = data.get("equity") if isinstance(data, dict) else None
    if equity is None:
        return {"status": "ignored", "reason": "missing equity"}
    try:
        equity_value = float(equity)
    except Exception:
        return {"status": "ignored", "reason": "invalid equity"}
    runner.state.balance = equity_value
    prop_status_result = prop_engine.update_equity(equity_value)
    _handle_phase_event(prop_status_result)
    runner.state.phase = prop_engine.phase
    return {
        "status": "synced",
        "equity": equity_value,
        "prop_status": prop_status_result,
        "trading_enabled": prop_engine.can_trade(),
    }


@app.post("/broker/sync_equity_from_page")
def sync_equity_from_page_endpoint():
    page = runner.execution.playwright.page
    if page is None:
        return {"status": "ignored", "reason": "browser page unavailable"}
    equity = fetch_equity_from_browser(page)
    if equity is None:
        return {"status": "ignored", "reason": "equity selector unavailable"}
    runner.state.balance = equity
    prop_status_result = prop_engine.update_equity(equity)
    _handle_phase_event(prop_status_result)
    runner.state.phase = prop_engine.phase
    return {
        "status": "synced",
        "equity": equity,
        "prop_status": prop_status_result,
        "trading_enabled": prop_engine.can_trade(),
    }
