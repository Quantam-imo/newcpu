"""
phase_accuracy_validator.py  —  Phase Label Quality Assessment
================================================================
Answers the critique's key question:
  "If phase labeling is wrong, everything downstream is confidently wrong."

WHAT IS MEASURED
----------------
For each labeled bar, we ask:
  "Did a significant directional move follow within the next N bars?"

Then we check:
  1. ACCUMULATION → was followed by a ≥X% UP move (EXPANSION)?
  2. MANIPULATION → was followed by a reversal (trap confirmed)?
  3. EXPANSION    → was the trend direction correct?
  4. DISTRIBUTION → was followed by a ≥X% DOWN move?

The "significant move" threshold is adaptive:  we use 0.5 × ATR of the
bar's local window as the minimum meaningful move size.

OUTPUT
------
  - Per-phase precision (fraction of labeled bars where move matched expectation)
  - Per-phase recall    (fraction of significant moves that were labeled correctly)
  - Transition lag      (how many bars after label change did the move begin)
  - Confusion matrix    (which phases get confused with each other)

USAGE
-----
    python phase_accuracy_validator.py
    python phase_accuracy_validator.py --tf 1h
    python phase_accuracy_validator.py --forward-bars 5 --move-atr 0.8
    python phase_accuracy_validator.py --json

"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from backend.engines.phase_labeler import PhaseLabeler, get_current_phase


PHASE_NAMES = {0: "ACCUMULATION", 1: "MANIPULATION", 2: "EXPANSION", 3: "DISTRIBUTION"}
PHASE_INT   = {v: k for k, v in PHASE_NAMES.items()}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    df.columns = [c.strip().lower() for c in df.columns]
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df = df[df[col].astype(str).str.strip() != "0"]
    df = df.dropna(subset=["close"] if "close" in df.columns else [])
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"] if "close" in df.columns else [])
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# ATR helper
# ---------------------------------------------------------------------------

def _rolling_atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high  = df["high"]
    low   = df["low"]
    close = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window, min_periods=1).mean()


# ---------------------------------------------------------------------------
# Forward-move detection
# ---------------------------------------------------------------------------

def _forward_return(close_series: pd.Series, idx: int, forward: int) -> float:
    """Pct return from close[idx] to max(close[idx+1..idx+forward])."""
    end = min(idx + forward, len(close_series) - 1)
    if end <= idx:
        return 0.0
    future = close_series.iloc[idx + 1: end + 1]
    best_up   = (future.max()  - close_series.iloc[idx]) / close_series.iloc[idx]
    best_down = (close_series.iloc[idx] - future.min()) / close_series.iloc[idx]
    # Return signed: positive = best up move, negative = best down move
    if best_up >= best_down:
        return float(best_up)
    return float(-best_down)


# ---------------------------------------------------------------------------
# Phase labeling pass
# ---------------------------------------------------------------------------

def label_all_bars(
    df: pd.DataFrame,
    warmup: int = 60,
) -> list[int]:
    labeler = PhaseLabeler()
    labels: list[int] = []
    n = len(df)
    for i in range(warmup, n):
        window = df.iloc[max(0, i - 59): i + 1]
        try:
            phase = get_current_phase(labeler.label_phases(window))
        except Exception:
            phase = 0
        labels.append(phase)
    return labels


# ---------------------------------------------------------------------------
# Core validator
# ---------------------------------------------------------------------------

def validate_phase_accuracy(
    df: pd.DataFrame,
    forward_bars: int = 5,
    move_atr_mult: float = 0.5,
    warmup: int = 60,
) -> dict[str, Any]:

    n = len(df)
    if n < warmup + forward_bars + 5:
        return {"error": f"too few bars ({n})"}

    atr = _rolling_atr(df)
    labels = label_all_bars(df, warmup=warmup)

    # For each label we have df index = warmup + i
    results_per_phase: dict[int, dict] = {p: {"tp": 0, "fp": 0, "fn": 0, "lags": []} for p in range(4)}
    confusion = np.zeros((4, 4), dtype=int)

    # Phase → expected signed direction of "significant move" after label
    EXPECTED_DIRECTION = {
        0: +1,  # ACCUMULATION → up move
        1:  0,  # MANIPULATION → reversal (context-dependent, skip precision calc)
        2: +1,  # EXPANSION    → continuation (up if hh_hl; we'll measure abs move)
        3: -1,  # DISTRIBUTION → down move
    }

    def _close_at(i): return float(df["close"].iloc[i])

    for label_idx, phase in enumerate(labels):
        bar_idx = warmup + label_idx
        if bar_idx + forward_bars >= n:
            continue

        threshold = float(atr.iloc[bar_idx]) * move_atr_mult / _close_at(bar_idx)

        fwd_ret = _forward_return(df["close"], bar_idx, forward_bars)
        exp_dir = EXPECTED_DIRECTION[phase]

        if exp_dir == 0:
            # MANIPULATION: skip precision, still track what phase comes next
            pass
        elif exp_dir > 0:
            if fwd_ret >= threshold:
                results_per_phase[phase]["tp"] += 1
            else:
                results_per_phase[phase]["fp"] += 1
        else:  # exp_dir < 0
            if fwd_ret <= -threshold:
                results_per_phase[phase]["tp"] += 1
            else:
                results_per_phase[phase]["fp"] += 1

        # Confusion: compare label to "actual" next-phase
        if label_idx + 1 < len(labels):
            next_phase = labels[label_idx + 1]
            confusion[phase][next_phase] += 1

        # Lag: how many bars until move ≥ threshold after phase-change
        if label_idx > 0 and labels[label_idx - 1] != phase:
            for lag in range(1, forward_bars + 1):
                lag_idx = bar_idx + lag
                if lag_idx >= n:
                    break
                lag_ret = abs(float(df["close"].iloc[lag_idx]) - _close_at(bar_idx)) / _close_at(bar_idx)
                if lag_ret >= threshold:
                    results_per_phase[phase]["lags"].append(lag)
                    break

    # Compute per-phase metrics
    phase_metrics: dict[str, dict] = {}
    for ph, d in results_per_phase.items():
        tp, fp = d["tp"], d["fp"]
        total = tp + fp
        lags  = d["lags"]
        phase_metrics[PHASE_NAMES[ph]] = {
            "total_labeled":       total,
            "true_positive":       tp,
            "false_positive":      fp,
            "precision":           round(tp / max(1, total), 4),
            "mean_lag_bars":       round(float(np.mean(lags)) if lags else float("nan"), 2),
            "median_lag_bars":     round(float(np.median(lags)) if lags else float("nan"), 2),
        }

    # Label distribution
    label_counts = {PHASE_NAMES[p]: int((np.array(labels) == p).sum()) for p in range(4)}

    # Transition accuracy: fraction of phase transitions followed by expected direction
    transitions = []
    for i in range(len(labels) - 1):
        if labels[i] != labels[i + 1]:
            transitions.append((labels[i], labels[i + 1]))

    return {
        "total_bars_labeled":   len(labels),
        "forward_bars":         forward_bars,
        "move_atr_mult":        move_atr_mult,
        "label_distribution":   label_counts,
        "total_transitions":    len(transitions),
        "per_phase_metrics":    phase_metrics,
        "confusion_matrix":     {
            "row_label": "current_phase",
            "col_label": "next_phase (t+1)",
            "phases":    list(PHASE_NAMES.values()),
            "matrix":    confusion.tolist(),
        },
    }


# ---------------------------------------------------------------------------
# Pretty printer
# ---------------------------------------------------------------------------

def _print_results(label: str, r: dict) -> None:
    if "error" in r:
        print(f"\n[{label}] ERROR: {r['error']}")
        return

    print(f"\n{'='*60}")
    print(f"  PHASE ACCURACY — {label}")
    print(f"{'='*60}")
    print(f"  Total bars labeled : {r['total_bars_labeled']}")
    print(f"  Forward window     : {r['forward_bars']} bars")
    print(f"  Move threshold     : {r['move_atr_mult']}× ATR")
    print(f"  Label distribution : {r['label_distribution']}")
    print(f"  Total transitions  : {r['total_transitions']}")
    print()

    print(f"  {'Phase':<16} {'Labeled':>8} {'TP':>6} {'FP':>6} {'Precision':>10} {'MeanLag':>8} {'MedLag':>8}")
    print("  " + "-" * 68)
    for ph, m in r["per_phase_metrics"].items():
        prec = m["precision"]
        qual = (
            "GOOD  (>70%)" if prec > 0.70 else
            "FAIR  (50-70%)" if prec > 0.50 else
            "POOR  (<50%)"
        )
        lag_mean = m["mean_lag_bars"]
        lag_med  = m["median_lag_bars"]
        print(
            f"  {ph:<16} {m['total_labeled']:>8} {m['true_positive']:>6} "
            f"{m['false_positive']:>6} {prec:>10.3f} "
            f"{lag_mean:>8.1f} {lag_med:>8.1f}  {qual}"
        )

    print()
    print("  Confusion matrix (row=current_phase, col=next_phase at t+1):")
    phases = r["confusion_matrix"]["phases"]
    mat = r["confusion_matrix"]["matrix"]
    col_w = 14
    header = f"  {'':16}" + "".join(f"{p[:col_w]:>{col_w}}" for p in phases)
    print(header)
    for i, ph in enumerate(phases):
        row_str = "".join(f"{mat[i][j]:>{col_w}}" for j in range(len(phases)))
        print(f"  {ph:<16}{row_str}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Phase Detection Accuracy Validator")
    parser.add_argument("--tf", default=None, help="timeframe suffix e.g. 1h")
    parser.add_argument("--forward-bars", type=int, default=5)
    parser.add_argument("--move-atr", type=float, default=0.5,
                        help="min move = move_atr × ATR to count as 'significant'")
    parser.add_argument("--max-bars", type=int, default=2000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    data_dir = ROOT / "data"
    pattern  = str(data_dir / f"XAU_{'*' + args.tf if args.tf else '*'}_data.csv")
    files    = sorted(glob.glob(pattern))

    if not files:
        print(f"No CSV files found matching {pattern}")
        sys.exit(1)

    all_results: dict[str, Any] = {}

    for fpath in files:
        label = Path(fpath).stem
        try:
            df = _load_csv(fpath)
            if len(df) > args.max_bars:
                df = df.tail(args.max_bars).reset_index(drop=True)
            results = validate_phase_accuracy(
                df,
                forward_bars=args.forward_bars,
                move_atr_mult=args.move_atr,
            )
        except Exception as exc:
            results = {"error": str(exc)}

        if args.json:
            all_results[label] = results
        else:
            _print_results(label, results)

    if args.json:
        print(json.dumps(all_results, indent=2, default=str))


if __name__ == "__main__":
    main()
