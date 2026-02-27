from fastapi import APIRouter, Depends, Query
from concurrent.futures import ThreadPoolExecutor, wait
import csv
import os
from datetime import datetime, timezone

from backend.security import require_admin_key
from engine.data_engine import DataEngine
from engine.orderflow_engine import OrderFlowEngine
from engine.iceberg_engine import IcebergEngine
from engine.fusion_engine import FusionEngine
from ai.mentor import AIMentor
from engine.ict_engine import ICTEngine
from engine.gann_engine import GannEngine
from engine.astro_engine import AstroEngine
from engine.regime_engine import RegimeEngine
from engine.prop_phase_engine import PropPhaseEngine
from engine.capital_engine import CapitalEngine
from engine.risk_engine import RiskEngine
from execution.execution_manager import get_execution_manager
from execution.symbol_mapper import to_execution_symbol
from execution.config import SYMBOL_SPREAD_LIMITS, TRADE_UNIVERSE
from backend.engines.news_engine import NewsEngine
from backend.engines.cycle_engine import CycleEngine
from backend.engines.liquidity_engine import LiquidityEngine
from backend.modules.rollover_manager import RolloverManager
from backend.services.data_freshness_service import staleness_limit_for
from backend.services.market_data_service import safe_float, normalize_bars, generate_fallback_bars, aggregate_bars


router = APIRouter()

# --- EMERGENCY CONTROL ROUTES ---
@router.get("/emergency/stop")
def emergency_stop(_auth: None = Depends(require_admin_key)):
    execution_manager.enable_emergency_stop()
    return {"status": "Emergency stop enabled"}


@router.get("/emergency/start")
def emergency_start(_auth: None = Depends(require_admin_key)):
    execution_manager.disable_emergency_stop()
    return {"status": "Trading resumed"}


data_engine = DataEngine()
orderflow = OrderFlowEngine()
iceberg_engine = IcebergEngine()
fusion = FusionEngine()
mentor = AIMentor()
ict_engine = ICTEngine()
gann_engine = GannEngine()
astro_engine = AstroEngine()
regime_engine = RegimeEngine()
phase_engine = PropPhaseEngine()
capital_engine = CapitalEngine()
risk_engine = RiskEngine()
execution_manager = get_execution_manager()
news_guard_engine = NewsEngine()
cycle_overlay_engine = CycleEngine()
liquidity_overlay_engine = LiquidityEngine()
rollover_manager = RolloverManager(data_engine)
try:
    MARKET_FETCH_TIMEOUT_SECONDS = float(os.getenv("MARKET_FETCH_TIMEOUT_SECONDS", "8"))
except Exception:
    MARKET_FETCH_TIMEOUT_SECONDS = 8.0
MARKET_FETCH_TIMEOUT_SECONDS = max(2.0, min(MARKET_FETCH_TIMEOUT_SECONDS, 30.0))

try:
    ENGINES_ANALYZE_TIMEOUT_SECONDS = float(os.getenv("ENGINES_ANALYZE_TIMEOUT_SECONDS", "9"))
except Exception:
    ENGINES_ANALYZE_TIMEOUT_SECONDS = 9.0
ENGINES_ANALYZE_TIMEOUT_SECONDS = max(2.0, min(ENGINES_ANALYZE_TIMEOUT_SECONDS, 30.0))


def _timed_fetch(fetcher, timeout_seconds: float, fallback):
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fetcher)
    try:
        return future.result(timeout=timeout_seconds)
    except Exception:
        future.cancel()
        return fallback
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _is_futures_symbol(symbol: str):
    normalized = str(symbol or "").upper()
    return normalized.endswith(".FUT") or normalized.startswith(("GC", "NQ", "YM", "CL", "6E", "6B"))


