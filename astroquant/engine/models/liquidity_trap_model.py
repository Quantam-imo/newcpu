from astroquant.engine.liquidity_trap_detector import LiquidityTrapDetector
from astroquant.engine.tape_speed_engine import TapeSpeedEngine


class LiquidityTrapModel:

	def __init__(self, orderflow_engine=None):
		self.detector = LiquidityTrapDetector()
		self.tape_speed_engine = TapeSpeedEngine()
		self.orderflow = orderflow_engine

	def check(self, market_data, symbol):
		data = dict(market_data or {})
		candles = list(data.get("candles") or [])
		if len(candles) < 8:
			return None

		trap = self.detector.detect(candles, lookback=20)
		if not bool(trap.get("trap")):
			return None

		direction = str(trap.get("side") or "NONE").upper()
		if direction not in {"BUY", "SELL"}:
			return None

		speed_state = "UNKNOWN"
		if self.orderflow:
			dataset = data.get("dataset", "GLBX.MDP3")
			trades = self.orderflow.get_recent_trades(dataset=dataset, symbol=symbol)
			if trades:
				speed = self.tape_speed_engine.compute(trades, lookback_seconds=8.0)
				speed_state = str(speed.get("speed_state") or "UNKNOWN").upper()
				# Avoid reversal entries during extreme tape acceleration.
				if speed_state == "FAST":
					return None

		base = 69.0
		if speed_state == "ACTIVE":
			base += 3.0

		return {
			"model": "LIQUIDITY_TRAP",
			"direction": direction,
			"confidence": round(min(86.0, base), 2),
			"rr": 2.2,
			"performance_weight": 1.0,
			"trap_reason": str(trap.get("reason") or "trap"),
			"tape_speed": speed_state,
		}
