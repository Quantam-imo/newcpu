"""
Regime Detector — AstroQuant Market Regime Clustering.

Uses a k-means-style threshold clustering on (ATR, trend_strength, volatility_z)
to classify the market into one of 4 regimes:
    TREND_STRONG   – directional, high momentum, increasing ATR
    TREND_WEAK     – directional but slowing, ATR flattening
    RANGE          – low ATR, oscillating close, no clear direction
    HIGH_VOL_NOISE – spike / news event: ATR spike but no clean direction

Each regime has an associated confidence weight that the decision engine uses
to scale factor scores up or down.

Usage:
    from backend.engines.regime_detector import detect_regime

    result = detect_regime(df)
    # → {"regime": "TREND_STRONG", "confidence": 0.82,
    #    "decision_weight": 1.25, "atr_z": 1.1, "trend_z": 0.9}
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Confidence weight modifiers applied to the confluence decision engine
# > 1.0 means "trust signals more in this regime"
# < 1.0 means "require more confluence before acting"
_REGIME_WEIGHTS = {
    "TREND_STRONG":  1.25,
    "TREND_WEAK":    1.00,
    "RANGE":         0.75,
    "HIGH_VOL_NOISE": 0.50,
}


def detect_regime(
    df: pd.DataFrame,
    atr_period: int = 14,
    trend_period: int = 20,
    lookback: int = 5,
) -> dict:
    """
    Classify the current market regime from OHLCV history.

    Parameters
    ----------
    df           : OHLCV DataFrame (at least 40 rows recommended)
    atr_period   : period for ATR calculation
    trend_period : period for trend strength measurement (EMA slope)
    lookback     : bars used to determine regime momentum direction

    Returns
    -------
    dict with keys: regime, confidence, decision_weight,
                    atr_z, trend_z, vol_z, atr_current, atr_mean
    """
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    high  = df["high"].astype(float)
    low   = df["low"].astype(float)
    close = df["close"].astype(float)

    # --- ATR ---
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / atr_period, adjust=False).mean()

    atr_mean = atr.rolling(atr_period * 3).mean()
    atr_std  = atr.rolling(atr_period * 3).std().fillna(1e-9)

    # Z-score of current ATR vs recent history
    atr_z = float((atr.iloc[-1] - atr_mean.iloc[-1]) / max(atr_std.iloc[-1], 1e-9))

    # --- Trend strength: slope of EMA ---
    ema = close.ewm(span=trend_period, adjust=False).mean()
    ema_slope = (ema.iloc[-1] - ema.iloc[-lookback]) / max(atr.iloc[-1], 1e-9)
    trend_z = float(ema_slope)

    # --- Directional consistency (% of last N bars closing in same direction) ---
    direction = np.sign(close.diff().dropna().iloc[-lookback:].values)
    dir_consistency = float(abs(direction.sum()) / max(len(direction), 1))

    # --- ATR trending up or down ---
    atr_rising = bool(atr.iloc[-1] > atr.iloc[-lookback])

    # --- Classification rules (order matters: most specific first) ---
    regime: str
    confidence: float

    if atr_z > 1.5 and dir_consistency < 0.5:
        # Big ATR spike but no clean direction → chaotic
        regime = "HIGH_VOL_NOISE"
        confidence = min(0.95, 0.60 + abs(atr_z) * 0.1)

    elif abs(trend_z) >= 1.5 and dir_consistency >= 0.65 and atr_rising:
        # Strong trend with ATR expanding
        regime = "TREND_STRONG"
        confidence = min(0.95, 0.60 + dir_consistency * 0.35)

    elif abs(trend_z) >= 0.5 and dir_consistency >= 0.50:
        # Trending but losing steam
        regime = "TREND_WEAK"
        confidence = min(0.90, 0.50 + dir_consistency * 0.30)

    else:
        # Low ATR, no clear direction → ranging
        regime = "RANGE"
        confidence = min(0.90, 0.55 + (1.0 - dir_consistency) * 0.30)

    return {
        "regime": regime,
        "confidence": round(confidence, 3),
        "decision_weight": _REGIME_WEIGHTS[regime],
        "atr_z": round(atr_z, 3),
        "trend_z": round(trend_z, 3),
        "dir_consistency": round(dir_consistency, 3),
        "atr_current": round(float(atr.iloc[-1]), 4),
        "atr_mean": round(float(atr_mean.iloc[-1]) if not np.isnan(atr_mean.iloc[-1]) else float(atr.iloc[-1]), 4),
    }


def regime_weight(regime_result: dict) -> float:
    """Convenience: return only the decision_weight from a detect_regime() result."""
    return float(regime_result.get("decision_weight", 1.0))
