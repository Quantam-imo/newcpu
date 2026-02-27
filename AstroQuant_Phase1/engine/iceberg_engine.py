class IcebergEngine:

    def detect(self, orderflow, last_bar):

        body = abs(last_bar["close"] - last_bar["open"])
        range_ = last_bar["high"] - last_bar["low"]

        if range_ == 0:
            return None

        body_ratio = body / range_

        if orderflow["imbalance"] == 1 and body_ratio < 0.35:
            direction = "BUY_ABSORPTION" if last_bar["close"] > last_bar["open"] else "SELL_ABSORPTION"

            return {
                "type": direction,
                "price": last_bar["close"],
                "confidence": 70
            }

        return None
