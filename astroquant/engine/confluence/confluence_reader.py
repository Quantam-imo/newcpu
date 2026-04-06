"""
confluence_reader.py — stub reader for WebSocket confluence score streaming.
Returns multi-factor confluence scores derived from candle data.
"""
from __future__ import annotations


def get_confluence_scores(symbol: str) -> dict | None:
    """
    Return a confluence score dict or None if unavailable.
    Keys: overall, trend, momentum, volume, astro, ts
    """
    try:
        from astroquant.engine.candle.candle_reader import get_candle_series
        candles = get_candle_series(symbol, 1, limit=20)
        if not candles:
            return None
        closes = [float(c.get("close", 0)) for c in candles if c.get("close")]
        if len(closes) < 5:
            return None
        # Simple trend: last close vs 5-period MA
        ma5 = sum(closes[-5:]) / 5
        last = closes[-1]
        trend_score = min(100.0, max(0.0, 50.0 + (last - ma5) / ma5 * 1000))
        # Momentum: last 3 vs previous 3
        mom_score = min(100.0, max(0.0, 50.0 + (sum(closes[-3:]) - sum(closes[-6:-3])) / max(1, sum(closes[-6:-3])) * 500))
        # Volume: recent vs average
        vols = [float(c.get("volume", 0)) for c in candles]
        avg_vol = sum(vols) / len(vols) if vols else 0
        last_vol = vols[-1] if vols else 0
        vol_score = min(100.0, (last_vol / avg_vol) * 50.0) if avg_vol > 0 else 50.0
        overall = round((trend_score + mom_score + vol_score) / 3, 1)
        return {
            "symbol": symbol,
            "overall": overall,
            "trend": round(trend_score, 1),
            "momentum": round(mom_score, 1),
            "volume": round(vol_score, 1),
            "astro": 50.0,  # placeholder — populate from astro_signal if needed
            "ts": int(candles[-1].get("time", 0)),
        }
    except Exception:
        return None
