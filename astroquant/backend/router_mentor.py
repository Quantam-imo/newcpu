
from fastapi import APIRouter
from astroquant.backend.ai.mentor_engine import MentorEngine
from astroquant.engine.mentor_gann_engine import MentorGannEngine
from astroquant.engine.mentor_astro_engine import MentorAstroEngine
from functools import lru_cache
import time
from datetime import datetime, timezone
# Ensure .env variables are loaded through standard dotenv resolution.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _detect_session() -> str:
    """Return the current trading session based on UTC hour."""
    hour = datetime.now(timezone.utc).hour
    # Overlaps take priority
    if 12 <= hour < 16:
        return "LONDON/NY"
    if 7 <= hour < 12:
        return "LONDON"
    if 16 <= hour < 21:
        return "NY"
    if hour >= 23 or hour < 2:
        return "TOKYO"
    return "ASIA/OFF"


def _detect_volatility(candles: list) -> str:
    """Classify volatility using ATR of the last 14 candles."""
    if len(candles) < 5:
        return "NORMAL"
    recent = candles[-14:]
    ranges = [
        abs(float(c.get("high", 0) or 0) - float(c.get("low", 0) or 0))
        for c in recent
        if c.get("high") and c.get("low")
    ]
    if not ranges:
        return "NORMAL"
    atr = sum(ranges) / len(ranges)
    last_close = float(candles[-1].get("close", 2000) or 2000)
    if last_close <= 0:
        return "NORMAL"
    atr_pct = atr / last_close * 100
    if atr_pct > 0.4:
        return "HIGH"
    if atr_pct < 0.07:
        return "LOW"
    return "NORMAL"

def _derive_liquidity_sweep(candles: list, prev_low, prev_high) -> dict:
    """Detect if recent candles swept a prior range extreme."""
    if len(candles) < 3 or prev_low is None or prev_high is None:
        return {"sweep": "none", "target": "--"}
    last = candles[-1]
    last_low = float(last.get("low", 0) or 0)
    last_high = float(last.get("high", 0) or 0)
    last_close = float(last.get("close", 0) or 0)
    if last_high >= prev_high and last_close < prev_high * 0.9999:
        return {"sweep": "HIGH_SWEEP", "target": "SHORT_REVERSAL"}
    if last_low <= prev_low and last_close > prev_low * 1.0001:
        return {"sweep": "LOW_SWEEP", "target": "LONG_REVERSAL"}
    if last_close > prev_high:
        return {"sweep": "BREAKOUT_HIGH", "target": "CONTINUATION_LONG"}
    if last_close < prev_low:
        return {"sweep": "BREAKDOWN_LOW", "target": "CONTINUATION_SHORT"}
    return {"sweep": "none", "target": "--"}


def _derive_ict_patterns(candles: list) -> dict:
    """Detect Turtle Soup, FVG, and Order Block from candles."""
    if len(candles) < 5:
        return {"turtle_soup": "INSUFFICIENT_DATA", "fvg_zone": "--", "order_block": "--", "liquidity_sweep": "none"}
    fvg = "--"
    for i in range(len(candles) - 1, 1, -1):
        h0 = float(candles[i - 2].get("high", 0) or 0)
        l0 = float(candles[i - 2].get("low", 0) or 0)
        h2 = float(candles[i].get("high", 0) or 0)
        l2 = float(candles[i].get("low", 0) or 0)
        if l2 > h0 and h0 > 0:
            fvg = f"BULL_FVG @ {round((h0 + l2) / 2, 2)}"
            break
        if h2 < l0 and l0 > 0:
            fvg = f"BEAR_FVG @ {round((l0 + h2) / 2, 2)}"
            break
    ob = "--"
    for c in reversed(candles[-15:]):
        o = float(c.get("open", 0) or 0)
        cl = float(c.get("close", 0) or 0)
        h = float(c.get("high", 0) or 0)
        l = float(c.get("low", 0) or 0)
        rng = h - l
        body = abs(cl - o)
        if rng > 1e-9 and body / rng > 0.60:
            tag = "BULL_OB" if cl > o else "BEAR_OB"
            ob = f"{tag} @ {round(min(o, cl), 2)}-{round(max(o, cl), 2)}"
            break
    turtle = "NO_PATTERN"
    if len(candles) >= 10:
        window = candles[-10:]
        prior_highs = [float(c.get("high", 0) or 0) for c in window[:-1]]
        prior_lows  = [float(c.get("low", 0) or 0)  for c in window[:-1]]
        last_c = window[-1]
        lh = float(last_c.get("high", 0) or 0)
        ll = float(last_c.get("low", 0) or 0)
        lclose = float(last_c.get("close", 0) or 0)
        if prior_highs and lh >= max(prior_highs) and lclose < max(prior_highs):
            turtle = "HIGH_SWEEP_REVERSAL"
        elif prior_lows and ll <= min(prior_lows) and lclose > min(prior_lows):
            turtle = "LOW_SWEEP_REVERSAL"
    return {"turtle_soup": turtle, "fvg_zone": fvg, "order_block": ob, "liquidity_sweep": "none"}


