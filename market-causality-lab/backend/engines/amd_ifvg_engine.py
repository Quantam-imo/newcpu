"""AMD + IFVG Distribution Strategy Engine.

Converted from Pine Script (LuxAlgo) to Python.
Implements: Accumulation → Manipulation → Distribution detection using
ATR-filtered range compression, stop-sweeps, and Inversion Fair Value Gap (IFVG) entries.

Usage (vectorised on a full OHLCV DataFrame):
    from backend.engines.amd_ifvg_engine import run_amd_ifvg, amd_ifvg_latest

    # Full history — returns a DataFrame with signal columns
    result_df = run_amd_ifvg(df, lookback=20, atr_length=14, atr_mult=1.5, min_fvg_pct=0.0)

    # Live single-bar check — returns a dict with the latest signal
    signal = amd_ifvg_latest(df, lookback=20, atr_length=14, atr_mult=1.5, min_fvg_pct=0.0)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    """Classic Wilder ATR via pandas."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False).mean()


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

@dataclass
class _FVG:
    top: float
    bottom: float
    bar_index: int
    is_bull: bool


def run_amd_ifvg(
    df: pd.DataFrame,
    *,
    lookback: int = 20,
    atr_length: int = 14,
    atr_mult: float = 1.5,
    min_fvg_pct: float = 0.0,
) -> pd.DataFrame:
    """Vectorised AMD + IFVG scan over a full OHLCV history.

    Parameters
    ----------
    df : DataFrame with lowercase columns: open, high, low, close (and optionally time).
    lookback : Accumulation lookback bars.
    atr_length : ATR period for range-validity filter.
    atr_mult : Maximum allowed range as multiple of ATR.
    min_fvg_pct : Minimum FVG size as fraction of close price (0.001 = 0.1%).

    Returns
    -------
    Original DataFrame augmented with columns:
        amd_bull_entry    bool  — bullish IFVG entry signal
        amd_bear_entry    bool  — bearish IFVG entry signal
        amd_sl            float — stop-loss price (NaN when no active signal)
        amd_tp            float — take-profit price (NaN when no active signal)
        amd_entry_top     float — IFVG top of entry zone
        amd_entry_bot     float — IFVG bottom of entry zone
        amd_phase         str   — 'ACCUMULATION' | 'MANIPULATION_BULL' |
                                  'MANIPULATION_BEAR' | 'DISTRIBUTION' | 'NONE'
        amd_acc_hh        float — rolling highest-high of accumulation window
        amd_acc_ll        float — rolling lowest-low of accumulation window
        amd_atr           float — ATR value
    """
    df = df.copy()
    # Normalise column names
    df.columns = [c.lower() for c in df.columns]
    needed = {"open", "high", "low", "close"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"amd_ifvg_engine: missing columns {missing}")

    n = len(df)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)

    atr_series = _atr(df["high"], df["low"], df["close"], atr_length).to_numpy(dtype=float)

    acc_hh_arr = df["high"].rolling(lookback).max().to_numpy(dtype=float)
    acc_ll_arr = df["low"].rolling(lookback).min().to_numpy(dtype=float)

    # Output arrays
    bull_entry = np.zeros(n, dtype=bool)
    bear_entry = np.zeros(n, dtype=bool)
    sl_arr = np.full(n, np.nan)
    tp_arr = np.full(n, np.nan)
    entry_top_arr = np.full(n, np.nan)
    entry_bot_arr = np.full(n, np.nan)
    phase_arr = np.array(["NONE"] * n, dtype=object)
    acc_hh_out = acc_hh_arr.copy()
    acc_ll_out = acc_ll_arr.copy()

    # --- State machine (mirrors Pine Script var declarations) ---
    static_hh: float = np.nan
    static_ll: float = np.nan
    acc_start: int = 0
    manipulating_bull: bool = False
    manipulating_bear: bool = False
    manip_extreme: float = np.nan

    active_fvgs: list[_FVG] = []

    for i in range(max(lookback, atr_length, 3), n):
        atr_val = atr_series[i]
        acc_hh = acc_hh_arr[i - 1]  # [1] in Pine = previous bar's rolling value
        acc_ll = acc_ll_arr[i - 1]
        acc_height = acc_hh - acc_ll
        atr_prev = atr_series[i - 1]

        is_range_valid_prev = (acc_hh - acc_ll) <= (atr_prev * atr_mult)

        # Strong candle filters
        candle_range = high[i] - low[i]
        body = abs(close[i] - open_[i])
        is_strong_bull = (
            candle_range > 0
            and close[i] > (high[i] - candle_range * 0.25)
            and body > candle_range * 0.5
        )
        is_strong_bear = (
            candle_range > 0
            and close[i] < (low[i] + candle_range * 0.25)
            and body > candle_range * 0.5
        )

        # --- Manipulation detection ---
        break_low = (
            low[i] < acc_ll
            and is_range_valid_prev
            and not manipulating_bull
            and not manipulating_bear
        )
        break_high = (
            high[i] > acc_hh
            and is_range_valid_prev
            and not manipulating_bear
            and not manipulating_bull
        )

        if break_low:
            manipulating_bull = True
            static_hh = acc_hh
            static_ll = acc_ll
            acc_start = i - lookback
            manip_extreme = low[i]

        if break_high:
            manipulating_bear = True
            static_hh = acc_hh
            static_ll = acc_ll
            acc_start = i - lookback
            manip_extreme = high[i]

        # Track manipulation extremes
        if manipulating_bull:
            manip_extreme = min(manip_extreme, low[i])
        if manipulating_bear:
            manip_extreme = max(manip_extreme, high[i])

        # --- FVG detection (requires i >= 2) ---
        bull_fvg = low[i] > high[i - 2] and (low[i] - high[i - 2]) > close[i] * min_fvg_pct
        bear_fvg = high[i] < low[i - 2] and (low[i - 2] - high[i]) > close[i] * min_fvg_pct

        if bull_fvg:
            active_fvgs.append(_FVG(top=low[i], bottom=high[i - 2], bar_index=i - 1, is_bull=True))
        if bear_fvg:
            active_fvgs.append(_FVG(top=low[i - 2], bottom=high[i], bar_index=i - 1, is_bull=False))

        # --- Entry detection ---
        if manipulating_bull and is_strong_bull:
            for j in range(len(active_fvgs) - 1, -1, -1):
                f = active_fvgs[j]
                if f.bar_index >= acc_start and not f.is_bull and close[i] > f.top:
                    bull_entry[i] = True
                    sl_arr[i] = manip_extreme
                    tp_arr[i] = static_hh
                    entry_top_arr[i] = f.top
                    entry_bot_arr[i] = f.bottom
                    active_fvgs.pop(j)
                    manipulating_bull = False
                    break

        if manipulating_bear and is_strong_bear:
            for j in range(len(active_fvgs) - 1, -1, -1):
                f = active_fvgs[j]
                if f.bar_index >= acc_start and f.is_bull and close[i] < f.bottom:
                    bear_entry[i] = True
                    sl_arr[i] = manip_extreme
                    tp_arr[i] = static_ll
                    entry_top_arr[i] = f.top
                    entry_bot_arr[i] = f.bottom
                    active_fvgs.pop(j)
                    manipulating_bear = False
                    break

        # Phase label
        if bull_entry[i] or bear_entry[i]:
            phase_arr[i] = "DISTRIBUTION"
        elif manipulating_bull:
            phase_arr[i] = "MANIPULATION_BULL"
        elif manipulating_bear:
            phase_arr[i] = "MANIPULATION_BEAR"
        else:
            is_range_valid_now = (acc_hh_arr[i] - acc_ll_arr[i]) <= (atr_val * atr_mult)
            phase_arr[i] = "ACCUMULATION" if is_range_valid_now else "NONE"

        # Cap FVG list (prevent unbounded growth)
        if len(active_fvgs) > 100:
            active_fvgs = active_fvgs[-100:]

    df["amd_bull_entry"] = bull_entry
    df["amd_bear_entry"] = bear_entry
    df["amd_sl"] = sl_arr
    df["amd_tp"] = tp_arr
    df["amd_entry_top"] = entry_top_arr
    df["amd_entry_bot"] = entry_bot_arr
    df["amd_phase"] = phase_arr
    df["amd_acc_hh"] = acc_hh_out
    df["amd_acc_ll"] = acc_ll_out
    df["amd_atr"] = atr_series

    return df


