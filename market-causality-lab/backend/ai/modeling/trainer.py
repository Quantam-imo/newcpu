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
    DEFAULT_LABEL_MODE,
    DEFAULT_SETUP_MODE,
    DEFAULT_STOP_RETURN_PCT,
    DEFAULT_TARGET_RETURN_PCT,
    build_dataset_from_memory,
    feature_names_for_version,
    label_config,
    setup_config,
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


def _model_scope(timeframe: str | None, setup_mode: str, label_mode: str) -> str | None:
    tf = str(timeframe or "").strip().lower()
    setup = str(setup_mode or "").strip().lower()
    label = str(label_mode or "").strip().lower()
    if not tf:
        return None
    if setup and label:
        return f"{tf}__{setup}__{label}"
    return tf


def train_and_register_from_memory(
    memory: list[dict[str, Any]],
    horizon: int = 1,
    timeframe: str | None = None,
    dataset_path: str | None = None,
    lookback_years: int | None = None,
    label_mode: str = DEFAULT_LABEL_MODE,
    target_return_pct: float = DEFAULT_TARGET_RETURN_PCT,
    stop_return_pct: float = DEFAULT_STOP_RETURN_PCT,
    feature_version: str = "v3_amd_cycle_state",
    setup_mode: str = DEFAULT_SETUP_MODE,
) -> TrainResult:
    X, y = build_dataset_from_memory(
        memory,
        horizon=horizon,
        label_mode=label_mode,
        target_return_pct=target_return_pct,
        stop_return_pct=stop_return_pct,
        feature_version=feature_version,
        setup_mode=setup_mode,
    )
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

    model_scope = _model_scope(timeframe, setup_mode, label_mode)
    bundle = {
        "family": "aq-memory-baselines",
        "model_scope": model_scope,
        "timeframe": str(timeframe or "").strip().lower() or None,
        "dataset_path": dataset_path,
        "lookback_years": int(lookback_years) if lookback_years is not None else None,
        "horizon": int(horizon),
        "label": label_config(
            label_mode=label_mode,
            target_return_pct=target_return_pct,
            stop_return_pct=stop_return_pct,
        ),
        "setup": setup_config(setup_mode=setup_mode),
        "feature_version": str(feature_version),
        "feature_count": len(feature_names_for_version(feature_version)),
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
    reg = save_model_bundle(
        bundle,
        tag="memory",
        scope=model_scope,
        aliases=[str(timeframe or "").strip().lower() or None],
    )

    out = {
        "registered": True,
        "version": reg["version"],
        "path": reg["path"],
        "timeframe": bundle["timeframe"],
        "label": bundle["label"],
        "setup": bundle["setup"],
        "feature_version": bundle["feature_version"],
        "selected_model": best["model_name"],
        "metrics": bundle["validation_metrics"],
    }
    return TrainResult(True, "ok", out)
