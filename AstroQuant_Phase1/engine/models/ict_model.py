class ICTModel:

    def generate(self, data):
        if (
            data.get("liquidity_sweep")
            and data.get("bos")
            and data.get("fvg")
            and float(data.get("confidence", 0) or 0) >= 70
        ):
            direction = str(data.get("direction", "")).upper()
            if direction not in ["BUY", "SELL"]:
                return None

            return {
                "model": "ICT_LIQUIDITY",
                "side": direction,
                "confidence": float(data.get("confidence", 0) or 0),
                "entry": data.get("price"),
                "stop": data.get("fvg_low") if direction == "BUY" else data.get("fvg_high"),
                "rr": 3,
                "risk_percent": 0.5,
            }

        return None
