import numpy as np

class StrategyBrain:
    """
    Combines signals from multiple engines (ICT, Gann, Astro, etc.)
    Applies AI-style weighting, adapts to market regime, and auto-switches strategies.
    """
    def __init__(self, engine_names):
        self.engine_names = engine_names
        # Initial equal weights
        self.weights = {name: 1.0 / len(engine_names) for name in engine_names}
        self.performance = {name: [] for name in engine_names}

    def update_performance(self, engine_name, result):
        # result: +1 for win, -1 for loss, 0 for neutral
        self.performance[engine_name].append(result)
        # Keep only recent N results
        N = 100
        if len(self.performance[engine_name]) > N:
            self.performance[engine_name] = self.performance[engine_name][-N:]
        self._recalculate_weights()

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