def amd_ifvg_latest(
    df: pd.DataFrame,
    *,
    lookback: int = 20,
    atr_length: int = 14,
    atr_mult: float = 1.5,
    min_fvg_pct: float = 0.0,
) -> dict[str, Any]:
    """Run the engine and return only the latest bar's signal as a dict.

    Convenient for live/streaming calls where you only need the current state.

    Returns
    -------
    {
        "signal":       "BULL" | "BEAR" | "NONE",
        "phase":        str,
        "sl":           float | None,
        "tp":           float | None,
        "entry_top":    float | None,
        "entry_bot":    float | None,
        "rr_ratio":     float | None,   # abs(tp - entry_mid) / abs(sl - entry_mid)
        "acc_hh":       float,
        "acc_ll":       float,
        "atr":          float,
    }
    """
    result = run_amd_ifvg(df, lookback=lookback, atr_length=atr_length,
                          atr_mult=atr_mult, min_fvg_pct=min_fvg_pct)
    last = result.iloc[-1]

    signal = "NONE"
    if bool(last.get("amd_bull_entry")):
        signal = "BULL"
    elif bool(last.get("amd_bear_entry")):
        signal = "BEAR"

    sl = float(last["amd_sl"]) if not pd.isna(last["amd_sl"]) else None
    tp = float(last["amd_tp"]) if not pd.isna(last["amd_tp"]) else None
    entry_top = float(last["amd_entry_top"]) if not pd.isna(last["amd_entry_top"]) else None
    entry_bot = float(last["amd_entry_bot"]) if not pd.isna(last["amd_entry_bot"]) else None

    rr_ratio = None
    if sl is not None and tp is not None and entry_top is not None and entry_bot is not None:
        entry_mid = (entry_top + entry_bot) / 2.0
        risk = abs(entry_mid - sl)
        reward = abs(tp - entry_mid)
        rr_ratio = round(reward / risk, 2) if risk > 0 else None

    return {
        "signal": signal,
        "phase": str(last["amd_phase"]),
        "sl": sl,
        "tp": tp,
        "entry_top": entry_top,
        "entry_bot": entry_bot,
        "rr_ratio": rr_ratio,
        "acc_hh": float(last["amd_acc_hh"]) if not pd.isna(last["amd_acc_hh"]) else None,
        "acc_ll": float(last["amd_acc_ll"]) if not pd.isna(last["amd_acc_ll"]) else None,
        "atr": float(last["amd_atr"]) if not pd.isna(last["amd_atr"]) else None,
    }