def _load_bars_with_rollover(symbol: str, minutes: int, fallback_count: int):
    symbol_upper = str(symbol or "").upper()
    rollover_meta = None

    if _is_futures_symbol(symbol_upper):
        continuous = _timed_fetch(
            lambda: rollover_manager.get_continuous_ohlcv(symbol_upper, minutes=minutes),
            MARKET_FETCH_TIMEOUT_SECONDS,
            {"bars": [], "meta": None},
        )
        bars = continuous.get("bars") or generate_fallback_bars(fallback_count)
        rollover_meta = continuous.get("meta")
        return bars, rollover_meta, bool(continuous.get("bars"))

    raw_bars = _timed_fetch(
        lambda: data_engine.get_ohlcv(symbol),
        MARKET_FETCH_TIMEOUT_SECONDS,
        [],
    )
    bars = normalize_bars(raw_bars) if raw_bars else generate_fallback_bars(fallback_count)
    return bars, rollover_meta, bool(raw_bars)


def _bar_timestamp_utc(bar):
    if not isinstance(bar, dict):
        return None

    raw_value = bar.get("time") or bar.get("ts_event") or bar.get("timestamp")
    if raw_value is None:
        return None

    if isinstance(raw_value, datetime):
        dt = raw_value
    else:
        text = str(raw_value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _bar_age_seconds(bars):
    if not bars:
        return None

    latest = _bar_timestamp_utc(bars[-1])
    if latest is None:
        return None

    age = (datetime.now(timezone.utc) - latest).total_seconds()
    return max(0.0, float(age))


@router.get("/symbols")
def symbols():
    data_symbols = [item.get("data_symbol") for item in TRADE_UNIVERSE if item.get("data_symbol")]
    broker_symbols = [item.get("broker_symbol") for item in TRADE_UNIVERSE if item.get("broker_symbol")]
    return [*data_symbols, *broker_symbols, *list(SYMBOL_SPREAD_LIMITS.keys())]


@router.get("/news/status")
def news_status(symbol: str = Query("GC.FUT")):
    bars, rollover_meta, _ = _load_bars_with_rollover(symbol, minutes=240, fallback_count=60)

    news = news_guard_engine.analyze(symbol, bars)

    trade_halt = bool(news.get("trade_halt", False))
    high_impact_text = str(news.get("high_impact", "") or "")
    high_impact = trade_halt or (high_impact_text.strip().lower() not in ["", "no major event detected"])

    return {
        "symbol": symbol,
        "high_impact": high_impact,
        "trade_halt": trade_halt,
        "headline": high_impact_text,
        "reaction_bias": news.get("reaction_bias", "Neutral"),
        "rollover": rollover_meta,
    }


@router.get("/futures/continuous")
def futures_continuous(symbol: str = Query("GC"), minutes: int = Query(720, ge=60, le=10080)):
    continuous = rollover_manager.get_continuous_ohlcv(symbol, minutes=minutes)
    bars = continuous.get("bars", [])
    return {
        "symbol": symbol,
        "bars": bars,
        "bar_count": len(bars),
        "rollover": continuous.get("meta", {}),
    }


@router.get("/futures/rollovers")
def futures_rollovers(symbol: str = Query("GC")):
    return rollover_manager.get_rollover_history(symbol)


@router.get("/futures/rollover-status")
def futures_rollover_status(symbol: str = Query("GC")):
    return rollover_manager.get_rollover_status(symbol)


@router.get("/journal")
def get_journal():
    log_path = "logs/execution_log.csv"
    if not os.path.exists(log_path):
        return []

    rows = []
    with open(log_path, "r") as file:
        reader = csv.reader(file)
        for record in reader:
            if len(record) < 4:
                continue
            symbol, direction, lot, confidence = record[:4]
            if symbol.lower() == "symbol" and direction.lower() == "direction":
                continue
            rows.append(
                {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "symbol": symbol,
                    "model": "fusion",
                    "direction": direction,
                    "entry": "--",
                    "sl": "--",
                    "tp": "--",
                    "confidence": confidence,
                    "result": "OPEN",
                    "slippage": "--",
                    "lot": lot,
                }
            )

    return rows


@router.get("/engines")
def engines():
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    open_slots_used = len(execution_manager.active_symbols)
    slot_limit = 2
    profiles = list(TRADE_UNIVERSE)
    pool = ThreadPoolExecutor(max_workers=max(1, min(6, len(profiles))))
    try:
        futures = {
            profile.get("broker_symbol", profile.get("data_symbol", "GC.FUT")): (profile, pool.submit(analyze, profile.get("data_symbol", "GC.FUT")))
            for profile in profiles
        }

        all_futures = [future for _, future in futures.values()]
        done_set, _ = wait(all_futures, timeout=ENGINES_ANALYZE_TIMEOUT_SECONDS)

        for broker_key, (profile, future) in futures.items():
            data_symbol = profile.get("data_symbol", "GC.FUT")
            broker_symbol = profile.get("broker_symbol", data_symbol)
            priority = profile.get("priority", "MEDIUM")
            try:
                if future not in done_set:
                    raise TimeoutError("Analysis timeout")
                analysis = future.result()
            except TimeoutError:
                rows.append(
                    {
                        "time": now,
                        "symbol": broker_symbol,
                        "status": "ERROR",
                        "model": "fusion",
                        "confidence": 0,
                        "top_signals": "--",
                        "ai_score": "--",
                        "chosen_model": "--",
                        "reason_blocked": "Analysis timeout",
                        "active_model": "--",
                        "active_direction": "--",
                        "score_gap": "--",
                        "concurrent_slots": f"{open_slots_used}/{slot_limit}",
                        "rollover_status": "--",
                        "rollover_contract": "--",
                        "data_fresh": False,
                        "data_age_seconds": None,
                        "max_staleness_seconds": staleness_limit_for(data_symbol),
                        "spread": "--",
                        "pnl": "--",
                    }
                )
                continue

            except Exception:
                rows.append(
                    {
                        "time": now,
                        "symbol": broker_symbol,
                        "status": "ERROR",
                        "model": "fusion",
                        "confidence": 0,
                        "top_signals": "--",
                        "ai_score": "--",
                        "chosen_model": "--",
                        "reason_blocked": "Engine error",
                        "active_model": "--",
                        "active_direction": "--",
                        "score_gap": "--",
                        "concurrent_slots": f"{open_slots_used}/{slot_limit}",
                        "rollover_status": "--",
                        "rollover_contract": "--",
                        "data_fresh": False,
                        "data_age_seconds": None,
                        "max_staleness_seconds": staleness_limit_for(data_symbol),
                        "spread": "--",
                        "pnl": "--",
                    }
                )
                continue

            try:
                fusion_result = analysis.get("fusion", {})
                execution_symbol = analysis.get("execution_symbol", broker_symbol)
                active_direction = execution_manager.active_symbols.get(execution_symbol)
                rollover_meta = analysis.get("meta", {}).get("rollover") or {}

                raw_signals = fusion_result.get("signals", [])
                if isinstance(raw_signals, list):
                    top_signals = ", ".join([
                        str(signal.get("model", signal)).upper() if isinstance(signal, dict) else str(signal)
                        for signal in raw_signals[:2]
                    ])
                else:
                    top_signals = ""

                chosen_model = (
                    fusion_result.get("chosen_model")
                    or fusion_result.get("model")
                    or analysis.get("mentor", {}).get("active_model")
                    or "FUSION"
                )

                if analysis.get("trade_halted"):
                    reason_blocked = analysis.get("halt_reason") or "Trade halted"
                elif not bool((analysis.get("meta") or {}).get("data_fresh", True)):
                    age_seconds = int((analysis.get("meta") or {}).get("data_age_seconds", 0) or 0)
                    reason_blocked = f"Stale data ({age_seconds}s)"
                elif active_direction:
                    reason_blocked = "Position active"
                elif analysis.get("auto_executed"):
                    reason_blocked = "--"
                else:
                    reason_blocked = "No approved signal"

                rows.append(
                    {
                        "time": now,
                        "symbol": broker_symbol,
                        "status": "ACTIVE" if analysis.get("auto_executed") else "MONITORING",
                        "model": f"fusion/{priority}",
                        "confidence": fusion_result.get("confidence", 0),
                        "top_signals": top_signals or "--",
                        "ai_score": fusion_result.get("ai_score", "--"),
                        "chosen_model": str(chosen_model).upper(),
                        "reason_blocked": reason_blocked,
                        "active_model": str(chosen_model).upper() if active_direction else "--",
                        "active_direction": active_direction or "--",
                        "score_gap": fusion_result.get("score_gap", "--"),
                        "concurrent_slots": f"{open_slots_used}/{slot_limit}",
                        "rollover_status": "WEEK" if rollover_meta.get("rollover_week") else "NORMAL" if rollover_meta else "--",
                        "rollover_contract": rollover_meta.get("active_contract", "--") if rollover_meta else "--",
                        "data_fresh": bool((analysis.get("meta") or {}).get("data_fresh", False)),
                        "data_age_seconds": (analysis.get("meta") or {}).get("data_age_seconds"),
                        "max_staleness_seconds": (analysis.get("meta") or {}).get("max_staleness_seconds"),
                        "spread": "--",
                        "pnl": "--",
                    }
                )
            except Exception:
                rows.append(
                    {
                        "time": now,
                        "symbol": broker_symbol,
                        "status": "ERROR",
                        "model": "fusion",
                        "confidence": 0,
                        "top_signals": "--",
                        "ai_score": "--",
                        "chosen_model": "--",
                        "reason_blocked": "Engine error",
                        "active_model": "--",
                        "active_direction": "--",
                        "score_gap": "--",
                        "concurrent_slots": f"{open_slots_used}/{slot_limit}",
                        "rollover_status": "--",
                        "rollover_contract": "--",
                        "data_fresh": False,
                        "data_age_seconds": None,
                        "max_staleness_seconds": staleness_limit_for(data_symbol),
                        "spread": "--",
                        "pnl": "--",
                    }
                )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return rows


@router.get("/orderflow/iceberg/{symbol}")
def orderflow_iceberg(symbol: str):
    raw_bars = data_engine.get_ohlcv(symbol)
    bars = normalize_bars(raw_bars) if raw_bars else generate_fallback_bars(30)
    of = orderflow.analyze(bars)
    rows = []
    as_of_time = bars[-1].get("time", "--") if bars else "--"

    ladder = of.get("ladder") if isinstance(of, dict) else None
    if isinstance(ladder, list) and ladder:
        for level in ladder[:20]:
            bid_size = safe_float(level.get("bid_size", 0))
            ask_size = safe_float(level.get("ask_size", 0))
            rows.append(
                {
                    "time": as_of_time,
                    "price": round(safe_float(level.get("price", 0)), 2),
                    "buy_volume": round(bid_size, 2),
                    "sell_volume": round(ask_size, 2),
                    "bias": "BUY" if bid_size >= ask_size else "SELL",
                }
            )

    if not rows:
        recent = bars[-12:]
        for bar in recent:
            price = safe_float(bar.get("close", 0))
            volume = safe_float(bar.get("volume", 0))
            buy_volume = round(volume * 0.58, 2)
            sell_volume = round(volume * 0.42, 2)
            rows.append(
                {
                    "time": bar.get("time", "--"),
                    "price": round(price, 2),
                    "buy_volume": buy_volume,
                    "sell_volume": sell_volume,
                    "bias": "BUY" if buy_volume >= sell_volume else "SELL",
                }
            )

    return rows


@router.get("/orderflow/table/{symbol}")
def orderflow_table(symbol: str):
    raw_bars = data_engine.get_ohlcv(symbol)
    bars = normalize_bars(raw_bars) if raw_bars else generate_fallback_bars(30)
    rows = []

    for bar in bars[-20:]:
        close_price = safe_float(bar.get("close", 0))
        open_price = safe_float(bar.get("open", close_price))
        volume = safe_float(bar.get("volume", 0))
        delta = round((close_price - open_price) * 20, 2)
        imbalance = round((delta / volume), 4) if volume else 0
        rows.append(
            {
                "time": bar.get("time", "--"),
                "delta": delta,
                "volume": round(volume, 2),
                "imbalance": imbalance,
            }
        )

    return rows


@router.get("/orderflow/ladder/{symbol}")
def orderflow_ladder(symbol: str):
    raw_bars = data_engine.get_ohlcv(symbol)
    bars = normalize_bars(raw_bars) if raw_bars else generate_fallback_bars(15)
    center_price = safe_float(bars[-1].get("close", 2350.0)) if bars else 2350.0
    as_of_time = bars[-1].get("time", "--") if bars else "--"

    rows = []
    step = 0.25
    for index in range(15):
        price = round(center_price + ((7 - index) * step), 2)
        distance = abs(7 - index)
        bid_size = max(1, 150 - distance * 16)
        ask_size = max(1, 145 - distance * 15)
        rows.append(
            {
                "time": as_of_time,
                "price": price,
                "bid_size": bid_size,
                "ask_size": ask_size,
            }
        )

    return rows


@router.get("/orderflow/time-sales/{symbol}")
def orderflow_time_sales(symbol: str):
    raw_bars = data_engine.get_ohlcv(symbol)
    bars = normalize_bars(raw_bars) if raw_bars else generate_fallback_bars(25)

    rows = []
    for bar in bars[-25:]:
        open_price = safe_float(bar.get("open", 0))
        close_price = safe_float(bar.get("close", 0))
        rows.append(
            {
                "time": bar.get("time", "--"),
                "price": round(close_price, 2),
                "size": round(safe_float(bar.get("volume", 0)), 2),
                "side": "BUY" if close_price >= open_price else "SELL",
            }
        )

    return rows


@router.get("/cycle/{symbol}")
def cycle_status(symbol: str):
    raw_bars = data_engine.get_ohlcv(symbol)
    bars = normalize_bars(raw_bars) if raw_bars else generate_fallback_bars(120)
    output = cycle_overlay_engine.analyze(bars)
    output["time"] = bars[-1].get("time", datetime.now(timezone.utc).isoformat()) if bars else datetime.now(timezone.utc).isoformat()
    return output


@router.get("/liquidity/{symbol}")
def liquidity_status(symbol: str):
    raw_bars = data_engine.get_ohlcv(symbol)
    bars = normalize_bars(raw_bars) if raw_bars else generate_fallback_bars(120)
    output = liquidity_overlay_engine.analyze(bars)
    output["time"] = bars[-1].get("time", datetime.now(timezone.utc).isoformat()) if bars else datetime.now(timezone.utc).isoformat()
    return output


@router.get("/analyze/{symbol}")


def analyze(symbol: str, tf: str = Query("5m")):
    base_bars, rollover_meta, has_live_data = _load_bars_with_rollover(symbol, minutes=360, fallback_count=120)
    raw_bars = base_bars if has_live_data else []
    data_age_seconds = _bar_age_seconds(base_bars)
    max_staleness_seconds = staleness_limit_for(symbol)
    data_fresh = bool(
        has_live_data
        and data_age_seconds is not None
        and data_age_seconds <= max_staleness_seconds
    )

    bars = aggregate_bars(base_bars, tf)

    of = orderflow.analyze(bars)
    ice = iceberg_engine.detect(of, bars[-1])
    ict = ict_engine.analyze(bars)
    gann = gann_engine.analyze(bars)
    astro = astro_engine.analyze()
    regime = regime_engine.detect(bars)

    fu = fusion.combine(of, ice, ict, gann, astro, regime)

    mentor_struct = mentor.structured(fu, ice, ict, gann, astro)

    news_guard = news_guard_engine.analyze(symbol, bars)
    cycle_data = cycle_overlay_engine.analyze(bars)
    liquidity_data = liquidity_overlay_engine.analyze(bars)

    # --- Institutional position sync ---
    execution_manager.sync_position_state()

    auto_executed = False
    trade_halted = bool(news_guard.get("trade_halt", False))
    halt_reason = news_guard.get("high_impact", "News risk event") if trade_halted else None

    if not data_fresh:
        trade_halted = True
        halt_reason = "Stale market data"

    if fu["confidence"] >= 75 and raw_bars and not trade_halted:
        auto_executed = execution_manager.execute_trade(fu, symbol=symbol)

    fu["prices"] = bars
    fu["signals"] = []

    start_time = bars[0]["time"] if bars else datetime.now(timezone.utc).isoformat()
    end_time = bars[-1]["time"] if bars else datetime.now(timezone.utc).isoformat()
    low_price = min((bar["low"] for bar in bars), default=0)
    high_price = max((bar["high"] for bar in bars), default=0)
    last_close = bars[-1]["close"] if bars else 0

    fu["cycle"] = {
        "times": [start_time, end_time] if bars else [],
        "levels": [last_close, last_close] if bars else [],
        "phase": cycle_data.get("phase", "Build-up"),
        "active_cycles": cycle_data.get("active_cycles", []),
    }
    fu["liquidity"] = {
        "times": [start_time, end_time] if bars else [],
        "equilibrium": [liquidity_data.get("equilibrium", 0), liquidity_data.get("equilibrium", 0)] if bars else [],
        "range_low": liquidity_data.get("range_low", 0),
        "range_high": liquidity_data.get("range_high", 0),
        "bias": liquidity_data.get("bias", "Neutral"),
    }

    engine_overlays = {
        "iceberg": {
            "enabled": bool(ice),
            "times": [start_time, end_time] if ice else [],
            "levels": [ice.get("price"), ice.get("price")] if ice else []
        },
        "gann": {
            "enabled": True,
            "times": [start_time, end_time],
            "level_50": gann.get("level_50"),
            "level_100": gann.get("level_100")
        },
        "astro": {
            "enabled": True,
            "times": [bars[-1]["time"]] if bars else [],
            "levels": [last_close] if bars else [],
            "harmonic": astro.get("harmonic")
        },
        "cycle": {
            "enabled": True,
            "times": [start_time, end_time] if bars else [],
            "levels": [last_close, last_close] if bars else [],
            "phase": cycle_data.get("phase", "Build-up"),
            "is_cycle": cycle_data.get("is_cycle", False),
            "active_cycles": cycle_data.get("active_cycles", []),
        },
        "liquidity": {
            "enabled": True,
            "times": [start_time, end_time] if bars else [],
            "equilibrium": [liquidity_data.get("equilibrium", 0), liquidity_data.get("equilibrium", 0)] if bars else [],
            "range_low": liquidity_data.get("range_low", 0),
            "range_high": liquidity_data.get("range_high", 0),
            "bias": liquidity_data.get("bias", "Neutral"),
            "zone": liquidity_data.get("zone", "Unavailable"),
        },
        "news": {
            "enabled": True,
            "times": [bars[-1]["time"]] if bars else [],
            "levels": [last_close] if bars else [],
            "trade_halt": trade_halted,
            "label": news_guard.get("high_impact", "No major event detected"),
            "line": {
                "times": [end_time, end_time],
                "levels": [low_price, high_price]
            }
        }
    }


    return {
        "symbol": symbol,
        "execution_symbol": to_execution_symbol(symbol),
        "fusion": fu,
        "auto_executed": auto_executed,
        "trade_halted": trade_halted,
        "halt_reason": halt_reason,
        "news": news_guard,
        "cycle": cycle_data,
        "liquidity": liquidity_data,
        "engine_overlays": engine_overlays,
        "mentor": mentor_struct,
        "meta": {
            "data_source": "live" if has_live_data else "fallback",
            "data_fresh": data_fresh,
            "data_age_seconds": round(data_age_seconds, 2) if data_age_seconds is not None else None,
            "max_staleness_seconds": max_staleness_seconds,
            "rollover": rollover_meta,
        }
    }


# --- PHASE 3: PROP STATUS ROUTE ---
@router.get("/prop/status")
def prop_status():

    phase_progress = phase_engine.progress()

    withdrawal = capital_engine.check_withdrawal(
        phase_engine.current_balance
    )

    return {
        "phase": phase_engine.phase,
        "balance": phase_engine.current_balance,
        "daily_loss": risk_engine.daily_loss if hasattr(risk_engine, "daily_loss") else 0,
        "progress": phase_progress,
        "withdrawal": withdrawal
    }
