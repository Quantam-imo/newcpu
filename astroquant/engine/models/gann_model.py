class GannModel:

	def check(self, data, symbol):
		if data["time_cycle_alignment"]:
			return {
				"model": "GANN",
				"direction": data["trend"],
				"confidence": 65,
				"rr": 2,
				"performance_weight": 1.0
			}

		return None
