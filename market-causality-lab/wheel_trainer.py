"""
wheel_trainer.py — Fit the WheelTransitionModel from historical OHLCV data.

Reads price history for all available timeframes, runs the phase labeler,
builds the transition matrix conditioned on market context
(regime/volatility/liquidity/absorption), and saves the fitted model to:
    data/ai_models/wheel_transition.json

Usage:
    python wheel_trainer.py [--timeframe 1d] [--all]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Resolve project root
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

from backend.engines.phase_labeler import label_phases
from backend.engines.transition_model import WheelTransitionModel

_SAVE_PATH = ROOT / "data" / "ai_models" / "wheel_transition.json"

_TIMEFRAME_FILES = {
    "1d":  "data/XAU_1d_data.csv",
    "4h":  "data/XAU_4h_data.csv",
    "1h":  "data/XAU_1h_data.csv",
    "30m": "data/XAU_30m_data.csv",
    "15m": "data/XAU_15m_data.csv",
    "5m":  "data/XAU_5m_data.csv",
    "1w":  "data/XAU_1w_data.csv",
}


def _load_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        # Try semicolon-delimited first (MetaTrader export format)
        df = pd.read_csv(path, sep=";", index_col=0)
        df.columns = [c.lower() for c in df.columns]
        required = {"open", "high", "low", "close"}
        if not required.issubset(set(df.columns)):
            # Fall back to comma-delimited
            df = pd.read_csv(path, index_col=0)
            df.columns = [c.lower() for c in df.columns]
        if not required.issubset(set(df.columns)):
            return None
        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
        df = df.dropna(subset=list(required))
        idx = pd.to_datetime(df.index, errors="coerce", utc=True)
        df = df.loc[~idx.isna()].copy()
        df.index = idx[~idx.isna()]
        df = df.sort_index()
        # Filter out placeholder rows (all OHLC == 1.25 = MetaTrader filler)
        filler = (df["open"] == df["high"]) & (df["high"] == df["low"]) & (df["low"] == df["close"])
        df = df[~filler]
        if len(df) < 50:
            return None
        return df
    except Exception as e:
        print(f"  [WARN] Could not load {path}: {e}")
        return None


def _volatility_bucket(atr_z: float) -> str:
    if atr_z > 1.5:
        return "HIGH_VOL"
    if atr_z < 0.5:
        return "LOW_VOL"
    return "MED_VOL"


def _regime_label(momentum_12: float, atr_z: float) -> str:
    if atr_z > 1.8:
        return "VOLATILE"
    if abs(momentum_12) >= 0.008:
        return "TREND"
    return "RANGE"


def _absorption_strength_bucket(absorption_score: float, flow_imbalance: float) -> str:
    absorption_mag = max(abs(absorption_score), abs(flow_imbalance))
    if absorption_mag >= 0.75:
        return "ABSORB_HIGH"
    if absorption_mag >= 0.40:
        return "ABSORB_MED"
    return "ABSORB_LOW"


def _build_context_keys(labeled: pd.DataFrame) -> list[str] | None:
    if labeled is None or labeled.empty:
        return None

    open_ = pd.to_numeric(labeled.get("open"), errors="coerce")
    high = pd.to_numeric(labeled.get("high"), errors="coerce")
    low = pd.to_numeric(labeled.get("low"), errors="coerce")
    close = pd.to_numeric(labeled.get("close"), errors="coerce")
    if any(series is None for series in (open_, high, low, close)):
        return None

    span = (high - low).replace(0.0, np.nan)
    body = (close - open_).abs()
    up_wick = high - np.maximum(open_, close)
    down_wick = np.minimum(open_, close) - low

    # Sweep proxy from wick rejection structure.
    sweep_sell = (down_wick / span >= 0.45) & (close > open_)
    sweep_buy = (up_wick / span >= 0.45) & (close < open_)
    liq_state = np.where((sweep_sell | sweep_buy).fillna(False), "SWEEP", "NO_SWEEP")

    flow_imbalance = (close - open_) / span
    flow_imbalance = flow_imbalance.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    # Absorption score from wick-heavy candles, boosted by relative volume when present.
    absorption_base = (1.0 - (body / span)).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    if "volume" in labeled.columns:
        volume = pd.to_numeric(labeled.get("volume"), errors="coerce").fillna(0.0)
        vol_mu = volume.rolling(24, min_periods=8).mean()
        vol_sigma = volume.rolling(24, min_periods=8).std(ddof=0).replace(0.0, np.nan)
        vol_z = ((volume - vol_mu) / vol_sigma).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        absorption_score = absorption_base * (1.0 + vol_z.clip(lower=0.0))
    else:
        absorption_score = absorption_base

    absorption_side = np.where(
        (sweep_sell.fillna(False) & (absorption_score >= 0.35)),
        "BUY",
        np.where(
            (sweep_buy.fillna(False) & (absorption_score >= 0.35)),
            "SELL",
            np.where(flow_imbalance > 0.18, "BUY", np.where(flow_imbalance < -0.18, "SELL", "NEUTRAL")),
        ),
    )

    returns = close.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    momentum_12 = close.pct_change(12).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    atr = span.fillna(0.0)
    atr_mu = atr.rolling(24, min_periods=8).mean()
    atr_sigma = atr.rolling(24, min_periods=8).std(ddof=0).replace(0.0, np.nan)
    atr_z = ((atr - atr_mu) / atr_sigma).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    context_keys: list[str] = []
    for i in range(len(labeled)):
        regime = _regime_label(float(momentum_12.iloc[i]), float(atr_z.iloc[i]))
        vol_bucket = _volatility_bucket(float(atr_z.iloc[i]))
        liq = str(liq_state[i])
        abs_side = str(absorption_side[i])
        abs_strength = _absorption_strength_bucket(
            float(absorption_score.iloc[i]),
            float(returns.iloc[i]),
        )
        context = WheelTransitionModel.build_context_key(
            regime=regime,
            volatility_bucket=vol_bucket,
            liquidity_state=liq,
            absorption_side=abs_side,
            absorption_strength=abs_strength,
        )
        context_keys.append(context or "")

    return context_keys


def fit_from_dataframe(df: pd.DataFrame, timeframe: str = "") -> tuple[WheelTransitionModel, int]:
    """Label phases and fit transition model; return (model, n_transitions)."""
    labeled = label_phases(df)
    phases = labeled["phase"].tolist()
    context_keys = _build_context_keys(labeled)

    wm = WheelTransitionModel()
    wm.fit(phases, context_keys=context_keys)
    return wm, len(phases) - 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit Wheel Transition Model")
    parser.add_argument("--timeframe", default="", help="Single timeframe key (e.g. 4h). Empty = all.")
    parser.add_argument("--all", action="store_true", help="Fit on all timeframes concatenated.")
    args = parser.parse_args()

    timeframes_to_use = list(_TIMEFRAME_FILES.keys()) if (args.all or not args.timeframe) else [args.timeframe]

    all_phases: list[int] = []
    all_contexts: list[str] = []
    total_rows = 0

    for tf in timeframes_to_use:
        fpath = ROOT / (_TIMEFRAME_FILES.get(tf, f"data/xauusd_{tf}.csv"))
        df = _load_csv(fpath)
        if df is None or len(df) < 50:
            print(f"  [SKIP] {tf}: no valid data at {fpath}")
            continue

        labeled = label_phases(df)
        phases = labeled["phase"].tolist()
        context_keys = _build_context_keys(labeled)

        all_phases.extend(phases)
        if context_keys:
            all_contexts.extend(context_keys)
        total_rows += len(labeled)

        phase_counts = labeled["phase"].value_counts().to_dict()
        print(f"  [{tf}] {len(labeled)} bars  phases={phase_counts}")

    if len(all_phases) < 10:
        print("[ERROR] Not enough data to fit transition model.")
        sys.exit(1)

    wm = WheelTransitionModel()
    wm.fit(all_phases, context_keys=all_contexts or None)
    wm.save(_SAVE_PATH)

    print(f"\n--- Wheel Transition Model ---")
    print(wm.summary())
    print(f"\nSaved → {_SAVE_PATH}")
    print(f"Total bars: {total_rows},  transitions: {wm._total_transitions}")


if __name__ == "__main__":
    main()
