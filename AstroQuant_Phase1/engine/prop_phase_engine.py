class PropPhaseEngine:

    def __init__(self):
        self.phase = "PHASE_1"
        self.start_balance = 50000
        self.current_balance = 50000

        self.phase1_target = 0.08     # 8%
        self.phase2_target = 0.05     # 5%

    def update_balance(self, new_balance):
        self.current_balance = new_balance

    def progress(self):

        profit_percent = (self.current_balance - self.start_balance) / self.start_balance

        if self.phase == "PHASE_1" and profit_percent >= self.phase1_target:
            return "PHASE_1_PASSED"

        if self.phase == "PHASE_2" and profit_percent >= self.phase2_target:
            return "PHASE_2_PASSED"

        return "IN_PROGRESS"

    def set_phase(self, phase_name):
        self.phase = phase_name
