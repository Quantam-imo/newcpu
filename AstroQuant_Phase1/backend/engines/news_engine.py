class NewsEngine:

    def analyze(self, symbol, price_data):
        if len(price_data) < 6:
            return {
                "high_impact": "No major event detected",
                "reaction_bias": "Neutral",
                "trade_halt": False,
            }

        closes = [float(bar.get("close", 0) or 0) for bar in price_data[-20:]]
        ranges = [
            abs(float(bar.get("high", 0) or 0) - float(bar.get("low", 0) or 0))
            for bar in price_data[-20:]
        ]

        base_price = closes[0] if closes and closes[0] else 1.0
        displacement = abs(closes[-1] - closes[0]) / base_price
        avg_range = (sum(ranges) / len(ranges)) if ranges else 0
        avg_price = (sum(closes) / len(closes)) if closes else 1.0
        range_ratio = (avg_range / avg_price) if avg_price else 0

        event_score = displacement + range_ratio

        if event_score > 0.01:
            high_impact = "Volatility spike detected"
            reaction_bias = "Volatile Upside" if closes[-1] >= closes[0] else "Volatile Downside"
            trade_halt = True
        elif event_score > 0.004:
            high_impact = "Elevated macro sensitivity"
            reaction_bias = "Directional"
            trade_halt = False
        else:
            high_impact = "No major event detected"
            reaction_bias = "Neutral"
            trade_halt = False

        return {
            "high_impact": high_impact,
            "reaction_bias": reaction_bias,
            "trade_halt": trade_halt,
        }
