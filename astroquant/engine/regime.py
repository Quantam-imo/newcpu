class RegimeEngine:

	def detect(self, market_data):
		if market_data.get("volatility_breakout"):
			return "VOLATILE"

		if market_data.get("absorption"):
			return "ACCUMULATION"

		return "TREND"

	def get_weight(self, regime):
		if regime == "VOLATILE":
			return 1.2
		if regime == "ACCUMULATION":
			return 1.1
		if regime == "TREND":
			return 1.3

		return 1
