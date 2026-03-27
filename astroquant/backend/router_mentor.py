
from fastapi import APIRouter
from astroquant.backend.ai.mentor_engine import MentorEngine
from functools import lru_cache
import time
# Ensure .env variables are loaded through standard dotenv resolution.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

router = APIRouter()
mentor_engine = MentorEngine()

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
    return {
        "name": "ICT",
        "confidence": 0.7,
        "reason": "Stub reason",
        "rr": 2.0,
        "invalid_if": False,
        "entry_logic": "Stub entry logic",
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
    
    from datetime import datetime, timezone
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

    # Fallback to stub if no real candles
    if not candles:
        candles = [{"open": 2000, "high": 2010, "low": 1995, "close": 2005, "volume": 1000} for _ in range(30)]

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
    
    market_data = {
        "symbol": symbol,
        "canonical_symbol": db_symbol,
        "pricing_source": "DATABENTO",
        "spot_fidelity": {"spot_primary": False, "strict": False, "spot_data_available": True},
        "htf_bias": htf_bias,
        "ltf_structure": ltf_structure,
        "session": "US",
        "volatility": "NORMAL",
        "news_state": "NORMAL",
        "iceberg": iceberg,
    }
    
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
    context["cached"] = False
    
    # Add narrative for concept drawers
    try:
        from astroquant.backend.journal.ai_trade_journal import generate_narrative
        context["narrative"] = generate_narrative(
            model_data["name"],
            market_data["volatility"],
            market_data["session"],
            market_data["news_state"],
            model_data["rr"]
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
