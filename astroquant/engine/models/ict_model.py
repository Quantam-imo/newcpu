class ICTModel:

	def check(self, data, symbol):
		# Realistic ICT logic: trend, liquidity, order block, FVG, and breaker checks
		if (
			data.get("trend") == "UP"
			and data.get("liquidity_sweep", False)
			and data.get("order_block", "") == "BULLISH"
			and data.get("fvg", False)
		):
			return {
				"model": "ICT",
				"direction": "BUY",
				"confidence": 90,
				"rr": 4,
				"performance_weight": 1.1
			}
		elif (
			data.get("trend") == "DOWN"
			and data.get("liquidity_sweep", False)
			and data.get("order_block", "") == "BEARISH"
			and data.get("breaker", False)
		):
			return {
				"model": "ICT",
				"direction": "SELL",
				"confidence": 88,
				"rr": 3.5,
				"performance_weight": 1.05
			}
		return None
