from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.ai.modeling.baseline_models import available_model_factories
from backend.ai.modeling.calibration import (
    accuracy_from_prob,
    brier_score,
    fit_temperature,
    apply_temperature,
    log_loss,
)
from backend.ai.modeling.feature_pipeline import (
    build_dataset_from_memory,
    standardize_fit,
    standardize_transform,
)
from backend.ai.modeling.registry import save_model_bundle
from backend.ai.modeling.walkforward import walkforward_validate


@dataclass
class TrainResult:
    trained: bool
    reason: str
    summary: dict[str, Any]


def _time_split(X: np.ndarray, y: np.ndarray, train_ratio: float = 0.8):
    n = len(X)
    cut = max(20, min(n - 5, int(n * train_ratio)))
    return X[:cut], y[:cut], X[cut:], y[cut:]


def train_and_register_from_memory(memory: list[dict[str, Any]], horizon: int = 1) -> TrainResult:
    X, y = build_dataset_from_memory(memory, horizon=horizon)
    if len(X) < 120:
        return TrainResult(False, "insufficient_training_rows", {"rows": int(len(X))})

    X_train_raw, y_train, X_val_raw, y_val = _time_split(X, y)
    X_train, mean, std = standardize_fit(X_train_raw)
    X_val = standardize_transform(X_val_raw, mean, std)

    candidates: list[dict[str, Any]] = []

    for model_name, factory in available_model_factories():
        model = factory().fit(X_train, y_train)
        raw_p = model.predict_proba(X_val)
        t = fit_temperature(y_val, raw_p)
        p = apply_temperature(raw_p, t)

        row = {
            "model_name": model_name,
            "model": model,
            "temperature": float(t),
            "brier": brier_score(y_val, p),
            "accuracy": accuracy_from_prob(y_val, p),
            "log_loss": log_loss(y_val, p),
        }
        candidates.append(row)

    candidates.sort(key=lambda item: (float(item["brier"]), -float(item["accuracy"])))
    best = candidates[0]

    # Walk-forward validation on the same standardized feature space.
    X_all = standardize_transform(X, mean, std)
    walkforward = walkforward_validate(X_all, y, windows=4, min_train=300)

    bundle = {
        "family": "aq-memory-baselines",
        "horizon": int(horizon),
        "feature_version": "v1_extended",
        "scaler": {
            "mean": mean.tolist(),
            "std": std.tolist(),
        },
        "best_model": {
            "name": best["model_name"],
            "serialized": best["model"].to_dict(),
            "temperature": float(best["temperature"]),
        },
        "validation_metrics": {
            "brier": round(float(best["brier"]), 6),
            "accuracy": round(float(best["accuracy"]), 6),
            "log_loss": round(float(best["log_loss"]), 6),
            "rows_train": int(len(X_train)),
            "rows_val": int(len(X_val)),
        },
        "walkforward": walkforward,
        "leaderboard": [
            {
                "name": c["model_name"],
                "brier": round(float(c["brier"]), 6),
                "accuracy": round(float(c["accuracy"]), 6),
                "log_loss": round(float(c["log_loss"]), 6),
            }
            for c in candidates
        ],
    }
    reg = save_model_bundle(bundle, tag="memory")

    out = {
        "registered": True,
        "version": reg["version"],
        "path": reg["path"],
        "selected_model": best["model_name"],
        "metrics": bundle["validation_metrics"],
    }
    return TrainResult(True, "ok", out)
