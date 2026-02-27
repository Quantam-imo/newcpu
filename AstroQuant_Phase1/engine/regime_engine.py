class RegimeEngine:

    def detect(self, bars):

        if len(bars) < 20:
            return {"regime": "UNKNOWN", "regime_score": 0}

        last = bars[-1]
        avg_range = sum(bar["high"] - bar["low"] for bar in bars[-20:]) / 20

        current_range = last["high"] - last["low"]

        if current_range > 1.5 * avg_range:
            return {"regime": "EXPANSION", "regime_score": 20}

        return {"regime": "NORMAL", "regime_score": 0}
