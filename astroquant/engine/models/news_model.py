class NewsModel:

	def check(self, data, symbol):
		if data["high_impact_news"]:
			return {
				"model": "NEWS",
				"direction": "NONE",
				"confidence": 90,
				"rr": 0,
				"performance_weight": 1.0
			}

		return None
