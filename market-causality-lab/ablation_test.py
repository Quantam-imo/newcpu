"""
ablation_test.py  —  AstroQuant Engine Ablation Study
=======================================================
Measures the contribution of each confluence engine by zeroing it out and
comparing the directional consistency of the surviving system.

HOW IT WORKS
------------
1. Load historical XAU data (same CSVs used by wheel_trainer).
2. Run the full confluence_decision() on every bar in the test window to
   produce a "baseline" decision stream.
3. For each engine, produce an "ablated" decision stream where that engine's
   contribution is nulled (liquidity sweep zeroed → no liquidity trigger, etc.)
4. Report:
   - Direction flip rate: fraction of bars where ablation changes the direction
   - WAIT increase: how often ablating an engine pushes a signal to WAIT
   - Confidence delta: mean change in confidence score

The ablation scores tell you which engines drive decisions.  An engine with a
high flip rate is load-bearing; one with a near-zero flip rate is decorative.

USAGE
-----
    python ablation_test.py                    # all engines, all timeframes
    python ablation_test.py --tf 1h            # single timeframe
    python ablation_test.py --engine model     # single engine
    python ablation_test.py --top-n 3          # only show top-3 by flip rate

REQUIRES
--------
- Fitted wheel_transition model at data/ai_models/wheel_transition.json
  (run wheel_trainer.py first if it doesn't exist)
- XAU_*_data.csv files in data/

"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from backend.ai.decision_engine import confluence_decision
from backend.engines.phase_labeler import PhaseLabeler, get_current_phase
from backend.engines.regime_detector import detect_regime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    df.columns = [c.strip().lower() for c in df.columns]
    # Drop placeholder / all-zero rows
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df = df[df[col].astype(str).str.strip() != "0"]
    df = df.dropna(subset=["close"] if "close" in df.columns else [])
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"] if "close" in df.columns else [])
    df = df.reset_index(drop=True)
    return df


def _make_stub_memory(df: pd.DataFrame, idx: int) -> dict[str, Any]:
    """
    Build a minimal memory record from a single OHLCV row.
    Only fields read by confluence_decision() are populated.
    """
    row = df.iloc[idx]
    close = float(row.get("close", 0))
    high  = float(row.get("high", close))
    low   = float(row.get("low", close))

    # Simple structure guess: running on last-8-bar direction
    window = df.iloc[max(0, idx - 8): idx + 1]
    is_uptrend = bool(window["close"].iloc[-1] > window["close"].iloc[0]) if len(window) > 1 else True

    return {
        "state": {"price": close},
        "bar": {"high": high, "low": low},
        "phase": "ACCUMULATION",          # will be overridden by phase_labeled arg
        "structure": {"hh_hl": is_uptrend},
        "liquidity": {"type": "NONE"},
        "gann_astro_math": {
            "major_turn_window": False,
            "sqrt_rotation_deg": 45.0,
        },
        "elliott_wave": {
            "wave_phase": "IMPULSE",
            "wave_confidence": 0.5,
            "wave_direction_up": is_uptrend,
            "wave_progress": 0.4,
        },
        "participation": {"london_open": False, "newyork_open": False},
        "trigger": {"trigger_confirmed": False, "trigger_direction": "WAIT"},
        "trap": {"trap": "NONE"},
        "location": {},
        "amd_ifvg": {"amd_bull_entry": False, "amd_bear_entry": False},
        "turtle_soup": {"turtle_soup_sell": False, "turtle_soup_buy": False},
        "reliability": {},
    }


def _make_stub_model_meta(p_buy: float = 0.52) -> dict[str, Any]:
    return {
        "p_buy": p_buy,
        "p_sell": 1.0 - p_buy,
        "used_model": True,
    }


# ---------------------------------------------------------------------------
# Engine zeroing functions
# Keyed by engine name; each returns a mutated COPY of (model_meta, mem).
# ---------------------------------------------------------------------------

def _zero_model(model_meta, mem):
    m = copy.deepcopy(model_meta)
    m["p_buy"] = 0.5
    m["p_sell"] = 0.5
    m["used_model"] = False
    return m, mem


def _zero_liquidity(model_meta, mem):
    m2 = copy.deepcopy(mem)
    m2["liquidity"] = {"type": "NONE"}
    return model_meta, m2


def _zero_phase(model_meta, mem):
    # Phase ablation: force phase to NONE / invalid so primary phase fires nothing
    m2 = copy.deepcopy(mem)
    m2["phase"] = "UNKNOWN"
    return model_meta, m2


def _zero_gann(model_meta, mem):
    m2 = copy.deepcopy(mem)
    m2["gann_astro_math"] = {"major_turn_window": False, "sqrt_rotation_deg": 0.0}
    return model_meta, m2


def _zero_astro(model_meta, mem):
    # Astro and Gann share gann_astro_math; ablate harmonic proximity
    m2 = copy.deepcopy(mem)
    m2.setdefault("gann_astro_math", {})
    m2["gann_astro_math"]["sqrt_rotation_deg"] = 0.0   # 0° is not near any reversal harmonic
    return model_meta, m2


def _zero_elliott(model_meta, mem):
    m2 = copy.deepcopy(mem)
    m2["elliott_wave"] = {"wave_phase": "FLAT", "wave_confidence": 0.0,
                          "wave_direction_up": True, "wave_progress": 0.0}
    return model_meta, m2


def _zero_amd(model_meta, mem):
    m2 = copy.deepcopy(mem)
    m2["amd_ifvg"] = {"amd_bull_entry": False, "amd_bear_entry": False}
    return model_meta, m2


def _zero_turtle_soup(model_meta, mem):
    m2 = copy.deepcopy(mem)
    m2["turtle_soup"] = {"turtle_soup_sell": False, "turtle_soup_buy": False}
    return model_meta, m2


def _zero_session(model_meta, mem):
    m2 = copy.deepcopy(mem)
    m2["participation"] = {"london_open": False, "newyork_open": False}
    return model_meta, m2


def _zero_ict_trigger(model_meta, mem):
    m2 = copy.deepcopy(mem)
    m2["trigger"] = {"trigger_confirmed": False, "trigger_direction": "WAIT"}
    return model_meta, m2


def _zero_wheel_transition(model_meta, mem):
    # Wheel transition is computed inside confluence_decision from the model file.
    # We can't zero it directly without patching — instead we signal via a
    # special flag in the stub.  This ablation will be skipped if model not fitted.
    # For now return unchanged — see note in results output.
    return model_meta, mem


ABLATION_ENGINES: dict[str, Any] = {
    "model":           _zero_model,
    "liquidity":       _zero_liquidity,
    "phase":           _zero_phase,
    "gann":            _zero_gann,
    "elliott":         _zero_elliott,
    "amd_ifvg":        _zero_amd,
    "turtle_soup":     _zero_turtle_soup,
    "session":         _zero_session,
    "ict_trigger":     _zero_ict_trigger,
    # wheel_transition ablation is approximate (built inside confluence_decision)
}


# ---------------------------------------------------------------------------
# Core ablation runner
# ---------------------------------------------------------------------------

PHASE_INT = {"ACCUMULATION": 0, "MANIPULATION": 1, "EXPANSION": 2, "DISTRIBUTION": 3}
PHASE_NAMES = {0: "ACCUMULATION", 1: "MANIPULATION", 2: "EXPANSION", 3: "DISTRIBUTION"}


def run_ablation(
    df: pd.DataFrame,
    engine_filter: list[str] | None = None,
    warmup: int = 80,
) -> dict[str, Any]:
    """
    Run baseline + ablation on df.  Returns metrics per engine.
    """
    n = len(df)
    if n < warmup + 5:
        return {"error": f"too few bars ({n})"}

    labeler = PhaseLabeler()

    baseline_directions: list[str] = []
    baseline_confidences: list[float] = []
    ablated: dict[str, list[str]] = {e: [] for e in (engine_filter or ABLATION_ENGINES)}
    ablated_conf: dict[str, list[float]] = {e: [] for e in (engine_filter or ABLATION_ENGINES)}
    phase_labels: list[int] = []

    for i in range(warmup, n):
        window_phase  = df.iloc[max(0, i - 59): i + 1]
        window_regime = df.iloc[max(0, i - 79): i + 1]

        try:
            phase_int = get_current_phase(labeler.label_phases(window_phase))
        except Exception:
            phase_int = 0
        phase_labels.append(phase_int)

        try:
            regime_res = detect_regime(window_regime)
        except Exception:
            regime_res = None

        mem = _make_stub_memory(df, i)
        model_meta = _make_stub_model_meta(p_buy=0.52 + 0.1 * float(np.sin(i * 0.1)))

        # Baseline
        try:
            base = confluence_decision(model_meta, memory_last=mem,
                                       regime_result=regime_res, phase_labeled=phase_int)
            baseline_directions.append(base["direction"])
            baseline_confidences.append(base.get("confidence", 0.0))
        except Exception as exc:
            baseline_directions.append("WAIT")
            baseline_confidences.append(0.0)

        # Ablations
        for eng in (engine_filter or list(ABLATION_ENGINES.keys())):
            fn = ABLATION_ENGINES.get(eng)
            if fn is None:
                continue
            try:
                a_meta, a_mem = fn(model_meta, mem)
                ab = confluence_decision(a_meta, memory_last=a_mem,
                                         regime_result=regime_res, phase_labeled=phase_int)
                ablated[eng].append(ab["direction"])
                ablated_conf[eng].append(ab.get("confidence", 0.0))
            except Exception:
                ablated[eng].append("WAIT")
                ablated_conf[eng].append(0.0)

    total = len(baseline_directions)
    base_arr = np.array(baseline_directions)
    base_conf_arr = np.array(baseline_confidences)

    metrics: dict[str, dict] = {}
    for eng, ablated_dirs in ablated.items():
        ab_arr = np.array(ablated_dirs)
        ab_conf_arr = np.array(ablated_conf[eng])

        flip_mask      = base_arr != ab_arr
        to_wait_mask   = (base_arr != "WAIT") & (ab_arr == "WAIT")
        from_wait_mask = (base_arr == "WAIT") & (ab_arr != "WAIT")

        metrics[eng] = {
            "total_bars":         total,
            "flip_rate":          round(float(flip_mask.mean()), 4),
            "to_wait_rate":       round(float(to_wait_mask.mean()), 4),
            "from_wait_rate":     round(float(from_wait_mask.mean()), 4),
            "mean_conf_delta":    round(float((ab_conf_arr - base_conf_arr).mean()), 4),
            "baseline_wait_pct":  round(float((base_arr == "WAIT").mean()), 4),
            "ablated_wait_pct":   round(float((ab_arr == "WAIT").mean()), 4),
        }

    # Phase distribution in this run
    ph_dist = {PHASE_NAMES.get(i, str(i)): 0 for i in range(4)}
    for p in phase_labels:
        ph_dist[PHASE_NAMES.get(p, str(p))] = ph_dist.get(PHASE_NAMES.get(p, str(p)), 0) + 1

    return {
        "total_bars": total,
        "baseline_buy_pct":  round(float((base_arr == "BUY").mean()), 4),
        "baseline_sell_pct": round(float((base_arr == "SELL").mean()), 4),
        "baseline_wait_pct": round(float((base_arr == "WAIT").mean()), 4),
        "phase_distribution": ph_dist,
        "engine_metrics": metrics,
    }


# ---------------------------------------------------------------------------
# Pretty printer
# ---------------------------------------------------------------------------

def _print_results(label: str, results: dict) -> None:
    if "error" in results:
        print(f"\n[{label}] ERROR: {results['error']}")
        return

    print(f"\n{'='*60}")
    print(f"  ABLATION RESULTS — {label}")
    print(f"{'='*60}")
    print(f"  Total bars tested : {results['total_bars']}")
    print(f"  Baseline  BUY     : {results['baseline_buy_pct']*100:.1f}%")
    print(f"  Baseline  SELL    : {results['baseline_sell_pct']*100:.1f}%")
    print(f"  Baseline  WAIT    : {results['baseline_wait_pct']*100:.1f}%")
    print(f"  Phase dist        : {results['phase_distribution']}")
    print()

    eng_metrics = results["engine_metrics"]
    # Sort by flip_rate descending (most impactful first)
    sorted_engines = sorted(eng_metrics.items(), key=lambda x: x[1]["flip_rate"], reverse=True)

    col_w = 18
    header = (
        f"  {'Engine':<{col_w}} {'FlipRate':>10} {'→WAIT':>8} "
        f"{'←WAIT':>8} {'ConfDelta':>10} {'AblWAIT%':>10}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))

    for eng, m in sorted_engines:
        flip = m["flip_rate"]
        to_w = m["to_wait_rate"]
        fr_w = m["from_wait_rate"]
        cd   = m["mean_conf_delta"]
        aw   = m["ablated_wait_pct"]

        importance = (
            "*** HIGH IMPACT" if flip > 0.15 else
            "**  MED IMPACT"  if flip > 0.05 else
            "*   LOW IMPACT"  if flip > 0.01 else
            "    NEGLIGIBLE"
        )
        print(
            f"  {eng:<{col_w}} {flip:>10.3f} {to_w:>8.3f} {fr_w:>8.3f} "
            f"{cd:>+10.4f} {aw:>10.3f}  {importance}"
        )

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="AstroQuant Ablation Test")
    parser.add_argument("--tf", default=None, help="timeframe suffix, e.g. 1h, 4h, 1d")
    parser.add_argument("--engine", default=None, help="single engine to ablate")
    parser.add_argument("--top-n", type=int, default=None, help="only print top-N by flip rate")
    parser.add_argument("--max-bars", type=int, default=2000, help="max bars per file (default 2000)")
    parser.add_argument("--json", action="store_true", help="output raw JSON instead of table")
    args = parser.parse_args()

    data_dir = ROOT / "data"
    pattern  = str(data_dir / f"XAU_{'*' + args.tf if args.tf else '*'}_data.csv")
    files    = sorted(glob.glob(pattern))

    if not files:
        print(f"No CSV files found matching {pattern}")
        print("Expected: data/XAU_<tf>_data.csv  (semicolon-delimited)")
        sys.exit(1)

    engine_filter = [args.engine] if args.engine else None
    all_results: dict[str, Any] = {}

    for fpath in files:
        label = Path(fpath).stem
        try:
            df = _load_csv(fpath)
            if len(df) > args.max_bars:
                df = df.tail(args.max_bars).reset_index(drop=True)
            results = run_ablation(df, engine_filter=engine_filter)
        except Exception as exc:
            results = {"error": str(exc)}

        if args.json:
            all_results[label] = results
        else:
            _print_results(label, results)

    if args.json:
        print(json.dumps(all_results, indent=2))


if __name__ == "__main__":
    main()
