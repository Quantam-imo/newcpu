"""
delta_reader.py — lightweight reader for WebSocket delta streaming.
Returns delta_percent in [-1, 1] from candle volume data.
"""
from __future__ import annotations


def get_delta_percent(symbol: str) -> float | None:
    """
    Compute buy/sell delta percent from recent candle data.
    Returns a float in [-1.0, 1.0] or None if unavailable.
    """
    try:
        from astroquant.engine.candle.candle_reader import get_candle_series
        candles = get_candle_series(symbol, 1, limit=30)
        if not candles:
            return None
        buy_vol = sum(float(c.get("volume", 0)) for c in candles if float(c.get("close", 0)) >= float(c.get("open", 0)))
        sell_vol = sum(float(c.get("volume", 0)) for c in candles if float(c.get("close", 0)) < float(c.get("open", 0)))
        total = buy_vol + sell_vol
        if total <= 0:
            return None
        return round((buy_vol - sell_vol) / total, 4)
    except Exception:
        return None
