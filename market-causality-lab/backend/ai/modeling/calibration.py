from __future__ import annotations

import numpy as np


def _clip_p(p: np.ndarray) -> np.ndarray:
    return np.clip(p, 1e-6, 1.0 - 1e-6)


def brier_score(y_true: np.ndarray, p: np.ndarray) -> float:
    if len(y_true) == 0:
        return 0.25
    return float(np.mean((p - y_true.astype(float)) ** 2))


def accuracy_from_prob(y_true: np.ndarray, p: np.ndarray, threshold: float = 0.5) -> float:
    if len(y_true) == 0:
        return 0.0
    pred = (p >= float(threshold)).astype(int)
    return float((pred == y_true).mean())


def log_loss(y_true: np.ndarray, p: np.ndarray) -> float:
    if len(y_true) == 0:
        return 0.6931
    p = _clip_p(p)
    y = y_true.astype(float)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def fit_temperature(y_true: np.ndarray, raw_p: np.ndarray) -> float:
    """Fit scalar temperature T to calibrate probabilities using BCE grid-search."""
    if len(y_true) == 0:
        return 1.0

    z = np.log(_clip_p(raw_p) / (1.0 - _clip_p(raw_p)))
    best_t = 1.0
    best_loss = float("inf")

    for t in np.linspace(0.6, 3.0, 50):
        p = 1.0 / (1.0 + np.exp(-z / float(t)))
        loss = log_loss(y_true, p)
        if loss < best_loss:
            best_loss = loss
            best_t = float(t)

    return best_t


def apply_temperature(raw_p: np.ndarray, temperature: float) -> np.ndarray:
    t = max(1e-6, float(temperature or 1.0))
    z = np.log(_clip_p(raw_p) / (1.0 - _clip_p(raw_p)))
    return 1.0 / (1.0 + np.exp(-z / t))
