from fastapi import APIRouter
from astroquant.backend.ai.mentor_engine import MentorEngine

router = APIRouter()
mentor_engine = MentorEngine()

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
    candles = [{"open": 2000, "high": 2010, "low": 1995, "close": 2005, "volume": 1000} for _ in range(30)]
    last_price = candles[-1]["close"] if candles else None
    market_data = {
        "symbol": symbol,
        "canonical_symbol": symbol,
        "pricing_source": "DATABENTO",
        "spot_fidelity": {"spot_primary": False, "strict": False, "spot_data_available": True},
        "htf_bias": mentor_engine.derive_htf_bias(candles),
        "ltf_structure": mentor_engine.derive_ltf_structure(candles),
        "session": "US",
        "volatility": "NORMAL",
        "news_state": "NORMAL",
        "iceberg": mentor_engine.derive_iceberg(candles),
    }
    model_data = _mentor_model_data(symbol, market_data)
    risk_data = _mentor_risk_data()
    phase_data, exit_data = _mentor_phase_data(symbol)
    context = mentor_engine.build_context(market_data, model_data, risk_data, phase_data)
    context["exit"] = exit_data
    context["updated_at"] = "2026-03-18T00:00:00Z"
    context["price"] = last_price
    return {"context": context}

@router.get("/mentor")
def mentor_v3(symbol: str = "XAUUSD"):
    context = mentor_context(symbol)
    v3_payload = dict(context)
    v3_payload["symbol"] = symbol
    return {"context": v3_payload}
