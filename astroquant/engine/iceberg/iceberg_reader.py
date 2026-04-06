"""
iceberg_reader.py — stub reader for WebSocket iceberg event streaming.
Returns absorption/iceberg events from candle data heuristics.
"""
from __future__ import annotations


def get_iceberg_events(symbol: str) -> list | None:
    """
    Return a list of detected iceberg/absorption events, or None if unavailable.
    Each event: {"price": float, "side": "BUY"|"SELL", "size": float, "ts": int}
    """
    try:
        from astroquant.engine.candle.candle_reader import get_candle_series
        candles = get_candle_series(symbol, 1, limit=20)
        if not candles:
            return None
        # Simple heuristic: large-wick candles with high volume signal absorption
        events = []
        for c in candles[-5:]:
            hi = float(c.get("high", 0))
            lo = float(c.get("low", 0))
            op = float(c.get("open", 0))
            cl = float(c.get("close", 0))
            vol = float(c.get("volume", 0))
            body = abs(cl - op)
            wick = (hi - lo) - body
            if vol > 0 and wick > body * 1.5:
                side = "BUY" if cl >= op else "SELL"
                events.append({
                    "price": round((hi + lo) / 2, 2),
                    "side": side,
                    "size": round(vol, 2),
                    "ts": int(c.get("time", 0)),
                })
        return events if events else None
    except Exception:
        return None
