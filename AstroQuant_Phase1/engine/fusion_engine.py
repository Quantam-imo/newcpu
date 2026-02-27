

from backend.ai.learning_engine import LearningEngine

class FusionEngine:

    def __init__(self):
        self.learning = LearningEngine()

    def combine(self, orderflow, iceberg, ict, gann, astro, regime, active_model="fusion"):

        score = 0

        score += orderflow["delta"] * 0.00001
        score += ict["ict_score"]
        score += gann["gann_score"]
        score += astro["astro_score"]
        score += regime["regime_score"]

        if iceberg:
            score += 40

        # Adaptive model weighting
        model_weight = self.learning.get_model_weight(active_model)
        confidence = min(abs(int(score * model_weight)), 100)
        direction = "BUY" if score > 0 else "SELL"

        return {
            "direction": direction,
            "confidence": confidence,
            "total_score": score,
            "model_weight": model_weight
        }
