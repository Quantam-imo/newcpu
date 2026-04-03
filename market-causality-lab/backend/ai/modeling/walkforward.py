from __future__ import annotations

import numpy as np

from backend.ai.modeling.baseline_models import available_model_factories
from backend.ai.modeling.calibration import accuracy_from_prob, brier_score


def walkforward_validate(
    X: np.ndarray,
    y: np.ndarray,
    windows: int = 4,
    min_train: int = 300,
) -> dict:
    """Simple chronological walk-forward validation over N windows."""
    n = len(X)
    if n < max(min_train + 50, 200):
        return {
            "enabled": False,
            "reason": "insufficient_rows",
            "folds": [],
            "summary": {"avg_brier": None, "avg_accuracy": None},
        }

    fold_size = max(50, (n - min_train) // max(1, windows))
    folds = []

    for i in range(windows):
        train_end = min_train + i * fold_size
        val_end = min(n, train_end + fold_size)
        if val_end - train_end < 20:
            break

        X_train = X[:train_end]
        y_train = y[:train_end]
        X_val = X[train_end:val_end]
        y_val = y[train_end:val_end]

        best = None
        for name, factory in available_model_factories():
            model = factory().fit(X_train, y_train)
            p = model.predict_proba(X_val)
            row = {
                "name": name,
                "brier": brier_score(y_val, p),
                "accuracy": accuracy_from_prob(y_val, p),
            }
            if best is None or row["brier"] < best["brier"]:
                best = row

        folds.append(
            {
                "fold": i + 1,
                "train_rows": int(len(X_train)),
                "val_rows": int(len(X_val)),
                "selected_model": best["name"],
                "brier": round(float(best["brier"]), 6),
                "accuracy": round(float(best["accuracy"]), 6),
            }
        )

    if not folds:
        return {
            "enabled": False,
            "reason": "no_valid_folds",
            "folds": [],
            "summary": {"avg_brier": None, "avg_accuracy": None},
        }

    avg_brier = float(np.mean([f["brier"] for f in folds]))
    avg_accuracy = float(np.mean([f["accuracy"] for f in folds]))

    return {
        "enabled": True,
        "reason": "ok",
        "folds": folds,
        "summary": {
            "avg_brier": round(avg_brier, 6),
            "avg_accuracy": round(avg_accuracy, 6),
            "fold_count": len(folds),
        },
    }
