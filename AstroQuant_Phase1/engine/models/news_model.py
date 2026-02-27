class NewsModel:

    def generate(self, data):
        if (
            data.get("high_impact_news")
            and data.get("range_break")
            and data.get("volume_expansion")
            and float(data.get("spread", 999) or 999) < 30
        ):
            direction = str(data.get("direction", "")).upper()
            if direction not in ["BUY", "SELL"]:
                return None

            atr = float(data.get("atr", 0) or 0)
            price = float(data.get("price", 0) or 0)
            half_atr = atr / 2 if atr > 0 else 5
            stop = price - half_atr if direction == "BUY" else price + half_atr

            return {
                "model": "NEWS_BREAKOUT",
                "side": direction,
                "confidence": float(data.get("confidence", 0) or 0),
                "entry": data.get("price"),
                "stop": stop,
                "rr": 1.8,
                "risk_percent": 0.3,
            }

        return None
