# Prop Safe Trade Filter for AstroQuant

class PropSafeTradeFilter:
    """
    Applies proprietary safety checks to trades:
    - RR validation
    - Cooldown
    - Daily trade limit
    - Spread filter
    """
    def __init__(self, max_trades_per_day=10, min_rr=1.5, cooldown_minutes=5, max_spread=2.0):
        self.max_trades_per_day = max_trades_per_day
        self.min_rr = min_rr
        self.cooldown_minutes = cooldown_minutes
        self.max_spread = max_spread
        self.trade_log = []

    def is_trade_allowed(self, trade, current_time, spread, rr):
        # Check RR
        if rr < self.min_rr:
            return False, "RR below minimum"
        # Check spread
        if spread > self.max_spread:
            return False, "Spread too high"
        # Check cooldown
        if self.trade_log and (current_time - self.trade_log[-1]) < self.cooldown_minutes * 60:
            return False, "Cooldown active"
        # Check daily trade limit
        trades_today = [t for t in self.trade_log if self._is_today(t, current_time)]
        if len(trades_today) >= self.max_trades_per_day:
            return False, "Daily trade limit reached"
        # Passed all checks
        self.trade_log.append(current_time)
        return True, "OK"

    def _is_today(self, timestamp, now):
        from datetime import datetime
        return datetime.fromtimestamp(timestamp).date() == datetime.fromtimestamp(now).date()
