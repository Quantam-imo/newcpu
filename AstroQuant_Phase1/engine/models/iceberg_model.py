class IcebergModel:

    def generate(self, data):
        if (
            data.get("absorption")
            and float(data.get("delta", 0) or 0) > 1500
            and data.get("volume_spike")
            and not data.get("high_impact_news")
        ):
            direction = str(data.get("direction", "")).upper()
            if direction not in ["BUY", "SELL"]:
                return None

            absorption_level = float(data.get("absorption_level", data.get("price", 0)) or 0)
            stop = absorption_level - 5 if direction == "BUY" else absorption_level + 5

            return {
                "model": "ICEBERG",
                "side": direction,
                "confidence": float(data.get("confidence", 0) or 0),
                "entry": data.get("price"),
                "stop": stop,
                "rr": 2.5,
                "risk_percent": 0.4,
            }

        return None