def _derive_orderflow(candles: list, htf_bias: str) -> dict:
    """Derive buy/sell pressure delta and signal strength from candle bodies."""
    if len(candles) < 5:
        return {"delta_state": "NEUTRAL", "absorption_signal": "none", "direction": "--",
                "signal_strength": 50, "narrative": "Insufficient data."}
    recent = candles[-10:]
    buy_pts  = sum(float(c.get("close", 0) or 0) - float(c.get("open", 0) or 0)
                   for c in recent if float(c.get("close", 0) or 0) >= float(c.get("open", 0) or 0))
    sell_pts = sum(float(c.get("open", 0) or 0) - float(c.get("close", 0) or 0)
                   for c in recent if float(c.get("close", 0) or 0) < float(c.get("open", 0) or 0))
    total = buy_pts + sell_pts
    if total < 1e-9:
        delta_state, signal_strength = "NEUTRAL", 50
    elif buy_pts > sell_pts * 1.3:
        delta_state = "BUYING"
        signal_strength = min(100, int(60 + (buy_pts / total) * 40))
    elif sell_pts > buy_pts * 1.3:
        delta_state = "SELLING"
        signal_strength = min(100, int(60 + (sell_pts / total) * 40))
    else:
        delta_state, signal_strength = "NEUTRAL", 50
    absorption = ("BUY_ABSORPTION" if delta_state == "BUYING"
                  else "SELL_ABSORPTION" if delta_state == "SELLING" else "none")
    direction = htf_bias if htf_bias in ("BULLISH", "BEARISH") else delta_state
    narrative = f"Net candle delta: {delta_state.lower()} ({signal_strength}% strength). HTF: {htf_bias}."
    return {"delta_state": delta_state, "absorption_signal": absorption,
            "direction": direction, "signal_strength": signal_strength, "narrative": narrative}


def _derive_engine_status_blocks(candles: list, market_data: dict) -> tuple[dict, dict]:
    """Return Gann/Astro blocks using runtime engine flags and mentor engines."""
    gann_enabled = False
    astro_enabled = False
    try:
        from astroquant.backend.runtime import get_runner
        runner = get_runner()
        flags = getattr(runner, "engine_enable_flags", {}) or {}
        gann_enabled = bool(flags.get("GANN", False))
        astro_enabled = bool(flags.get("ASTRO", False))
    except Exception:
        pass

    last = candles[-1] if candles else {}
    lows = [float(c.get("low", 0) or 0) for c in candles[-20:] if c.get("low")]
    highs = [float(c.get("high", 0) or 0) for c in candles[-20:] if c.get("high")]
    lo = min(lows) if lows else float(last.get("low", 0) or 0)
    hi = max(highs) if highs else float(last.get("high", 0) or 0)
    bar_range = max(0.0, hi - lo)

    if gann_enabled:
        gann_calc = mentor_gann_engine.calculate({
            "range": bar_range,
            "low": lo,
            "bar_count": len(candles),
        })
        direction = "NONE"
        htf = str(market_data.get("htf_bias", "")).upper()
        if htf.startswith("BULL"):
            direction = "BUY"
        elif htf.startswith("BEAR"):
            direction = "SELL"
        confidence = 60 if direction in {"BUY", "SELL"} else 45
        gann_block = {
            "_engine": "ACTIVE",
            "enabled": True,
            "detected": direction in {"BUY", "SELL"},
            "direction": direction,
            "confidence": confidence,
            "score": confidence,
            "reason": "SIGNAL_DERIVED" if direction in {"BUY", "SELL"} else "NO_CLEAR_DIRECTION",
            **gann_calc,
        }
    else:
        gann_block = {
            "_engine": "NOT_ACTIVE",
            "enabled": False,
            "detected": False,
            "direction": "NONE",
            "confidence": 0,
            "score": 0,
            "cycle": 0,
            "reason": "ENGINE_DISABLED",
        }

    if astro_enabled:
        volatility = str(market_data.get("volatility", "")).upper()
        astro_payload = {
            "astro_window_active": str(market_data.get("session", "")).upper() in {"LONDON", "NY", "LONDON/NY"},
            "astro_marker": "Mars Square Saturn" if volatility == "HIGH" else "NO_EVENT",
            "astro_bias": "Volatility" if volatility == "HIGH" else "Neutral",
        }
        astro_calc = mentor_astro_engine.calculate(astro_payload)
        astro_block = {
            "_engine": "ACTIVE",
            **astro_calc,
            "reason": "WINDOW_ACTIVE" if astro_calc.get("harmonic_window") else "NO_WINDOW",
        }
    else:
        astro_block = {
            "_engine": "NOT_ACTIVE",
            "harmonic_window": False,
            "planet_event": "ENGINE_NOT_ACTIVE",
            "bias": "--",
            "reason": "ENGINE_DISABLED",
        }
    return gann_block, astro_block


