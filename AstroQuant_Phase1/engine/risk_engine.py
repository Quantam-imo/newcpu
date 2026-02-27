
from backend.risk.prop_mode_lock import PropModeLock

class RiskEngine:

    def __init__(self):
        self.start_balance = 50000
        self.current_balance = 50000
        self.daily_loss = 0
        self.prop_lock = PropModeLock()

    def update_losses(self, daily_loss, total_loss):
        self.daily_loss = daily_loss
        self.current_balance = self.start_balance + total_loss

    def allowed(self):
        rules = self.prop_lock.get_rules()
        allowed, reason = self.prop_lock.check_limits(
            self.start_balance,
            self.current_balance,
            self.daily_loss
        )
        if not allowed:
            return False
        return True

    def daily_loss_exceeded(self):
        rules = self.prop_lock.get_rules()
        daily_loss_limit = self.start_balance * rules["daily_loss"]
        return self.daily_loss <= -daily_loss_limit

    def get_balance(self):
        return self.current_balance
