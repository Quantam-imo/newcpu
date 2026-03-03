class RegimeEngine:

    def __init__(self):
        self.active_models = []

    def determine_active_models(
        self,
        volatility_regime,
        news_mode,
        session,
        liquidity_vacuum,
        drawdown,
    ):
        if volatility_regime == "LOW_VOL":
            models = ["ICT", "GANN"]
        elif volatility_regime == "HIGH_VOL":
            models = ["EXPANSION", "ICEBERG"]
        else:
            models = ["ICT", "ICEBERG", "EXPANSION", "GANN", "NEWS"]

        if news_mode == "BREAKOUT_ONLY":
            models = ["EXPANSION"]

        if news_mode == "HALT":
            models = []

        if liquidity_vacuum:
            models = ["EXPANSION"]

        if session == "ASIA":
            models = ["ICT"]

        if drawdown > 2000:
            models = ["ICT"]

        self.active_models = models
        return models
