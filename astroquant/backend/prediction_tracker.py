"""
Prediction Tracker — persistence layer for LearningFeedbackEngine.

Stores predictions, outcomes, and calibrated weights to a JSON file so the
learning loop survives process restarts.

Philosophy: "The market teaches every session. We must remember every lesson."
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "prediction_tracker.json"

_SCHEMA_VERSION = 1


class PredictionTracker:
    """
    Thread-safe, file-backed store for predictions, outcomes, and signal weights.

    Usage::

        tracker = PredictionTracker()          # default path
        tracker = PredictionTracker(path)      # custom path

        tracker.save_prediction({...})
        tracker.save_outcome({...})
        tracker.save_weights({...})

        preds   = tracker.load_predictions()
        weights = tracker.load_weights()

    Atomic writes: data is written to a temporary file then renamed, so a crash
    during write never corrupts the existing store.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else _DEFAULT_PATH
        self._lock = threading.Lock()
        self._ensure_file()

    # ── public API ───────────────────────────────────────────────────────────

    def save_prediction(self, prediction: dict[str, Any]) -> None:
        """Upsert a prediction record: update in-place if same ID exists, else append."""
        pid = prediction.get("id")
        with self._lock:
            data = self._read()
            preds = data["predictions"]
            idx = next((i for i, p in enumerate(preds) if p.get("id") == pid), None)
            if idx is not None:
                preds[idx] = prediction
            else:
                preds.append(prediction)
            data["meta"]["updated_at"] = int(time.time())
            self._write(data)

    def save_outcome(self, outcome: dict[str, Any]) -> None:
        """Upsert an outcome: update in-place if same prediction_id exists, else append."""
        pid = outcome.get("prediction_id")
        with self._lock:
            data = self._read()
            outcomes = data["outcomes"]
            idx = next((i for i, o in enumerate(outcomes) if o.get("prediction_id") == pid), None)
            if idx is not None:
                outcomes[idx] = outcome
            else:
                outcomes.append(outcome)
            data["meta"]["updated_at"] = int(time.time())
            self._write(data)

    def save_weights(self, weights: dict[str, float]) -> None:
        """Overwrite the persisted signal weights."""
        with self._lock:
            data = self._read()
            data["weights"] = {k: float(v) for k, v in weights.items()}
            data["meta"]["updated_at"] = int(time.time())
            self._write(data)

    def save_predictions_bulk(self, predictions: list[dict[str, Any]]) -> None:
        """Replace the entire predictions list in one atomic write."""
        with self._lock:
            data = self._read()
            data["predictions"] = list(predictions)
            data["meta"]["updated_at"] = int(time.time())
            self._write(data)

    def save_outcomes_bulk(self, outcomes: list[dict[str, Any]]) -> None:
        """Replace the entire outcomes list in one atomic write."""
        with self._lock:
            data = self._read()
            data["outcomes"] = list(outcomes)
            data["meta"]["updated_at"] = int(time.time())
            self._write(data)

    def load_predictions(self) -> list[dict[str, Any]]:
        """Return all stored predictions."""
        with self._lock:
            return list(self._read().get("predictions", []))

    def load_outcomes(self) -> list[dict[str, Any]]:
        """Return all stored outcomes."""
        with self._lock:
            return list(self._read().get("outcomes", []))

    def load_weights(self) -> dict[str, float]:
        """Return persisted signal weights, or empty dict if never saved."""
        with self._lock:
            raw = self._read().get("weights", {})
            return {k: float(v) for k, v in raw.items()}

    def clear(self) -> None:
        """Reset the store to an empty state (used in tests)."""
        with self._lock:
            self._write(self._empty_doc())

    @property
    def path(self) -> Path:
        return self._path

    # ── internal ─────────────────────────────────────────────────────────────

    def _ensure_file(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write(self._empty_doc())

    @staticmethod
    def _empty_doc() -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "meta": {"created_at": int(time.time()), "updated_at": int(time.time())},
            "weights": {},
            "predictions": [],
            "outcomes": [],
        }

    def _read(self) -> dict[str, Any]:
        try:
            text = self._path.read_text(encoding="utf-8")
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("store is not a JSON object")
            # Ensure expected top-level keys are present.
            data.setdefault("weights", {})
            data.setdefault("predictions", [])
            data.setdefault("outcomes", [])
            data.setdefault("meta", {})
            return data
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
            logging.warning("PredictionTracker: resetting corrupt store (%s)", exc)
            doc = self._empty_doc()
            self._write(doc)
            return doc

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(
            f"{self._path.stem}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
        )
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
