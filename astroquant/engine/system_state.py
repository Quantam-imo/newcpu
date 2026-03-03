class SystemState:

    def __init__(self):
        self.balance = 50000
        self.daily_loss = 0
        self.total_drawdown = 0
        self.phase = "PHASE1"
        self.news_halt = False
        self.reduce_risk = False
        self.open_positions = {}
        self.model_performance = {}
        self.consecutive_losses = 0

    def reset_daily(self):
        self.daily_loss = 0

    def adjust_risk(self):
        if self.reduce_risk:
            return 0.5
        if self.consecutive_losses >= 3:
            return 0.5
        return 1.0
