from __future__ import annotations

from typing import Any

import numpy as np

from backend.ai.feature_vector import create_feature_vector


PHASE_MAP = {
    "ACCUMULATION": 0,
    "MANIPULATION": 1,
    "EXPANSION": 2,
    "DISTRIBUTION": 3,
    "NEUTRAL": 4,
}


def build_feature_row(record: dict[str, Any]) -> list[float]:
    """Build an extended feature row from a scanned market record."""
    base = list(create_feature_vector(record))

    news = (record or {}).get("news") or {}
    signal = str((record or {}).get("signal") or "WAIT").upper()
    state = (record or {}).get("state") or {}

    extra = [
        float(news.get("impact_score", 0.0) or 0.0),
        1.0 if bool(news.get("high_impact_active", False)) else 0.0,
        1.0 if signal in {"BUY", "STRONG BUY"} else 0.0,
        1.0 if signal in {"SELL", "STRONG SELL"} else 0.0,
        float(state.get("price", 0.0) or 0.0),
    ]

    return [float(x) for x in (base + extra)]


def _label_from_record(record: dict[str, Any]) -> int:
    trend = str(((record or {}).get("state") or {}).get("trend") or "DOWN").upper()
    return 1 if trend == "UP" else 0


def build_dataset_from_memory(memory: list[dict[str, Any]], horizon: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """
    Build supervised dataset from memory records.

    Features at index i predict trend label at i+horizon.
    """
    if not memory or len(memory) < (horizon + 5):
        return np.empty((0, 0), dtype=float), np.empty((0,), dtype=int)

    X: list[list[float]] = []
    y: list[int] = []

    upper = len(memory) - int(max(1, horizon))
    for i in range(upper):
        row = build_feature_row(memory[i])
        target = _label_from_record(memory[i + horizon])
        X.append(row)
        y.append(target)

    return np.array(X, dtype=float), np.array(y, dtype=int)


def standardize_fit(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if X.size == 0:
        return X, np.array([], dtype=float), np.array([], dtype=float)
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std = np.where(std < 1e-12, 1.0, std)
    Xs = (X - mean) / std
    return Xs, mean, std


def standardize_transform(X: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    if X.size == 0:
        return X
    return (X - mean) / np.where(std < 1e-12, 1.0, std)
