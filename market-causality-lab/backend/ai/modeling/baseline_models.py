from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-x))


class BaseProbModel:
    name = "base"

    def fit(self, X: np.ndarray, y: np.ndarray) -> "BaseProbModel":
        raise NotImplementedError

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class LogisticGDModel(BaseProbModel):
    name: str = "logistic_gd"
    lr: float = 0.03
    epochs: int = 300
    l2: float = 1e-3

    def __post_init__(self) -> None:
        self.w: np.ndarray | None = None
        self.b: float = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> "LogisticGDModel":
        n, d = X.shape
        self.w = np.zeros((d,), dtype=float)
        self.b = 0.0
        y_f = y.astype(float)

        for _ in range(int(self.epochs)):
            logits = X @ self.w + self.b
            p = _sigmoid(logits)
            err = p - y_f
            grad_w = (X.T @ err) / max(1, n) + self.l2 * self.w
            grad_b = float(err.mean())
            self.w -= self.lr * grad_w
            self.b -= self.lr * grad_b

        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.w is None:
            return np.full((len(X),), 0.5, dtype=float)
        return _sigmoid(X @ self.w + self.b)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "lr": self.lr,
            "epochs": self.epochs,
            "l2": self.l2,
            "w": self.w.tolist() if self.w is not None else None,
            "b": self.b,
        }


@dataclass
class GaussianNBModel(BaseProbModel):
    name: str = "gaussian_nb"

    def __post_init__(self) -> None:
        self.priors: dict[int, float] = {0: 0.5, 1: 0.5}
        self.mean: dict[int, np.ndarray] = {}
        self.var: dict[int, np.ndarray] = {}

    def fit(self, X: np.ndarray, y: np.ndarray) -> "GaussianNBModel":
        eps = 1e-8
        for c in (0, 1):
            Xc = X[y == c]
            if len(Xc) == 0:
                self.mean[c] = np.zeros((X.shape[1],), dtype=float)
                self.var[c] = np.ones((X.shape[1],), dtype=float)
                self.priors[c] = 0.5
                continue
            self.mean[c] = Xc.mean(axis=0)
            self.var[c] = np.maximum(Xc.var(axis=0), eps)
            self.priors[c] = float(len(Xc)) / float(len(X))
        return self

    def _log_likelihood(self, X: np.ndarray, c: int) -> np.ndarray:
        mean = self.mean[c]
        var = self.var[c]
        return -0.5 * np.sum(np.log(2.0 * np.pi * var) + ((X - mean) ** 2) / var, axis=1) + np.log(max(self.priors[c], 1e-8))

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        ll0 = self._log_likelihood(X, 0)
        ll1 = self._log_likelihood(X, 1)
        p1 = 1.0 / (1.0 + np.exp(np.clip(ll0 - ll1, -40.0, 40.0)))
        return p1

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "priors": self.priors,
            "mean": {k: v.tolist() for k, v in self.mean.items()},
            "var": {k: v.tolist() for k, v in self.var.items()},
        }


@dataclass
class CentroidModel(BaseProbModel):
    name: str = "centroid"

    def __post_init__(self) -> None:
        self.c0: np.ndarray | None = None
        self.c1: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "CentroidModel":
        if np.any(y == 0):
            self.c0 = X[y == 0].mean(axis=0)
        else:
            self.c0 = np.zeros((X.shape[1],), dtype=float)
        if np.any(y == 1):
            self.c1 = X[y == 1].mean(axis=0)
        else:
            self.c1 = np.zeros((X.shape[1],), dtype=float)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.c0 is None or self.c1 is None:
            return np.full((len(X),), 0.5, dtype=float)
        d0 = np.linalg.norm(X - self.c0, axis=1)
        d1 = np.linalg.norm(X - self.c1, axis=1)
        return 1.0 / (1.0 + np.exp(np.clip(d1 - d0, -40.0, 40.0)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "c0": self.c0.tolist() if self.c0 is not None else None,
            "c1": self.c1.tolist() if self.c1 is not None else None,
        }


@dataclass
class MomentumRuleModel(BaseProbModel):
    name: str = "momentum_rule"

    def __post_init__(self) -> None:
        self.momentum_idx: int = 1
        self.threshold: float = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> "MomentumRuleModel":
        # Uses momentum feature with median threshold.
        if X.shape[1] > 1:
            self.momentum_idx = 1
            self.threshold = float(np.median(X[:, self.momentum_idx]))
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        m = X[:, self.momentum_idx] if X.shape[1] > self.momentum_idx else np.zeros((len(X),), dtype=float)
        logits = (m - self.threshold) * 2.0
        return _sigmoid(logits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "momentum_idx": self.momentum_idx,
            "threshold": self.threshold,
        }


@dataclass
class PriorModel(BaseProbModel):
    name: str = "prior"

    def __post_init__(self) -> None:
        self.p: float = 0.5

    def fit(self, X: np.ndarray, y: np.ndarray) -> "PriorModel":
        self.p = float(y.mean()) if len(y) else 0.5
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.full((len(X),), self.p, dtype=float)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "p": self.p}


def available_model_factories() -> list[tuple[str, type[BaseProbModel]]]:
    return [
        ("logistic_gd", LogisticGDModel),
        ("gaussian_nb", GaussianNBModel),
        ("centroid", CentroidModel),
        ("momentum_rule", MomentumRuleModel),
        ("prior", PriorModel),
    ]


def model_from_dict(payload: dict[str, Any]) -> BaseProbModel:
    name = str(payload.get("name") or "prior")
    if name == "logistic_gd":
        m = LogisticGDModel(lr=float(payload.get("lr", 0.03)), epochs=int(payload.get("epochs", 300)), l2=float(payload.get("l2", 1e-3)))
        w = payload.get("w")
        m.w = np.array(w, dtype=float) if w is not None else None
        m.b = float(payload.get("b", 0.0))
        return m
    if name == "gaussian_nb":
        m = GaussianNBModel()
        m.priors = {int(k): float(v) for k, v in (payload.get("priors") or {}).items()}
        m.mean = {int(k): np.array(v, dtype=float) for k, v in (payload.get("mean") or {}).items()}
        m.var = {int(k): np.array(v, dtype=float) for k, v in (payload.get("var") or {}).items()}
        return m
    if name == "centroid":
        m = CentroidModel()
        m.c0 = np.array(payload.get("c0"), dtype=float) if payload.get("c0") is not None else None
        m.c1 = np.array(payload.get("c1"), dtype=float) if payload.get("c1") is not None else None
        return m
    if name == "momentum_rule":
        m = MomentumRuleModel()
        m.momentum_idx = int(payload.get("momentum_idx", 1))
        m.threshold = float(payload.get("threshold", 0.0))
        return m
    m = PriorModel()
    m.p = float(payload.get("p", 0.5))
    return m
