"""
dom_lite_reader.py — stub reader for WebSocket DOM Lite streaming.
Returns bid/ask spread approximation from recent candle data.
"""
from __future__ import annotations


def get_dom_lite(symbol: str) -> dict | None:
    """
    Return a lightweight DOM snapshot dict or None if unavailable.
    Keys: bids, asks, spread, imbalance_side, ts
    """
    try:
        from astroquant.engine.candle.candle_reader import get_candle_series
        candles = get_candle_series(symbol, 1, limit=5)
        if not candles:
            return None
        last = candles[-1]
        hi = float(last.get("high", 0))
        lo = float(last.get("low", 0))
        cl = float(last.get("close", 0))
        spread = round(hi - lo, 2)
        mid = round((hi + lo) / 2, 2)
        tick = round(spread / 10, 2) if spread > 0 else 0.1
        bids = [{"price": round(mid - tick * i, 2), "size": round(100 - i * 8, 0)} for i in range(1, 6)]
        asks = [{"price": round(mid + tick * i, 2), "size": round(100 - i * 8, 0)} for i in range(1, 6)]
        return {
            "symbol": symbol,
            "bids": bids,
            "asks": asks,
            "spread": spread,
            "mid": mid,
            "imbalance_side": "BUY" if cl >= mid else "SELL",
            "ts": int(last.get("time", 0)),
        }
    except Exception:
        return None
