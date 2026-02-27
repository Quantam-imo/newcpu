class GannModel:

    def generate(self, data):
        if (
            data.get("gann_cycle_hit")
            and data.get("angle_respected")
            and data.get("divergence")
        ):
            direction = str(data.get("direction", "")).upper()
            if direction not in ["BUY", "SELL"]:
                return None

            return {
                "model": "GANN",
                "side": direction,
                "confidence": float(data.get("confidence", 0) or 0),
                "entry": data.get("price"),
                "stop": data.get("swing_low") if direction == "BUY" else data.get("swing_high"),
                "rr": 2,
                "risk_percent": 0.5,
            }

        return None
