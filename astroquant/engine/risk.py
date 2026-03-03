class RiskEngine:

	def __init__(self, state):
		self.state = state
		self.daily_loss_limit = 1500.0
		self.max_drawdown_floor = 46000.0
		self.max_lot_size = 10.0
		self.max_risk_per_trade = 0.01

	def calculate_position_size(self, risk_percent, stop_distance):
		risk_percent = max(0.0, min(float(risk_percent or 0.0), float(self.max_risk_per_trade)))
		adjustment = self.state.adjust_risk()
		risk_amount = self.state.balance * risk_percent * adjustment

		if stop_distance <= 0:
			return 0

		lot_size = risk_amount / stop_distance
		lot_size = min(float(lot_size), float(self.max_lot_size))
		return round(lot_size, 2)

	def get_phase_risk(self, phase):
		if phase == "PHASE1":
			return 0.005
		elif phase == "PHASE2":
			return 0.005
		elif phase == "FUNDED":
			return 0.0075
		return 0.005

	def check_limits(self):
		if self.state.daily_loss >= float(self.daily_loss_limit):
			return False, "Daily limit hit"

		if self.state.balance <= float(self.max_drawdown_floor):
			return False, "Max drawdown reached"

		return True, "OK"
