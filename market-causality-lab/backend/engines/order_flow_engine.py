from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _safe_series(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series([default] * len(df), index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(default).astype(float)


def _bar_split_buy_sell_volume(open_p: float, high_p: float, low_p: float, close_p: float, volume: float) -> tuple[float, float]:
    """
    Estimate aggressive buy/sell volume split from OHLCV when true bid/ask tape
    is unavailable in historical datasets.

    Heuristic:
      - close location within bar range captures directional pressure,
      - body direction adds conviction,
      - resulting ratio is clipped to [0.1, 0.9] to avoid hard 0/1 extremes.
    """
    rng = max(1e-9, high_p - low_p)
    close_pos = max(0.0, min(1.0, (close_p - low_p) / rng))
    body_bias = 1.0 if close_p > open_p else (0.0 if close_p < open_p else 0.5)
    buy_ratio = max(0.1, min(0.9, 0.7 * close_pos + 0.3 * body_bias))
    buy_vol = max(0.0, float(volume) * buy_ratio)
    sell_vol = max(0.0, float(volume) - buy_vol)
    return buy_vol, sell_vol


def order_flow_engine(
    sub_df: pd.DataFrame,
    liquidity: dict[str, Any] | None = None,
    lookback: int = 30,
) -> dict[str, Any]:
    """
    Estimate directional order flow and iceberg absorption from OHLCV.

    Output is deterministic and works on 25-year historical OHLCV datasets where
    L2/order-book data is unavailable.
    """
    empty = {
        "buy_volume_est": 0.0,
        "sell_volume_est": 0.0,
        "volume_total": 0.0,
        "volume_zscore": 0.0,
        "flow_delta": 0.0,
        "flow_imbalance": 0.0,
        "delta_trend": 0.0,
        "aggressive_side": "NEUTRAL",
        "iceberg_detected": False,
        "iceberg_side": "NONE",
        "iceberg_absorption_score": 0.0,
        "absorption_type": "NONE",
        "flow_regime": "NEUTRAL",
    }
    if sub_df is None or sub_df.empty or len(sub_df) < 6:
        return empty

    df = sub_df.tail(max(lookback, 20)).copy()
    opens = _safe_series(df, "open")
    highs = _safe_series(df, "high")
    lows = _safe_series(df, "low")
    closes = _safe_series(df, "close")
    vols = _safe_series(df, "volume")

    buy_parts = []
    sell_parts = []
    for o, h, l, c, v in zip(opens, highs, lows, closes, vols):
        b, s = _bar_split_buy_sell_volume(float(o), float(h), float(l), float(c), float(v))
        buy_parts.append(b)
        sell_parts.append(s)

    buy_ser = pd.Series(buy_parts, index=df.index, dtype=float)
    sell_ser = pd.Series(sell_parts, index=df.index, dtype=float)
    delta_ser = buy_ser - sell_ser

    last_buy = float(buy_ser.iloc[-1])
    last_sell = float(sell_ser.iloc[-1])
    last_vol = max(1e-9, float(vols.iloc[-1]))
    flow_delta = float(last_buy - last_sell)
    flow_imbalance = float(flow_delta / last_vol)

    vol_window = vols.tail(20)
    vol_mean = float(vol_window.mean() or 0.0)
    vol_std = float(vol_window.std(ddof=0) or 0.0)
    volume_z = float((last_vol - vol_mean) / max(1e-9, vol_std)) if vol_std > 0 else 0.0

    delta_trend = float(delta_ser.tail(8).mean() or 0.0)

    if flow_imbalance >= 0.18:
        aggressive_side = "BUY"
    elif flow_imbalance <= -0.18:
        aggressive_side = "SELL"
    else:
        aggressive_side = "NEUTRAL"

    # Iceberg/absorption proxy: high volume + small body + rejection wick near
    # swept side implies hidden passive liquidity absorbing aggressive flow.
    o = float(opens.iloc[-1]); h = float(highs.iloc[-1]); l = float(lows.iloc[-1]); c = float(closes.iloc[-1])
    rng = max(1e-9, h - l)
    body = abs(c - o)
    upper_wick = max(0.0, h - max(o, c))
    lower_wick = max(0.0, min(o, c) - l)

    body_ratio = body / rng
    upper_wick_ratio = upper_wick / rng
    lower_wick_ratio = lower_wick / rng

    liq_type = str((liquidity or {}).get("type") or "NONE").upper()

    score = 0.0
    score += 0.35 if volume_z >= 1.0 else 0.0
    score += 0.25 if body_ratio <= 0.35 else 0.0

    iceberg_side = "NONE"
    absorption_type = "NONE"

    # Buy-side sweep + upper rejection + net sell pressure => sell iceberg absorption.
    if liq_type == "BUY_SIDE_SWEEP" and upper_wick_ratio >= 0.45 and flow_imbalance <= -0.08:
        score += 0.4
        iceberg_side = "SELL"
        absorption_type = "BUY_BREAKOUT_ABSORBED"

    # Sell-side sweep + lower rejection + net buy pressure => buy iceberg absorption.
    if liq_type == "SELL_SIDE_SWEEP" and lower_wick_ratio >= 0.45 and flow_imbalance >= 0.08:
        score += 0.4
        iceberg_side = "BUY"
        absorption_type = "SELL_BREAKDOWN_ABSORBED"

    iceberg_detected = bool(score >= 0.6)

    if iceberg_detected and iceberg_side in {"BUY", "SELL"}:
        flow_regime = f"ICEBERG_{iceberg_side}"
    elif aggressive_side in {"BUY", "SELL"} and abs(delta_trend) > 0:
        flow_regime = f"AGGRESSIVE_{aggressive_side}"
    else:
        flow_regime = "NEUTRAL"

    return {
        "buy_volume_est": round(last_buy, 4),
        "sell_volume_est": round(last_sell, 4),
        "volume_total": round(last_vol, 4),
        "volume_zscore": round(volume_z, 4),
        "flow_delta": round(flow_delta, 4),
        "flow_imbalance": round(flow_imbalance, 5),
        "delta_trend": round(delta_trend, 4),
        "aggressive_side": aggressive_side,
        "iceberg_detected": iceberg_detected,
        "iceberg_side": iceberg_side,
        "iceberg_absorption_score": round(float(max(0.0, min(1.0, score))), 4),
        "absorption_type": absorption_type,
        "flow_regime": flow_regime,
    }
