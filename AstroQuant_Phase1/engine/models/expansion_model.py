class ExpansionModel:

    def generate(self, data):
        if (
            data.get("trend_structure")
            and data.get("ema_aligned")
            and data.get("pullback_50")
            and data.get("momentum")
        ):
            direction = str(data.get("direction", "")).upper()
            if direction not in ["BUY", "SELL"]:
                return None

            return {
                "model": "EXPANSION",
                "side": direction,
                "confidence": float(data.get("confidence", 0) or 0),
                "entry": data.get("price"),
                "stop": data.get("last_hl") if direction == "BUY" else data.get("last_lh"),
                "rr": 2.5,
                "risk_percent": 0.4,
            }

        return None
