from engine.model_performance import ModelPerformance


class AIDecisionEngine:

    def __init__(self, performance=None):
        self.performance = performance or ModelPerformance()
        self.model_weights = {
            "ICT_LIQUIDITY": 1.2,
            "ICEBERG": 1.1,
            "GANN": 1.0,
            "NEWS_BREAKOUT": 0.9,
            "EXPANSION": 1.0,
        }

    def rank(self, signals):
        if not signals:
            return []

        scored = []
        for signal in signals:
            model_name = signal.get("model")
            weight = self.model_weights.get(model_name, 1.0)
            performance_boost = self.performance.get_weight_adjustment(model_name)

            confidence = float(signal.get("confidence", 0) or 0)
            rr_value = float(signal.get("rr", 1) or 1)
            ai_score = confidence * weight * performance_boost * rr_value

            candidate = dict(signal)
            candidate["ai_score"] = ai_score
            candidate["model_weight"] = weight
            candidate["performance_boost"] = performance_boost
            scored.append(candidate)

        scored.sort(key=lambda item: item.get("ai_score", 0), reverse=True)
        return scored

    def evaluate(self, signals):
        ranked = self.rank(signals)
        if not ranked:
            return None
        return ranked[0]
