from fastapi import APIRouter, Query
from typing import Any
from astroquant.backend.runtime import get_runner, normalize_runtime_symbol

router = APIRouter()

# Endpoint: /spread_offset_history
@router.get("/spread_offset_history")
@router.get("/api/spread_offset_history")
def get_spread_offset_history(
    symbol: str = Query("XAUUSD", description="Symbol, e.g. XAUUSD, NQ, EURUSD, BTC, US30"),
    lookback_minutes: int = Query(240, description="Lookback window in minutes (default 240, max 4320)"),
) -> Any:
    canonical_symbol = normalize_runtime_symbol(symbol)
    runner = get_runner()
    market_data = runner.get_market_data(canonical_symbol) or {}
    # Get broker/spot tick candles
    spot_candles = runner._spot_candles_from_ticks(canonical_symbol, lookback_minutes=lookback_minutes)
    # Get basis (spread/offset) history
    basis_snap = runner.get_basis_snapshot(canonical_symbol)
    offset_guard = runner.offset_guard_snapshot(canonical_symbol, basis_snapshot=basis_snap)
    broker_quote = runner.get_broker_spot_quote(canonical_symbol) or {}
    return {
        "symbol": canonical_symbol,
        "spot_candles": spot_candles,
        "basis": basis_snap,
        "offset_guard": offset_guard,
        "broker_quote": broker_quote.get("snapshot") or {},
        "signal_detection": {
            "count": len(list(market_data.get("absorption_levels") or [])),
            "absorption": bool(market_data.get("absorption_levels")),
        },
        "meta": {
            "lookback_minutes": lookback_minutes,
            "count": len(spot_candles),
        },
    }
