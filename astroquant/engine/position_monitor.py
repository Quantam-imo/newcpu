class PositionMonitor:

    def check_close(self, position, current_price):

        entry = position["entry_price"]
        direction = position["direction"]
        tp = position.get("tp", entry + 50)
        sl = position.get("sl", entry - 50)

        if direction == "BUY":
            if current_price >= tp:
                return True, tp - entry
            if current_price <= sl:
                return True, sl - entry

        if direction == "SELL":
            if current_price <= tp:
                return True, entry - tp
            if current_price >= sl:
                return True, entry - sl

        return False, 0
