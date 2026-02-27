class OrderFlowEngine:

    def analyze(self, bars):

        if len(bars) < 20:
            return {"delta": 0, "imbalance": 0}

        recent = bars[-20:]
        total_volume = sum(bar["volume"] for bar in recent)
        avg_volume = total_volume / len(recent)

        last = recent[-1]

        delta = (last["close"] - last["open"]) * last["volume"]

        imbalance = 0
        if last["volume"] > 1.5 * avg_volume:
            imbalance = 1

        return {
            "delta": delta,
            "imbalance": imbalance
        }
