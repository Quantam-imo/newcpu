from backend.services.market_data_service import safe_float


class LiquidityEngine:

    def analyze(self, bars):
        if not bars:
            return {
                "range_low": 0,
                "range_high": 0,
                "equilibrium": 0,
                "bias": "Neutral",
                "zone": "Unavailable",
            }

        recent = bars[-40:]
        range_low = min(safe_float(bar.get("low", 0)) for bar in recent)
        range_high = max(safe_float(bar.get("high", 0)) for bar in recent)
        equilibrium = (range_low + range_high) / 2 if range_high >= range_low else 0

        last_close = safe_float(recent[-1].get("close", 0))
        bias = "Sell-side" if last_close >= equilibrium else "Buy-side"

        zone = f"{round(range_low, 2)}-{round(range_high, 2)}"

        return {
            "range_low": round(range_low, 2),
            "range_high": round(range_high, 2),
            "equilibrium": round(equilibrium, 2),
            "bias": bias,
            "zone": zone,
        }