router = APIRouter()
mentor_engine = MentorEngine()
mentor_gann_engine = MentorGannEngine()
mentor_astro_engine = MentorAstroEngine()

# Simple cache for mentor contexts (expires every 60 seconds)
_mentor_cache = {}
_cache_timestamps = {}
CACHE_TTL = 60

def _get_cached_context(symbol: str):
    """Get cached context if available and not expired"""
    if symbol in _mentor_cache:
        timestamp = _cache_timestamps.get(symbol, 0)
        if time.time() - timestamp < CACHE_TTL:
            return _mentor_cache[symbol]
    return None

def _set_cached_context(symbol: str, context: dict):
    """Cache context with timestamp"""
    _mentor_cache[symbol] = context
    _cache_timestamps[symbol] = time.time()

def _mentor_model_data(symbol: str, market_data: dict):
    htf = str(market_data.get("htf_bias", "NEUTRAL")).upper()
    ltf = str(market_data.get("ltf_structure", "RANGE")).upper()
    if htf == "BULLISH":
        reason = f"Bullish HTF bias with {ltf.lower()} LTF structure — watch long setups"
    elif htf == "BEARISH":
        reason = f"Bearish HTF bias with {ltf.lower()} LTF structure — watch short setups"
    else:
        reason = f"Neutral HTF bias, {ltf.lower()} structure — no directional edge, await confluence"
    entry_logic = "FVG + OB confluence" if ltf == "EXPANSION" else "Liquidity sweep + reversal"
    return {
        "name": "ICT",
        "confidence": 0.7,
        "reason": reason,
        "rr": 2.0,
        "invalid_if": False,
        "entry_logic": entry_logic,
        "exit": None,
    }

def _mentor_risk_data():
    return {
        "risk_percent": 0.5,
        "daily_buffer": 1000,
        "static_floor": 10000,
        "cooldown": 0,
    }

def _mentor_phase_data(symbol: str):
    return {"phase": "PHASE1", "prop_audit": {}, "last_trades": [], "model_stats": {}}, {}

