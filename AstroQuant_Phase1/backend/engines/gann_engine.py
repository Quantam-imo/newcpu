class GannEngine:

    def analyze(self, symbol, price_data):
        if len(price_data) < 2:
            return {
                "day_count": len(price_data),
                "bar_count": len(price_data),
                "square_level": "45°",
                "next_cycle": "Pending",
            }

        day_count = len(price_data)
        bar_count = len(price_data[-20:])

        square_level = "45°" if price_data[-1]["close"] > price_data[-2]["close"] else "90°"

        return {
            "day_count": day_count,
            "bar_count": bar_count,
            "square_level": square_level,
            "next_cycle": "2 Days",
        }
