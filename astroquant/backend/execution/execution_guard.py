import time


class ExecutionGuard:

    def __init__(self):
        self.max_slippage = 2.0
        self.execution_timeout = 5
        self.system_health = {
            "execution_status": "OK",
            "last_error": None,
            "halted_at": None,
        }

    def validate_sl_tp(self, sl, tp, entry):
        if sl is None or tp is None:
            return False, "SL or TP missing"

        if sl == entry or tp == entry:
            return False, "Invalid SL/TP"

        return True, "OK"

    def check_slippage(self, expected_price, fill_price):
        slippage = abs(float(fill_price) - float(expected_price))

        if slippage > self.max_slippage:
            return False, slippage

        return True, slippage

    def wait_for_fill(self, get_position_callback):
        start_time = time.time()

        while time.time() - start_time < self.execution_timeout:
            position = get_position_callback()
            if position:
                return True, position
            time.sleep(0.5)

        return False, None

    def verify_position(self, position_data, expected_symbol, expected_volume):
        if not position_data:
            return False, "Position data missing"

        symbol = str(position_data.get("symbol", "") or "").strip().upper()
        volume = position_data.get("volume")
        sl = position_data.get("sl")
        tp = position_data.get("tp")

        if symbol and expected_symbol and symbol != str(expected_symbol).upper():
            return False, "Symbol mismatch"

        if volume is None:
            return False, "Volume missing"

        if float(volume) != float(expected_volume):
            return False, "Partial fill detected"

        if sl is None or tp is None:
            return False, "SL/TP missing in open position"

        return True, "OK"

    def halt(self, reason):
        import logging, traceback
        logging.basicConfig(level=logging.ERROR)
        logging.error("Execution HALTED: %s\n%s", str(reason), traceback.format_stack())
        self.system_health["execution_status"] = "HALTED"
        self.system_health["last_error"] = str(reason)
        self.system_health["halted_at"] = int(time.time())

    def reset(self):
        self.system_health["execution_status"] = "OK"
        self.system_health["last_error"] = None
        self.system_health["halted_at"] = None

    def is_halted(self):
        return self.system_health.get("execution_status") == "HALTED"

    def health_snapshot(self):
        return {
            "execution_status": self.system_health.get("execution_status"),
            "last_error": self.system_health.get("last_error"),
            "halted_at": self.system_health.get("halted_at"),
            "max_slippage": self.max_slippage,
            "execution_timeout": self.execution_timeout,
        }
