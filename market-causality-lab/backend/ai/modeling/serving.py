from __future__ import annotations

from typing import Any

import numpy as np

from backend.ai.decision_engine import ai_decision
from backend.ai.modeling.baseline_models import model_from_dict
from backend.ai.modeling.calibration import apply_temperature
from backend.ai.modeling.drift_monitor import evaluate_drift, write_drift_snapshot
from backend.ai.modeling.feature_pipeline import (
    build_dataset_from_memory,
    build_feature_row,
    standardize_transform,
)
from backend.ai.modeling.registry import load_latest_bundle


def _decision_from_prob(p_buy: float) -> str:
    return ai_decision({"BUY": float(p_buy), "SELL": float(1.0 - p_buy)})


def decide_with_model(memory: list[dict[str, Any]], fallback_prob: dict[str, float]) -> tuple[str, dict[str, Any]]:
    """
    Return (decision, meta). Uses latest registered model when healthy,
    otherwise falls back to the existing rule decision.
    """
    fallback_decision = ai_decision(fallback_prob)

    bundle = load_latest_bundle()
    if not bundle:
        return fallback_decision, {
            "used_model": False,
            "reason": "no_registered_model",
        }

    try:
        scaler = bundle.get("scaler") or {}
        mean = np.array(scaler.get("mean") or [], dtype=float)
        std = np.array(scaler.get("std") or [], dtype=float)

        best = (bundle.get("best_model") or {})
        model_payload = best.get("serialized") or {}
        model = model_from_dict(model_payload)
        temperature = float(best.get("temperature", 1.0) or 1.0)

        if not memory:
            return fallback_decision, {
                "used_model": False,
                "reason": "empty_memory",
                "version": bundle.get("version"),
            }

        x_live = np.array([build_feature_row(memory[-1])], dtype=float)
        if len(mean) and len(std):
            x_live = standardize_transform(x_live, mean, std)

        raw_p = float(model.predict_proba(x_live)[0])
        p_buy = float(apply_temperature(np.array([raw_p], dtype=float), temperature)[0])

        # Drift check on most recent labeled window.
        X_recent, y_recent = build_dataset_from_memory(memory[-450:], horizon=int(bundle.get("horizon", 1) or 1))
        drift_meta = {
            "status": "unknown",
            "drift_detected": False,
            "reason": "insufficient_recent_labels",
        }
        if len(X_recent) >= 80 and len(mean) and len(std):
            X_recent = standardize_transform(X_recent, mean, std)
            p_recent_raw = model.predict_proba(X_recent)
            p_recent = apply_temperature(p_recent_raw, temperature)
            base = bundle.get("validation_metrics") or {}
            drift_meta = evaluate_drift(
                y_true=y_recent,
                p=p_recent,
                baseline_brier=float(base.get("brier", 0.25) or 0.25),
                baseline_accuracy=float(base.get("accuracy", 0.5) or 0.5),
            )
            write_drift_snapshot({
                "version": bundle.get("version"),
                "drift": drift_meta,
            })

        if bool(drift_meta.get("drift_detected", False)):
            return fallback_decision, {
                "used_model": False,
                "reason": "drift_guard_fallback",
                "version": bundle.get("version"),
                "drift": drift_meta,
            }

        decision = _decision_from_prob(p_buy)
        return decision, {
            "used_model": True,
            "version": bundle.get("version"),
            "model_name": (best.get("name") or model_payload.get("name") or "unknown"),
            "p_buy": round(p_buy, 6),
            "p_sell": round(1.0 - p_buy, 6),
            "drift": drift_meta,
        }
    except Exception as exc:
        return fallback_decision, {
            "used_model": False,
            "reason": f"model_runtime_error: {exc}",
            "version": bundle.get("version"),
        }
