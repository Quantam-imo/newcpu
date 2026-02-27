class ClawbotEngine:

    def check_anomaly(self, loss_streak, spread, slippage):

        if loss_streak >= 3:
            return "Loss streak anomaly"

        if spread > 40:
            return "Spread anomaly"

        if slippage > 2:
            return "Slippage anomaly"

        return None
