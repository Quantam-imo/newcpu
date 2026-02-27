class ICTEngine:

    def detect_fvg(self, bars):
        signals = []

        for i in range(2, len(bars)):
            prev = bars[i-2]
            curr = bars[i]

            # Bullish FVG
            if curr["low"] > prev["high"]:
                signals.append({
                    "type": "BULLISH_FVG",
                    "price": curr["low"]
                })

            # Bearish FVG
            if curr["high"] < prev["low"]:
                signals.append({
                    "type": "BEARISH_FVG",
                    "price": curr["high"]
                })

        return signals

    def analyze(self, bars):

        fvg = self.detect_fvg(bars)

        score = 0
        direction = None

        if fvg:
            last = fvg[-1]
            if "BULLISH" in last["type"]:
                score += 30
                direction = "BUY"
            else:
                score -= 30
                direction = "SELL"

        return {
            "ict_score": score,
            "ict_direction": direction,
            "fvg": fvg[-1] if fvg else None
        }
