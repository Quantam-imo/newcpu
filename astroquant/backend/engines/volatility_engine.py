class VolatilityEngine:

    def __init__(self):
        self.last_atr = None

    def calculate_atr(self, highs, lows, closes, period=14):
        trs = []

        if not highs or not lows or not closes:
            return None

        limit = min(len(highs), len(lows), len(closes))
        for i in range(1, limit):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)

        if len(trs) < period:
            return None

        atr_window = trs[-period:]
        atr = sum(atr_window) / len(atr_window)
        self.last_atr = atr
        return atr

    def volatility_state(self, atr, baseline):
        if atr is None or baseline is None or baseline <= 0:
            return "NORMAL"

        ratio = atr / baseline

        if ratio > 2.0:
            return "EXTREME"
        elif ratio > 1.5:
            return "HIGH"
        else:
            return "NORMAL"
