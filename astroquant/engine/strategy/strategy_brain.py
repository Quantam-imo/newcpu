import json
import os
import numpy as np

_DEFAULT_BRAIN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data", "strategy_brain.json"
)


class StrategyBrain:
    """
    Combines signals from multiple engines (ICT, Gann, Astro, etc.)
    Applies AI-style weighting, adapts to market regime, and auto-switches strategies.
    """
    def __init__(self, engine_names, persist_path: str | None = None):
        self.engine_names = engine_names
        self._persist_path = persist_path or _DEFAULT_BRAIN_PATH
        # Initial equal weights
        self.weights = {name: 1.0 / len(engine_names) for name in engine_names}
        self.performance = {name: [] for name in engine_names}
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Restore weights and performance history from disk (if the file exists)."""
        try:
            with open(self._persist_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for name in self.engine_names:
                if name in data.get("weights", {}):
                    self.weights[name] = float(data["weights"][name])
                if name in data.get("performance", {}):
                    self.performance[name] = list(data["performance"][name])
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass  # first run or corrupt file — start fresh

    def _save(self) -> None:
        """Persist current weights and performance history to disk."""
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            tmp = self._persist_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"weights": self.weights, "performance": self.performance}, fh)
            os.replace(tmp, self._persist_path)
        except OSError:
            pass

    def update_performance(self, engine_name, result):
        # result: +1 for win, -1 for loss, 0 for neutral
        self.performance[engine_name].append(result)
        # Keep only recent N results
        N = 100
        if len(self.performance[engine_name]) > N:
            self.performance[engine_name] = self.performance[engine_name][-N:]
        self._recalculate_weights()
        self._save()

    def _recalculate_weights(self):
        # Simple Sharpe-like weighting: mean / std
        for name in self.engine_names:
            perf = self.performance[name]
            if len(perf) < 10:
                self.weights[name] = 1.0 / len(self.engine_names)
            else:
                mean = np.mean(perf)
                std = np.std(perf) + 1e-6
                self.weights[name] = max(0.01, mean / std)
        # Normalize
        total = sum(self.weights.values())
        for name in self.engine_names:
            self.weights[name] /= total

    def decide(self, signals, market_regime=None):
        """
        signals: dict of {engine_name: signal_dict or None}
        market_regime: optional, can be used to further adjust weights
        Returns: best signal (dict), engine name, and weights
        """
        # Filter only engines with signals
        valid = {k: v for k, v in signals.items() if v is not None}
        if not valid:
            return None, None, self.weights.copy()
        # Weighted voting
        scores = {}
        for name, sig in valid.items():
            # Example: use signal confidence if present, else 1
            conf = sig.get("confidence", 1.0)
            scores[name] = self.weights.get(name, 0) * conf
        if not scores:
            return None, None, self.weights.copy()
        # Pick engine with highest score
        best_engine = max(scores, key=scores.get)
        return valid[best_engine], best_engine, self.weights.copy()
