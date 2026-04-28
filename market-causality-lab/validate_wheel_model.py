"""
validate_wheel_model.py — Run full wheel-model inference on XAUUSD for 24-04-2026.

Outputs per-timeframe:
  - Phase (wheel phase labeler output)
  - Regime (regime detector)
  - Wheel Transition (next phase probability from trained model)
  - Confluence decision (10-factor gate with regime weight)
  - Final direction + SL/TP
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

from backend.engines.phase_labeler import label_phases
from backend.engines.regime_detector import detect_regime
from backend.engines.transition_model import WheelTransitionModel
from backend.ai.decision_engine import confluence_decision

_WHEEL_MODEL_PATH = ROOT / "data" / "ai_models" / "wheel_transition.json"

_TIMEFRAME_FILES = {
    "1w":  "data/XAU_1w_data.csv",
    "1d":  "data/XAU_1d_data.csv",
    "4h":  "data/XAU_4h_data.csv",
    "1h":  "data/XAU_1h_data.csv",
    "30m": "data/XAU_30m_data.csv",
    "15m": "data/XAU_15m_data.csv",
    "5m":  "data/XAU_5m_data.csv",
}

_TARGET_DATE = "2026-04-24"


def _load_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, sep=";", index_col=0)
        df.columns = [c.lower() for c in df.columns]
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        filler = (df["open"] == df["high"]) & (df["high"] == df["low"])
        df = df[~filler]
        return df
    except Exception as e:
        print(f"  [WARN] load failed: {e}")
        return None


def _get_window_up_to(df: pd.DataFrame, target_date: str, lookback: int = 150) -> pd.DataFrame | None:
    """Return the last `lookback` bars with index <= target_date."""
    try:
        idx = pd.to_datetime(df.index, errors="coerce")
        df = df[idx <= pd.Timestamp(target_date)].tail(lookback)
        return df if len(df) >= 40 else None
    except Exception:
        return df.tail(lookback) if len(df) >= 40 else None


wm = WheelTransitionModel.load(_WHEEL_MODEL_PATH)
print(f"Wheel model loaded: {wm._total_transitions:,} training transitions\n")
print("=" * 65)
print(f" AstroQuant XAUUSD  |  24-04-2026  |  Wheel Model Validation")
print("=" * 65)

for tf, fpath_str in _TIMEFRAME_FILES.items():
    fpath = ROOT / fpath_str
    df_raw = _load_csv(fpath)
    if df_raw is None:
        print(f"\n[{tf}] SKIP — no data")
        continue

    df_window = _get_window_up_to(df_raw, _TARGET_DATE, lookback=200)
    if df_window is None:
        print(f"\n[{tf}] SKIP — insufficient bars before {_TARGET_DATE}")
        continue

    price = float(df_window["close"].iloc[-1])

    # Phase labeling
    try:
        labeled = label_phases(df_window)
        phase_code = int(labeled["phase"].iloc[-1])
        phase_str  = labeled["phase_name"].iloc[-1]
    except Exception as e:
        phase_code, phase_str = None, f"ERROR({e})"

    # Regime detection
    try:
        regime = detect_regime(df_window)
    except Exception as e:
        regime = {"regime": f"ERROR({e})", "decision_weight": 1.0}

    # Wheel transition prediction
    try:
        transition = wm.predict(phase_code, context_key=regime.get("regime"))
        next_phase = transition["next_phase_name"]
        trans_conf = transition["confidence"]
        trans_probs = transition["probabilities"]
    except Exception as e:
        next_phase, trans_conf = f"ERROR({e})", 0.0
        trans_probs = []

    # Minimal model_meta for standalone validation (no ML model loaded here)
    model_meta = {
        "used_model": False,
        "reason": "validation_only",
        "p_buy": 0.45,   # neutral placeholder
        "p_sell": 0.55,
    }

    # Confluence decision with wheel context
    try:
        conf_result = confluence_decision(
            model_meta,
            memory_last={
                "state": {"price": price},
                "bar": {
                    "high": float(df_window["high"].iloc[-1]),
                    "low":  float(df_window["low"].iloc[-1]),
                },
                "phase": phase_str,
            },
            regime_result=regime,
            phase_labeled=phase_code,
        )
        direction = conf_result["direction"]
        buy_s, sell_s = conf_result["buy_score"], conf_result["sell_score"]
        wheel_tr = conf_result.get("wheel_transition") or {}
        sl = conf_result.get("sl_zone")
        tp = conf_result.get("tp_zone")
    except Exception as e:
        direction, buy_s, sell_s = f"ERROR({e})", 0, 0
        wheel_tr = {}
        sl = tp = None

    print(f"\n[{tf}]  price={price:.2f}")
    print(f"  Phase:      {phase_str} (code={phase_code})")
    print(f"  Regime:     {regime.get('regime')}  weight={regime.get('decision_weight')}  atr_z={regime.get('atr_z')}")
    print(f"  Transition: {phase_str} → {next_phase}  P={trans_conf:.3f}")
    if trans_probs:
        prob_str = "  ".join(
            f"{n[:4]}={p:.2f}"
            for n, p in zip(["ACCU","MANI","EXPN","DIST"], trans_probs)
        )
        print(f"             [{prob_str}]")
    print(f"  Confluence: {direction}  buy={buy_s} sell={sell_s}")
    wt_msg = wheel_tr.get("next_phase_name", "") if isinstance(wheel_tr, dict) else ""
    if wt_msg:
        print(f"  WheelNext:  {wt_msg}  P={wheel_tr.get('confidence', 0):.3f}")
    if sl:
        print(f"  SL={sl:.2f}  TP={tp:.2f}")

print("\n" + "=" * 65)
print("Wheel model validation complete.")
