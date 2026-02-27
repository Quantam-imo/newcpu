from datetime import datetime, timezone


class AstroEngine:

    def analyze(self, symbol):
        hour = datetime.now(timezone.utc).hour

        if 6 <= hour < 10:
            phase = "Expansion"
            volatility_bias = "High"
            window = "London Active"
        elif 13 <= hour < 17:
            phase = "Transition"
            volatility_bias = "Medium"
            window = "New York Active"
        elif 17 <= hour < 21:
            phase = "Distribution"
            volatility_bias = "Medium"
            window = "US Afternoon"
        else:
            phase = "Compression"
            volatility_bias = "Low"
            window = "Off Session"

        return {
            "phase": phase,
            "volatility_bias": volatility_bias,
            "window": window,
        }
