class AIGovernanceEngine:

    def __init__(self):
        self.max_trades_per_day = 5
        self.current_trades_today = 0
        self.min_confidence_required = 55

    def register_trade(self):
        self.current_trades_today += 1

    def reset_day(self):
        self.current_trades_today = 0

    def trade_allowed(self, fusion_result):
        signal = fusion_result or {}

        if self.current_trades_today >= self.max_trades_per_day:
            return False, "Max daily trades reached"

        try:
            confidence = float(signal.get("confidence", 0) or 0)
        except Exception:
            confidence = 0.0

        if confidence < self.min_confidence_required:
            return False, "Confidence too low"

        return True, "Allowed"
