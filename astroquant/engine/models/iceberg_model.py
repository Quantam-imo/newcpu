class IcebergModel:

	def __init__(self, orderflow_engine):
		self.orderflow = orderflow_engine

	def check(self, market_data, symbol):
		if not self.orderflow:
			return None

		trades = self.orderflow.get_recent_trades(
			dataset=market_data.get("dataset", "GLBX.MDP3"),
			symbol=symbol,
		)

		if not trades:
			return None

		delta, buy_volume, sell_volume = self.orderflow.calculate_delta(trades)

		absorption_levels = self.orderflow.detect_absorption(trades)

		if abs(delta) > 500 and absorption_levels:
			direction = "BUY" if delta > 0 else "SELL"

			return {
				"model": "ICEBERG",
				"direction": direction,
				"confidence": min(90, abs(delta) / 10),
				"rr": 3,
				"performance_weight": 1.0,
				"absorption_levels": absorption_levels,
				"buy_volume": buy_volume,
				"sell_volume": sell_volume,
				"delta": delta,
			}

		return None
