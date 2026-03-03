class ConfidenceEngine:

    def __init__(self):
        self.base_threshold = 0.70

    def adjust_threshold(
        self,
        drawdown,
        loss_streak,
        regime,
        avg_slippage,
        model_win_rate,
    ):
        threshold = self.base_threshold

        if drawdown > 1000:
            threshold += 0.05
        if drawdown > 2000:
            threshold += 0.10

        if loss_streak >= 3:
            threshold += 0.05
        if loss_streak >= 5:
            threshold += 0.10

        if regime == "LOW_VOL":
            threshold += 0.05

        if avg_slippage > 2:
            threshold += 0.05

        if model_win_rate < 0.45:
            threshold += 0.05

        if regime == "HIGH_VOL" and model_win_rate > 0.60:
            threshold -= 0.03

        threshold = max(0.65, min(0.85, threshold))
        return threshold
