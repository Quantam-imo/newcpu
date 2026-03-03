class ICTModel:

	def check(self, data, symbol):
		# Example placeholder logic (replace with real ICT later)
		if data["trend"] == "UP" and data["liquidity_sweep"]:
			return {
				"model": "ICT",
				"direction": "BUY",
				"confidence": 80,
				"rr": 3,
				"performance_weight": 1.0
			}

		return None
