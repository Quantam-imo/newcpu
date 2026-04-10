"""Adaptive Time-Scale Engine — detect market speed regime and recommend timeframe."""
from __future__ import annotations

import numpy as np
from backend.engines.time_compression_engine import time_compression_engine


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


def adaptive_timescale_analysis(state: dict, df) -> dict:
    """
    Combined time-scale analysis: volatility regime + full time compression.
    signal_modifier:
      NORMAL          — no compression, trade as usual
      REDUCE_POSITION — fast/expanding regime, size down
      BREAKOUT_WATCH  — price+cycle+vol contracting, await node break
      SILENCE_ALERT   — maximum compression (silence phase), breakout imminent
    """
    regime      = detect_volatility_regime(df)
    compression = time_compression_engine(df)   # full 3-layer engine

    if compression["phase"] == "SILENT":
        signal_modifier = "SILENCE_ALERT"
    elif compression["breakout_near"] or compression["phase"] == "CONTRACTING":
        signal_modifier = "BREAKOUT_WATCH"
    elif regime["regime"] == "FAST" or compression["phase"] == "EXPANDING":
        signal_modifier = "REDUCE_POSITION"
    else:
        signal_modifier = "NORMAL"

    return {
        "volatility_regime":  regime,
        "time_compression":   compression,
        "signal_modifier":    signal_modifier,
    }
