"""
Rule-based Phase Labeler for the AstroQuant Wheel Model.

Produces a phase integer (0–3) for every bar using quantified rules.
This replaces guessing: every rule is explicit and testable.

Phases:
  0 = ACCUMULATION  – low volatility, range-bound, smart money building
  1 = MANIPULATION  – liquidity sweep / stop hunt / fake move
  2 = EXPANSION     – displacement candle, FVG forming, directional follow-through
  3 = DISTRIBUTION  – momentum waning, opposite liquidity forming, exhaustion

Usage:
    from backend.engines.phase_labeler import label_phases, phase_name

    df = label_phases(df)  # adds 'phase' and 'phase_name' columns
"""
from __future__ import annotations

import numpy as np
import pandas as pd


_PHASE_NAMES = {
    0: "ACCUMULATION",
    1: "MANIPULATION",
    2: "EXPANSION",
    3: "DISTRIBUTION",
}


def phase_name(code: int) -> str:
    return _PHASE_NAMES.get(int(code), "UNKNOWN")


# ---------------------------------------------------------------------------
# Core labeler (vectorised, no lookahead)
# ---------------------------------------------------------------------------

def label_phases(
    df: pd.DataFrame,
    atr_period: int = 14,
    vol_threshold_pct: float = 0.6,     # ATR < X% of rolling ATR mean → low vol
    sweep_window: int = 10,             # look-back for equal highs/lows
    sweep_tolerance_pct: float = 0.003, # equal within 0.3% of price
    displacement_body_pct: float = 1.3, # body > 1.3× ATR → displacement
    momentum_period: int = 5,
    momentum_strong_pct: float = 0.4,   # |close-close[n]| / ATR > threshold → strong
    dist_wick_ratio: float = 0.55,       # wick > 55% of range → exhaustion wick
    dist_lookback: int = 20,
) -> pd.DataFrame:
    """
    Vectorised rule-based phase labeler.

    Parameters
    ----------
    df : OHLCV DataFrame with columns: open, high, low, close, (volume optional)

    Returns
    -------
    df with additional columns: phase (int 0–3), phase_name (str)
    """
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    high = df["high"].astype(float)
    low  = df["low"].astype(float)
    close = df["close"].astype(float)
    open_ = df["open"].astype(float)

    # --- ATR ---
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / atr_period, adjust=False).mean()
    atr_mean = atr.rolling(atr_period * 2).mean().fillna(atr)

    # --- Body / wick ---
    body = (close - open_).abs()
    wick_upper = high - pd.concat([close, open_], axis=1).max(axis=1)
    wick_lower = pd.concat([close, open_], axis=1).min(axis=1) - low
    bar_range = (high - low).replace(0, np.nan).fillna(1e-9)

    # --- Volatility regime ---
    low_vol = atr < (atr_mean * vol_threshold_pct)

    # --- Liquidity sweep detection ---
    roll_high = high.shift(1).rolling(sweep_window).max()
    roll_low  = low.shift(1).rolling(sweep_window).min()
    tol = close * sweep_tolerance_pct

    sweep_high = (high > roll_high) & ((high - close) > tol * 0.5)   # wicked above & rejected
    sweep_low  = (low  < roll_low)  & ((close - low)  > tol * 0.5)   # wicked below & rejected

    manipulation = sweep_high | sweep_low

    # --- Displacement (Expansion trigger) ---
    body_ratio = body / atr.replace(0, np.nan).fillna(1)
    displacement = (body_ratio >= displacement_body_pct) & (
        # strong directional close
        ((close > open_) & (wick_upper / bar_range < 0.35)) |
        ((close < open_) & (wick_lower / bar_range < 0.35))
    )

    # --- Momentum strength ---
    mom = (close - close.shift(momentum_period)).abs() / atr.replace(0, np.nan).fillna(1)
    strong_momentum = mom >= momentum_strong_pct

    # --- Distribution (exhaustion) ---
    exhaustion_wick = (
        (wick_upper / bar_range > dist_wick_ratio) |
        (wick_lower / bar_range > dist_wick_ratio)
    )
    atr_declining = atr < atr.shift(3)
    distribution = exhaustion_wick & atr_declining & ~displacement

    # --- Priority labeling (manipulation overrides, then expansion, then distribution) ---
    # Start with accumulation for all bars
    n = len(df)
    phase = np.zeros(n, dtype=int)  # 0 = ACCUMULATION default

    # Phase 3 — Distribution (check first so manipulation can override)
    phase[distribution.to_numpy()] = 3

    # Phase 2 — Expansion
    phase[displacement.to_numpy() & strong_momentum.to_numpy()] = 2

    # Phase 1 — Manipulation (highest priority: overrides distribution/expansion)
    phase[manipulation.to_numpy()] = 1

    # Re-enforce: if low vol AND not manipulation → accumulation
    phase[(low_vol.to_numpy()) & ~manipulation.to_numpy()] = 0

    df["phase"] = phase
    df["phase_name"] = [_PHASE_NAMES[p] for p in phase]
    return df


def get_current_phase(df: pd.DataFrame, **kwargs) -> dict:
    """
    Return the phase of the LAST bar in df.
    Useful for live single-bar checks.
    """
    labeled = label_phases(df, **kwargs)
    last = labeled.iloc[-1]
    code = int(last["phase"])
    return {
        "phase_code": code,
        "phase_name": _PHASE_NAMES[code],
    }
