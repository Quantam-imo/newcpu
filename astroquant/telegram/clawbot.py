class ClawbotEngine:

	def __init__(
		self,
		consecutive_loss_defensive=2,
		consecutive_loss_halt=3,
		spread_defensive=2.2,
		spread_halt=2.8,
		slippage_halt=1.2,
	):
		self.consecutive_loss_defensive = int(consecutive_loss_defensive)
		self.consecutive_loss_halt = int(consecutive_loss_halt)
		self.spread_defensive = float(spread_defensive)
		self.spread_halt = float(spread_halt)
		self.slippage_halt = float(slippage_halt)
		self.last_state = {
			"mode": "CLEAR",
			"risk_multiplier": 1.0,
			"reason": "OK",
			"loss_streak": 0,
			"spread": 0.0,
			"slippage": 0.0,
		}

	def evaluate(self, loss_streak=0, spread=0.0, slippage=0.0):
		streak = int(loss_streak or 0)
		spread_val = float(spread or 0.0)
		slip_val = float(slippage or 0.0)

		mode = "CLEAR"
		risk_multiplier = 1.0
		reason = "OK"

		if spread_val >= self.spread_halt or slip_val >= self.slippage_halt or streak >= self.consecutive_loss_halt:
			mode = "HALT"
			risk_multiplier = 0.0
			if streak >= self.consecutive_loss_halt:
				reason = "Consecutive loss halt"
			elif spread_val >= self.spread_halt:
				reason = "Spread anomaly halt"
			else:
				reason = "Slippage anomaly halt"
		elif streak >= self.consecutive_loss_defensive or spread_val >= self.spread_defensive:
			mode = "DEFENSIVE"
			risk_multiplier = 0.6
			reason = "Defensive risk mode"

		self.last_state = {
			"mode": mode,
			"risk_multiplier": risk_multiplier,
			"reason": reason,
			"loss_streak": streak,
			"spread": round(spread_val, 4),
			"slippage": round(slip_val, 4),
		}
		return dict(self.last_state)

	def configure(self, config=None):
		payload = dict(config or {})
		if "consecutive_loss_defensive" in payload:
			self.consecutive_loss_defensive = int(payload.get("consecutive_loss_defensive") or self.consecutive_loss_defensive)
		if "consecutive_loss_halt" in payload:
			self.consecutive_loss_halt = int(payload.get("consecutive_loss_halt") or self.consecutive_loss_halt)
		if "spread_defensive" in payload:
			self.spread_defensive = float(payload.get("spread_defensive") or self.spread_defensive)
		if "spread_halt" in payload:
			self.spread_halt = float(payload.get("spread_halt") or self.spread_halt)
		if "slippage_halt" in payload:
			self.slippage_halt = float(payload.get("slippage_halt") or self.slippage_halt)
		return {
			"consecutive_loss_defensive": self.consecutive_loss_defensive,
			"consecutive_loss_halt": self.consecutive_loss_halt,
			"spread_defensive": self.spread_defensive,
			"spread_halt": self.spread_halt,
			"slippage_halt": self.slippage_halt,
		}

	def status(self):
		return dict(self.last_state)
