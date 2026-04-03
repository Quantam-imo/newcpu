from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from backend.ai.modeling.calibration import accuracy_from_prob, brier_score


_DRIFT_PATH = Path("data/ai_models/drift_stats.json")


def evaluate_drift(
    y_true: np.ndarray,
    p: np.ndarray,
    baseline_brier: float,
    baseline_accuracy: float,
) -> dict:
    if len(y_true) == 0:
        return {
            "status": "unknown",
            "current_brier": None,
            "current_accuracy": None,
            "drift_detected": False,
            "reason": "insufficient_recent_labels",
        }

    cur_brier = brier_score(y_true, p)
    cur_acc = accuracy_from_prob(y_true, p)

    brier_degraded = cur_brier > (float(baseline_brier) * 1.25 + 1e-9)
    acc_degraded = cur_acc < (float(baseline_accuracy) - 0.08)
    drift = bool(brier_degraded or acc_degraded)

    return {
        "status": "degraded" if drift else "healthy",
        "current_brier": round(cur_brier, 6),
        "current_accuracy": round(cur_acc, 6),
        "baseline_brier": round(float(baseline_brier), 6),
        "baseline_accuracy": round(float(baseline_accuracy), 6),
        "drift_detected": drift,
        "reason": "brier_or_accuracy_regression" if drift else "within_threshold",
    }


def write_drift_snapshot(snapshot: dict) -> None:
    _DRIFT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DRIFT_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")


def read_drift_snapshot() -> dict | None:
    if not _DRIFT_PATH.exists():
        return None
    try:
        return json.loads(_DRIFT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
