class SlippageGuard:

    def __init__(self):
        self.history = []
        self.window = 30

    def record(self, slippage):
        self.history.append(float(slippage))
        if len(self.history) > self.window:
            self.history.pop(0)

    def average_slippage(self):
        if not self.history:
            return 0.0
        return sum(self.history) / len(self.history)

    def validate(self, intended_price, filled_price):
        slippage = abs(filled_price - intended_price)
        self.record(slippage)

        if slippage > 2:  # 2 point threshold
            return False, "Excess slippage"

        return True, "OK"
