class GannEngine:

    def analyze(self, bars):

        if len(bars) < 10:
            return {"gann_score": 0}

        high = max(bar["high"] for bar in bars[-20:])
        low = min(bar["low"] for bar in bars[-20:])

        range_ = high - low

        last = bars[-1]["close"]

        level_50 = low + 0.5 * range_
        level_100 = low + 1.0 * range_

        score = 0

        if last > level_50:
            score += 20

        if last > level_100:
            score += 30

        return {
            "gann_score": score,
            "range": range_,
            "level_50": level_50,
            "level_100": level_100
        }
