from astroquant.engine.gann.gann_master_engine import GannMasterEngine


class GannModel:

	def __init__(self):
		self.master = GannMasterEngine()

	def check(self, data, symbol):
		candles = list((data or {}).get("candles") or [])
		if len(candles) < 8:
			return None

		result = self.master.analyze(candles)
		score = int(result.get("score") or 0)
		if score < 3:
			return None

		direction = str(result.get("direction") or (data or {}).get("trend") or "BUY").upper()
		if direction not in {"BUY", "SELL"}:
			direction = "BUY"

		confidence = max(55.0, min(90.0, float(result.get("confidence") or 65.0)))
		rr = 2.6 if score >= 7 else 2.2

		return {
			"model": "GANN",
			"direction": direction,
			"confidence": round(confidence, 2),
			"rr": rr,
			"performance_weight": 1.0,
			"gann_score": score,
			"gann_signals": result.get("signals", {}),
		}
