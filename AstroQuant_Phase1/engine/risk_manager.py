class RiskManager:

    def approve(self, signal, account):
        payload = signal or {}
        acc = account or {}

        def _as_float(value, default=0.0):
            try:
                return float(value)
            except Exception:
                return float(default)

        balance = _as_float(acc.get("balance", 0), 0)
        risk_percent = _as_float(payload.get("risk_percent", 0), 0)
        daily_loss = _as_float(acc.get("daily_loss", 0), 0)
        daily_limit = _as_float(acc.get("daily_limit", 0), 0)
        overall_loss = _as_float(acc.get("overall_loss", 0), 0)
        max_limit = _as_float(acc.get("max_limit", 0), 0)
        max_per_trade = _as_float(acc.get("max_per_trade", 0), 0)

        risk_amount = balance * (risk_percent / 100)

        if daily_loss >= daily_limit:
            return False

        if overall_loss >= max_limit:
            return False

        if risk_amount > max_per_trade:
            return False

        return True