@router.get("/mentor/context")
def mentor_context(symbol: str = "XAUUSD"):
    # Check cache first
    cached = _get_cached_context(symbol)
    if cached is not None:
        cached["cached"] = True
        cached["cache_ttl_remaining"] = int(CACHE_TTL - (time.time() - _cache_timestamps.get(symbol, 0)))
        return {"context": cached["context"]}
    
    from astroquant.backend.services.databento_utility import fetch_candles_unified
    error_msgs = []

    candles = []
    db_symbol = symbol
    fetch_meta = {}
    
    # Fetch with timeout handling
    try:
        candles, fetch_meta = fetch_candles_unified(symbol=symbol, limit=30)
        db_symbol = fetch_meta.get("resolved_symbol", symbol)
    except Exception as outer_e:
        error_msgs.append(f"Databento unified fetch error: {outer_e}")

    # Fallback: try to get live price from broker if Databento failed
    if not candles:
        live_price = None
        try:
            from astroquant.backend.main import runner as _runner
            lp, _ = _runner.get_live_price(symbol) if hasattr(_runner, "get_live_price") else (None, None)
            if lp and float(lp) > 0:
                live_price = float(lp)
        except Exception:
            pass
        base = live_price  # None if feed down — surfaces as N/A in UI rather than fake $2000
        if base is None:
            base = 0.0  # neutral sentinel; UI will show N/A for price=0
        candles = [
            {"open": base, "high": base * 1.0005, "low": base * 0.9995, "close": base, "volume": 1000}
            for _ in range(30)
        ]

    last_price = candles[-1]["close"] if candles else None
    
    # Use real context for model/risk/phase if possible
    try:
        htf_bias = mentor_engine.derive_htf_bias(candles)
        ltf_structure = mentor_engine.derive_ltf_structure(candles)
        iceberg = mentor_engine.derive_iceberg(candles)
    except Exception as e:
        error_msgs.append(f"Engine derivation error: {e}")
        htf_bias = "UNKNOWN"
        ltf_structure = "UNKNOWN"
        iceberg = {}
    
    session = _detect_session()
    volatility = _detect_volatility(candles)

    # Prev range from last 20 candles
    prev_low = None
    prev_high = None
    if candles:
        lows = [float(c.get("low", 0) or 0) for c in candles[-20:] if c.get("low")]
        highs = [float(c.get("high", 0) or 0) for c in candles[-20:] if c.get("high")]
        if lows:
            prev_low = min(lows)
        if highs:
            prev_high = max(highs)

    # Derive extra fields from candles
    liq_sweep  = _derive_liquidity_sweep(candles, prev_low, prev_high)
    ict_patterns = _derive_ict_patterns(candles)
    orderflow  = _derive_orderflow(candles, htf_bias)

    # Data staleness
    stale = False
    stale_hours = None
    if fetch_meta.get("window_end"):
        try:
            from dateutil import parser as _dp
            wend = _dp.parse(fetch_meta["window_end"])
            now_utc = datetime.now(timezone.utc)
            stale_hours = round((now_utc - wend).total_seconds() / 3600, 1)
            stale = stale_hours > 24
        except Exception:
            pass

    market_data = {
        "symbol": symbol,
        "canonical_symbol": db_symbol,
        "pricing_source": "DATABENTO",
        "spot_fidelity": {"spot_primary": False, "strict": False, "spot_data_available": True},
        "htf_bias": htf_bias,
        "ltf_structure": ltf_structure,
        "session": session,
        "volatility": volatility,
        "news_state": "NORMAL",
        "iceberg": iceberg,
    }
    gann_block, astro_block = _derive_engine_status_blocks(candles, market_data)
    
    # Model/risk/phase could be made dynamic here if more logic is available
    model_data = _mentor_model_data(symbol, market_data)
    risk_data = _mentor_risk_data()
    phase_data, exit_data = _mentor_phase_data(symbol)
    
    try:
        context = mentor_engine.build_context(market_data, model_data, risk_data, phase_data)
    except Exception as e:
        error_msgs.append(f"Context build error: {e}")
        context = {"error": str(e), "market": market_data}
    
    context["exit"] = exit_data
    context["updated_at"] = datetime.now(timezone.utc).isoformat()
    context["price"] = last_price
    context["prev_low"] = prev_low
    context["prev_high"] = prev_high
    context["cached"] = False
    context["liquidity_sweep"] = liq_sweep
    context["ict"] = ict_patterns
    context["orderflow"] = orderflow
    context["gann"] = gann_block
    context["astro"] = astro_block
    context["data_source"] = {
        "symbol": db_symbol,
        "records": fetch_meta.get("records", 0),
        "fallback_used": fetch_meta.get("fallback_used", False),
        "stale": stale,
        "stale_hours": stale_hours,
    }

    # Add narrative for concept drawers
    try:
        from astroquant.backend.journal.ai_trade_journal import generate_narrative
        context["narrative"] = generate_narrative(
            model_data["name"],
            market_data["volatility"],
            market_data["session"],
            market_data["news_state"],
            model_data["rr"],
            htf_bias=htf_bias,
            ltf_structure=ltf_structure,
        )
    except Exception as narrative_exc:
        context["narrative"] = f"NARRATIVE ERROR: {narrative_exc}"
    
    if fetch_meta:
        context["data_fetch"] = fetch_meta
    if error_msgs:
        context["errors"] = error_msgs
    
    # Cache the result
    _set_cached_context(symbol, {"context": context})
    
    return {"context": context}

@router.get("/mentor")
def mentor_v3(symbol: str = "XAUUSD"):
    context = mentor_context(symbol)
    v3_payload = dict(context)
    v3_payload["symbol"] = symbol
    return {"context": v3_payload}


@router.get("/ai/mentor")
def ai_mentor_alias(symbol: str = "XAUUSD"):
    """Compatibility alias for frontend mentor fetches."""
    return mentor_v3(symbol)
