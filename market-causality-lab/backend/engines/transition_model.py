"""
Transition Matrix — Wheel Rotation Engine.

Learns P(next_phase | current_phase) from labeled price history.
Optionally conditions on context buckets (moon quadrant, session, regime).

Usage:
    from backend.engines.transition_model import WheelTransitionModel

    wt = WheelTransitionModel()
    wt.fit(phases_array)                     # plain unconditional matrix
    wt.fit(phases_array, context_buckets)    # conditional matrix

    result = wt.predict(current_phase)
    # → {"next_phase": 2, "next_phase_name": "EXPANSION",
    #    "probabilities": [0.05, 0.10, 0.70, 0.15],
    #    "confidence": 0.70}

    wt.save("data/ai_models/wheel_transition.json")
    wt = WheelTransitionModel.load("data/ai_models/wheel_transition.json")
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

_PHASE_NAMES = {0: "ACCUMULATION", 1: "MANIPULATION", 2: "EXPANSION", 3: "DISTRIBUTION"}
_N_PHASES = 4


class WheelTransitionModel:
    """
    Probabilistic wheel transition matrix.

    Unconditional:
        T[i][j] = P(next=j | current=i)

    Conditional (context_key = regime | volatility | liquidity | absorption):
        T[context_key][i][j] = P(next=j | current=i, context=context_key)
    """

    def __init__(self) -> None:
        self._matrix: np.ndarray = self._uniform_matrix()           # shape (4,4)
        self._conditional: dict[str, np.ndarray] = {}               # key → (4,4)
        self._conditional_counts: dict[str, np.ndarray] = {}        # key → raw counts (4,4)
        self._counts: np.ndarray = np.zeros((_N_PHASES, _N_PHASES)) # raw counts
        self._total_transitions: int = 0
        self._phase_freq: np.ndarray = np.ones(_N_PHASES) / _N_PHASES

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(
        self,
        phases: "list[int] | np.ndarray",
        context_keys: "list[str] | None" = None,
    ) -> "WheelTransitionModel":
        """
        Build transition matrix from a sequence of phase labels.

        Parameters
        ----------
        phases       : sequence of int (0–3)
        context_keys : optional parallel list of context bucket strings
                       (e.g. "moon_0_90", "session_london", "regime_trend")
        """
        phases_arr = np.asarray(phases, dtype=int)
        valid = (phases_arr >= 0) & (phases_arr < _N_PHASES)
        phases_arr = phases_arr[valid]

        # Unconditional counts
        counts = np.zeros((_N_PHASES, _N_PHASES), dtype=float)
        for i in range(len(phases_arr) - 1):
            curr = phases_arr[i]
            nxt  = phases_arr[i + 1]
            counts[curr][nxt] += 1.0

        self._counts = counts
        self._total_transitions = int(counts.sum())
        self._matrix = self._normalise(counts)

        # Phase frequency
        freq = np.bincount(phases_arr, minlength=_N_PHASES).astype(float)
        self._phase_freq = freq / max(1.0, freq.sum())

        # Conditional matrix
        self._conditional_counts = {}
        if context_keys is not None:
            ck_arr = np.asarray(context_keys)
            ck_arr = ck_arr[valid]
            unique_keys = set(str(k) for k in ck_arr)
            for key in unique_keys:
                mask = ck_arr == key
                sub = phases_arr[mask]
                sub_counts = np.zeros((_N_PHASES, _N_PHASES), dtype=float)
                for i in range(len(sub) - 1):
                    curr = sub[i]; nxt = sub[i + 1]
                    sub_counts[curr][nxt] += 1.0
                self._conditional_counts[str(key)] = sub_counts
                self._conditional[str(key)] = self._normalise(sub_counts)

        return self

    # ------------------------------------------------------------------
    # Context key builder
    # ------------------------------------------------------------------

    @staticmethod
    def build_context_key(
        regime: str | None = None,
        volatility_bucket: str | None = None,
        liquidity_state: str | None = None,
        absorption_side: str | None = None,
        absorption_strength: str | None = None,
    ) -> str | None:
        """
        Build a composite context key from up to 5 conditioning variables.

        Context hierarchy (most specific → least specific):
          5-way: "TREND|HIGH_VOL|SWEEP|BUY|ABSORB_HIGH"
          4-way: "TREND|HIGH_VOL|SWEEP|BUY"
          3-way: "TREND|HIGH_VOL|SWEEP"
          2-way: "TREND|HIGH_VOL", "TREND|SWEEP", "HIGH_VOL|SWEEP"
          1-way: "TREND", "HIGH_VOL", "SWEEP", "BUY", "ABSORB_HIGH"

        Callers should build the most specific key possible and pass it to
        predict(), which will automatically fall through the hierarchy.

        Parameters
        ----------
        regime            : "TREND" | "RANGE" | "VOLATILE"
        volatility_bucket : "LOW_VOL" | "MED_VOL" | "HIGH_VOL"
        liquidity_state   : "SWEEP" | "NO_SWEEP"
        absorption_side   : "BUY" | "SELL" | "NEUTRAL"
        absorption_strength : "ABSORB_LOW" | "ABSORB_MED" | "ABSORB_HIGH"
        """
        parts = [
            p
            for p in [
                regime,
                volatility_bucket,
                liquidity_state,
                absorption_side,
                absorption_strength,
            ]
            if p
        ]
        if not parts:
            return None
        return "|".join(str(p).upper() for p in parts)

    # ------------------------------------------------------------------
    # Prediction (with context fallback chain)
    # ------------------------------------------------------------------

    def predict(
        self,
        current_phase: int,
        context_key: str | None = None,
        regime: str | None = None,
        volatility_bucket: str | None = None,
        liquidity_state: str | None = None,
        absorption_side: str | None = None,
        absorption_strength: str | None = None,
    ) -> dict[str, Any]:
        """
        Return next-phase probabilities given current phase and optional context.

        Context resolution order (most → least specific):
          1. Explicit context_key (legacy / override)
                    2. 5-way composite key: regime|volatility|liquidity|abs_side|abs_strength
                    3. 4-way composite key: regime|volatility|liquidity|abs_side
                    4. 3-way composite key: regime|volatility_bucket|liquidity_state
                    5. 2-way combos: regime|volatility_bucket, regime|liquidity_state,
                           volatility_bucket|liquidity_state
                    6. 2-way absorption key: absorption_side|absorption_strength
                    7. 1-way keys: regime, volatility_bucket, liquidity_state,
                                                 absorption_side, absorption_strength
                    8. Unconditional matrix

        This fallback chain means the model always uses the richest available
        conditioning without requiring all 3 variables to be populated.
        """
        p = int(current_phase)
        if not (0 <= p < _N_PHASES):
            p = 0

        # Build candidate context keys in priority order
        r = str(regime).upper() if regime else None
        v = str(volatility_bucket).upper() if volatility_bucket else None
        lq = str(liquidity_state).upper() if liquidity_state else None
        a = str(absorption_side).upper() if absorption_side else None
        a_strength = str(absorption_strength).upper() if absorption_strength else None

        def _append_unique(keys: list[str], value: str | None) -> None:
            if value and value not in keys:
                keys.append(value)

        candidate_keys: list[str] = []
        if context_key:
            candidate_keys.append(str(context_key))
        # 5-way
        if r and v and lq and a and a_strength:
            _append_unique(candidate_keys, f"{r}|{v}|{lq}|{a}|{a_strength}")
        # 4-way
        if r and v and lq and a:
            _append_unique(candidate_keys, f"{r}|{v}|{lq}|{a}")
        # 3-way
        if r and v and lq:
            _append_unique(candidate_keys, f"{r}|{v}|{lq}")
        if r and v and a:
            _append_unique(candidate_keys, f"{r}|{v}|{a}")
        if r and lq and a:
            _append_unique(candidate_keys, f"{r}|{lq}|{a}")
        if v and lq and a:
            _append_unique(candidate_keys, f"{v}|{lq}|{a}")
        # 2-way combos
        if r and v:
            _append_unique(candidate_keys, f"{r}|{v}")
        if r and lq:
            _append_unique(candidate_keys, f"{r}|{lq}")
        if v and lq:
            _append_unique(candidate_keys, f"{v}|{lq}")
        if a and a_strength:
            _append_unique(candidate_keys, f"{a}|{a_strength}")
        if r and a:
            _append_unique(candidate_keys, f"{r}|{a}")
        if lq and a:
            _append_unique(candidate_keys, f"{lq}|{a}")
        # 1-way
        if r:
            _append_unique(candidate_keys, r)
        if v:
            _append_unique(candidate_keys, v)
        if lq:
            _append_unique(candidate_keys, lq)
        if a:
            _append_unique(candidate_keys, a)
        if a_strength:
            _append_unique(candidate_keys, a_strength)

        # Walk the chain; use first key that exists in the conditional dict
        used_context: str | None = None
        row: np.ndarray | None = None
        for ck in candidate_keys:
            if ck in self._conditional:
                row = self._conditional[ck][p]
                used_context = ck
                break

        # Fall back to unconditional
        if row is None:
            row = self._matrix[p]

        next_phase = int(np.argmax(row))
        return {
            "current_phase": p,
            "current_phase_name": _PHASE_NAMES[p],
            "next_phase": next_phase,
            "next_phase_name": _PHASE_NAMES[next_phase],
            "probabilities": row.tolist(),
            "confidence": float(row[next_phase]),
            "phase_names": list(_PHASE_NAMES.values()),
            "context_used": used_context,
        }

    def current_phase_frequency(self, phase: int) -> float:
        """How often does this phase appear in training data?"""
        p = max(0, min(_N_PHASES - 1, int(phase)))
        return float(self._phase_freq[p])

    # ------------------------------------------------------------------
    # Online adaptation
    # ------------------------------------------------------------------

    def update_online(
        self,
        previous_phase: int,
        current_phase: int,
        context_key: str | None = None,
        learning_rate: float = 1.0,
        decay: float = 0.0,
    ) -> dict[str, Any]:
        """
        Incrementally update transition probabilities from the latest observed transition.

        Parameters
        ----------
        previous_phase : observed phase at t-1
        current_phase  : observed phase at t
        context_key    : optional context bucket (for conditional matrix update)
        learning_rate  : added count mass for the observed transition
        decay          : optional fading-memory factor in [0,1)
        """
        p_prev = int(previous_phase)
        p_curr = int(current_phase)
        if not (0 <= p_prev < _N_PHASES and 0 <= p_curr < _N_PHASES):
            return {"updated": False, "reason": "invalid_phase", "previous": p_prev, "current": p_curr}

        lr = max(0.0, float(learning_rate))
        d = min(0.999, max(0.0, float(decay)))

        if d > 0.0:
            self._counts *= (1.0 - d)
            for key in list(self._conditional_counts.keys()):
                self._conditional_counts[key] *= (1.0 - d)

        self._counts[p_prev][p_curr] += lr
        self._total_transitions = int(round(float(self._counts.sum())))
        self._matrix = self._normalise(self._counts)

        if context_key:
            key = str(context_key)
            cond_counts = self._conditional_counts.get(key)
            if cond_counts is None:
                cond_counts = np.zeros((_N_PHASES, _N_PHASES), dtype=float)
            cond_counts[p_prev][p_curr] += lr
            self._conditional_counts[key] = cond_counts
            self._conditional[key] = self._normalise(cond_counts)

        return {
            "updated": True,
            "previous_phase": p_prev,
            "current_phase": p_curr,
            "context_key": str(context_key) if context_key else None,
            "learning_rate": lr,
            "decay": d,
            "total_transitions": self._total_transitions,
        }

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "matrix": self._matrix.tolist(),
            "counts": self._counts.tolist(),
            "phase_freq": self._phase_freq.tolist(),
            "total_transitions": self._total_transitions,
            "conditional": {k: v.tolist() for k, v in self._conditional.items()},
            "conditional_counts": {k: v.tolist() for k, v in self._conditional_counts.items()},
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "WheelTransitionModel":
        obj = cls()
        if not Path(path).exists():
            return obj
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            obj._matrix = np.array(data.get("matrix") or obj._matrix.tolist(), dtype=float)
            obj._counts = np.array(data.get("counts") or obj._counts.tolist(), dtype=float)
            obj._phase_freq = np.array(data.get("phase_freq") or [0.25] * 4, dtype=float)
            obj._total_transitions = int(data.get("total_transitions") or 0)
            obj._conditional = {
                k: np.array(v, dtype=float)
                for k, v in (data.get("conditional") or {}).items()
            }
            obj._conditional_counts = {
                k: np.array(v, dtype=float)
                for k, v in (data.get("conditional_counts") or {}).items()
            }
        except Exception:
            pass
        return obj

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _uniform_matrix() -> np.ndarray:
        return np.full((_N_PHASES, _N_PHASES), 1.0 / _N_PHASES)

    @staticmethod
    def _normalise(counts: np.ndarray) -> np.ndarray:
        """Row-normalise with Laplace smoothing (avoids zero-probability transitions)."""
        smoothed = counts + 0.5      # add half-count to every cell
        row_sums = smoothed.sum(axis=1, keepdims=True)
        return smoothed / np.maximum(row_sums, 1e-9)

    def summary(self) -> str:
        lines = [
            f"Total transitions: {self._total_transitions}",
            f"Phase frequency:   {dict(zip(_PHASE_NAMES.values(), self._phase_freq.round(3).tolist()))}",
            "Transition matrix (rows=current, cols=next):",
        ]
        header = "         " + "  ".join(f"{_PHASE_NAMES[j][:6]:>6}" for j in range(_N_PHASES))
        lines.append(header)
        for i in range(_N_PHASES):
            row = "  ".join(f"{self._matrix[i][j]:.3f}" for j in range(_N_PHASES))
            lines.append(f"  {_PHASE_NAMES[i][:6]:>6}: {row}")
        return "\n".join(lines)