def amd_ifvg_summary(
    df: pd.DataFrame,
    *,
    lookback: int = 20,
    atr_length: int = 14,
    atr_mult: float = 1.5,
    min_fvg_pct: float = 0.0,
) -> dict[str, Any]:
    """Run full history scan and return summary statistics for MCL dashboard.

    Returns
    -------
    {
        "latest":           dict   — from amd_ifvg_latest()
        "total_bull":       int    — total bull entries in dataset
        "total_bear":       int    — total bear entries in dataset
        "avg_rr_bull":      float  — average R:R for bull entries
        "avg_rr_bear":      float  — average R:R for bear entries
        "recent_signals":  list   — last 5 entry signals with bar info
    }
    """
    result = run_amd_ifvg(df, lookback=lookback, atr_length=atr_length,
                          atr_mult=atr_mult, min_fvg_pct=min_fvg_pct)

    bull_rows = result[result["amd_bull_entry"]]
    bear_rows = result[result["amd_bear_entry"]]

    def _rr(row: pd.Series) -> float | None:
        sl = row["amd_sl"]
        tp = row["amd_tp"]
        et = row["amd_entry_top"]
        eb = row["amd_entry_bot"]
        if any(pd.isna(v) for v in (sl, tp, et, eb)):
            return None
        em = (et + eb) / 2.0
        risk = abs(em - sl)
        if risk == 0:
            return None
        return abs(tp - em) / risk

    def _rr_list(rows: pd.DataFrame) -> list[float]:
        return [r for r in rows.apply(_rr, axis=1) if r is not None]

    bull_rr = _rr_list(bull_rows)
    bear_rr = _rr_list(bear_rows)

    def _to_signal_row(row: pd.Series, direction: str) -> dict:
        time_val = None
        if "time" in row.index:
            t = row["time"]
            time_val = int(t.timestamp()) if hasattr(t, "timestamp") else str(t)
        sl = float(row["amd_sl"]) if not pd.isna(row["amd_sl"]) else None
        tp = float(row["amd_tp"]) if not pd.isna(row["amd_tp"]) else None
        et = float(row["amd_entry_top"]) if not pd.isna(row["amd_entry_top"]) else None
        eb = float(row["amd_entry_bot"]) if not pd.isna(row["amd_entry_bot"]) else None
        rr = None
        if sl and tp and et and eb:
            em = (et + eb) / 2.0
            risk = abs(em - sl)
            rr = round(abs(tp - em) / risk, 2) if risk > 0 else None
        return {
            "direction": direction,
            "time": time_val,
            "close": float(row["close"]),
            "sl": sl,
            "tp": tp,
            "entry_top": et,
            "entry_bot": eb,
            "rr_ratio": rr,
        }

    all_entries = pd.concat([
        bull_rows.assign(_dir="BULL"),
        bear_rows.assign(_dir="BEAR"),
    ]).sort_index().tail(5)

    recent = [_to_signal_row(row, row["_dir"]) for _, row in all_entries.iterrows()]

    latest = amd_ifvg_latest(df, lookback=lookback, atr_length=atr_length,
                             atr_mult=atr_mult, min_fvg_pct=min_fvg_pct)

    return {
        "latest": latest,
        "total_bull": int(len(bull_rows)),
        "total_bear": int(len(bear_rows)),
        "avg_rr_bull": round(float(np.mean(bull_rr)), 2) if bull_rr else None,
        "avg_rr_bear": round(float(np.mean(bear_rr)), 2) if bear_rr else None,
        "recent_signals": recent,
    }
