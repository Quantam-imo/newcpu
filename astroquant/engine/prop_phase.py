class PropPhase:

    def __init__(self, state):
        self.state = state
        self.funded_floor = 52000

    def set_phase(self, phase):
        self.state.phase = phase

    def enforce_floor(self):
        if self.state.phase == "FUNDED":
            if self.state.balance < self.funded_floor:
                return False, "Capital floor violated"
        return True, "OK"

    def get_risk_percent(self):
        if self.state.phase == "PHASE1":
            return 0.005
        elif self.state.phase == "PHASE2":
            return 0.005
        elif self.state.phase == "FUNDED":
            return 0.0075
        return 0.005
