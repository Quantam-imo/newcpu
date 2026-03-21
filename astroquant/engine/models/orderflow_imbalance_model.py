from astroquant.engine.orderflow_imbalance_engine import OrderflowImbalanceEngine
from astroquant.engine.tape_speed_engine import TapeSpeedEngine


class OrderflowImbalanceModel:

	def __init__(self, orderflow_engine):
		self.orderflow = orderflow_engine
		self.imbalance_engine = OrderflowImbalanceEngine()
		self.tape_speed_engine = TapeSpeedEngine()

	def check(self, market_data, symbol):
		if not self.orderflow:
			return None

		dataset = (market_data or {}).get("dataset", "GLBX.MDP3")
		trades = self.orderflow.get_recent_trades(dataset=dataset, symbol=symbol)
		if not trades:
			return None

		imb = self.imbalance_engine.compute(trades)
		speed = self.tape_speed_engine.compute(trades, lookback_seconds=5.0)

		side = str(imb.get("imbalance_side") or "NEUTRAL").upper()
		ratio = abs(float(imb.get("imbalance_ratio") or 0.0))
		speed_state = str(speed.get("speed_state") or "QUIET").upper()

		if side not in {"BUY", "SELL"}:
			return None
		if ratio < 0.22:
			return None
		if speed_state == "QUIET":
			return None

		speed_bonus = 8.0 if speed_state == "FAST" else 4.0
		confidence = min(88.0, 58.0 + (ratio * 70.0) + speed_bonus)

		return {
			"model": "ORDERFLOW_IMBALANCE",
			"direction": side,
			"confidence": round(confidence, 2),
			"rr": 2.4,
			"performance_weight": 1.0,
			"imbalance_ratio": round(ratio, 4),
			"delta": float(imb.get("delta") or 0.0),
			"tape_speed": speed_state,
		}
