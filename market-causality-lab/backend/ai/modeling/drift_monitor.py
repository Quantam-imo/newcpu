from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from backend.ai.modeling.calibration import accuracy_from_prob, brier_score


_DRIFT_PATH = Path("data/ai_models/drift_stats.json")
_RETRAIN_QUEUE_PATH = Path("data/ai_models/retrain_queue.json")


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
    # If drift was detected, queue this scope for automatic retrain.
    if snapshot.get("drift", {}).get("drift_detected", False):
        _queue_retrain(snapshot)


def _queue_retrain(snapshot: dict) -> None:
    """Add a drift-triggered retrain request to the queue file (non-blocking)."""
    try:
        _RETRAIN_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict[str, Any]] = []
        if _RETRAIN_QUEUE_PATH.exists():
            try:
                existing = json.loads(_RETRAIN_QUEUE_PATH.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []

        scope = snapshot.get("requested_timeframe") or snapshot.get("model_timeframe")
        version = snapshot.get("version")
        # Deduplicate: don't add same scope twice
        already_queued = any(e.get("scope") == scope for e in existing)
        if not already_queued:
            entry: dict[str, Any] = {
                "scope": scope,
                "version": version,
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "drift_brier": snapshot.get("drift", {}).get("current_brier"),
                "drift_accuracy": snapshot.get("drift", {}).get("current_accuracy"),
                "status": "pending",
            }
            existing.append(entry)
            _RETRAIN_QUEUE_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except Exception:
        pass  # Never crash serving due to queue write failure


def read_retrain_queue() -> list[dict[str, Any]]:
    """Return all pending retrain queue entries."""
    if not _RETRAIN_QUEUE_PATH.exists():
        return []
    try:
        data = json.loads(_RETRAIN_QUEUE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def mark_retrain_done(scope: str) -> None:
    """Mark a queued scope as completed after retrain finishes."""
    if not _RETRAIN_QUEUE_PATH.exists():
        return
    try:
        data = read_retrain_queue()
        for entry in data:
            if entry.get("scope") == scope and entry.get("status") == "pending":
                entry["status"] = "done"
                entry["done_at"] = datetime.now(timezone.utc).isoformat()
        _RETRAIN_QUEUE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def dispatch_retrain_if_queued(
    timeframe_file_map: dict[str, str],
    feature_version: str = "v5_elliott_unified",
) -> list[str]:
    """
    Check the retrain queue and fire background retrains for any pending scopes.
    Runs each retrain in a daemon thread so it doesn't block serving.

    Parameters
    ----------
    timeframe_file_map : e.g. {"4h": "data/XAU_4h_data.csv", ...}
    feature_version    : feature schema to retrain with

    Returns
    -------
    List of scope names that had a retrain dispatched.
    """
    queue = read_retrain_queue()
    pending = [e for e in queue if e.get("status") == "pending" and e.get("scope")]
    dispatched: list[str] = []

    for entry in pending:
        scope = str(entry["scope"])
        tf = scope.split("__")[0] if "__" in scope else scope
        price_file = timeframe_file_map.get(tf)
        if not price_file:
            continue

        def _run(sc: str, pf: str, fv: str) -> None:
            try:
                import subprocess
                import sys
                cmd = [
                    sys.executable,
                    "train_ai_models.py",
                    "--timeframe", sc.split("__")[0],
                    "--feature-version", fv,
                    "--price-file", pf,
                ]
                subprocess.run(cmd, capture_output=True, timeout=600)
                mark_retrain_done(sc)
            except Exception:
                pass

        t = threading.Thread(target=_run, args=(scope, price_file, feature_version), daemon=True)
        t.start()
        dispatched.append(scope)

    return dispatched


def read_drift_snapshot() -> dict | None:
    if not _DRIFT_PATH.exists():
        return None
    try:
        return json.loads(_DRIFT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
