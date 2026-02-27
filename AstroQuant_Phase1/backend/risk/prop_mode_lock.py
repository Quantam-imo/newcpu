class PropModeLock:

    def __init__(self):
        self.phase = "PHASE_1"  # PHASE_1, PHASE_2, FUNDED

        self.rules = {
            "PHASE_1": {
                "target": 0.08,
                "daily_loss": 0.03,
                "max_loss": 0.08,
                "risk_per_trade": 0.003
            },
            "PHASE_2": {
                "target": 0.05,
                "daily_loss": 0.03,
                "max_loss": 0.08,
                "risk_per_trade": 0.0025
            },
            "FUNDED": {
                "target": None,
                "daily_loss": 0.02,
                "max_loss": 0.06,
                "risk_per_trade": 0.002
            }
        }

    def set_phase(self, phase):
        if phase in self.rules:
            self.phase = phase
            return True
        return False

    def get_rules(self):
        return self.rules[self.phase]

    def check_limits(self, start_balance, current_balance, daily_loss):

        rule = self.rules[self.phase]

        max_loss_allowed = start_balance * rule["max_loss"]
        daily_loss_allowed = start_balance * rule["daily_loss"]

        if daily_loss <= -daily_loss_allowed:
            return False, "Daily loss limit hit"

        if (start_balance - current_balance) >= max_loss_allowed:
            return False, "Max loss limit hit"

        return True, "Within limits"

    def withdrawal_trigger(self, start_balance, current_balance):
        if self.phase != "FUNDED":
            return False
        if current_balance >= start_balance + 2000:
            return True
        return False
