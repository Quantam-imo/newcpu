class ExpansionModel:

	def check(self, data, symbol):
		if data["volatility_breakout"]:
			return {
				"model": "EXPANSION",
				"direction": "SELL",
				"confidence": 70,
				"rr": 3,
				"performance_weight": 1.0
			}

		return None
