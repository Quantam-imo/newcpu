"""Adaptive Time-Scale Engine — detect market speed regime and recommend timeframe."""
from __future__ import annotations

import numpy as np


def detect_volatility_regime(df, lookback: int = 20) -> dict:
    """
    Classify current market speed as SLOW | NORMAL | FAST using ATR ratio.
    Compares recent ATR vs baseline ATR from the earlier part of the dataset.
    """
    closes = df["close"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)

    if len(closes) < lookback + 10:
        return {
            "regime": "UNKNOWN",
            "recent_atr": 0.0,
            "baseline_atr": 0.0,
            "speed_ratio": 1.0,
            "recommendation": "CURRENT_TF_OK",
        }

    # True Range
    tr = np.maximum(highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1]))
    tr = np.maximum(tr, np.abs(lows[1:] - closes[:-1]))

    recent_atr = float(np.mean(tr[-lookback:]))
    baseline_atr = float(np.mean(tr[: -lookback])) if len(tr) > lookback else recent_atr
    if baseline_atr == 0:
        baseline_atr = recent_atr

    speed_ratio = round(recent_atr / baseline_atr, 3)

    if speed_ratio > 1.5:
        regime = "FAST"
        recommendation = "USE_SHORTER_TF"
    elif speed_ratio < 0.65:
        regime = "SLOW"
        recommendation = "USE_LONGER_TF"
    else:
        regime = "NORMAL"
        recommendation = "CURRENT_TF_OK"

    return {
        "regime": regime,
        "recent_atr": round(recent_atr, 4),
        "baseline_atr": round(baseline_atr, 4),
        "speed_ratio": speed_ratio,
        "recommendation": recommendation,
    }


def detect_time_compression(df, window: int = 10) -> dict:
    """
    Detect price compression (tight range) that often precedes a breakout.
    Compression score approaches 1.0 as range shrinks toward zero.
    """
    if len(df) < window * 2:
        return {
            "compressed": False,
            "compression_score": 0.0,
            "recent_range": 0.0,
            "prior_range": 0.0,
            "breakout_risk": "LOW",
        }

    recent_range = float(
        (df["high"].tail(window) - df["low"].tail(window)).mean()
    )
    prior_slice = df.tail(window * 2).head(window)
    prior_range = float((prior_slice["high"] - prior_slice["low"]).mean())

    if prior_range == 0:
        return {
            "compressed": False,
            "compression_score": 0.0,
            "recent_range": recent_range,
            "prior_range": prior_range,
            "breakout_risk": "LOW",
        }

    ratio = recent_range / prior_range
    compressed = ratio < 0.60
    compression_score = round(max(0.0, 1.0 - ratio), 4)

    return {
        "compressed": compressed,
        "compression_score": compression_score,
        "recent_range": round(recent_range, 4),
        "prior_range": round(prior_range, 4),
        "breakout_risk": "HIGH" if compressed else "LOW",
    }


def adaptive_timescale_analysis(state: dict, df) -> dict:
    """
    Combined time-scale analysis: volatility regime + compression detection.
    Returns signal_modifier: NORMAL | REDUCE_POSITION | BREAKOUT_WATCH.
    """
    regime = detect_volatility_regime(df)
    compression = detect_time_compression(df)

    if regime["regime"] == "FAST":
        signal_modifier = "REDUCE_POSITION"
    elif compression["compressed"]:
        signal_modifier = "BREAKOUT_WATCH"
    else:
        signal_modifier = "NORMAL"

    return {
        "volatility_regime": regime,
        "time_compression": compression,
        "signal_modifier": signal_modifier,
    }
