import random
import math

class StressEngine:

    def __init__(self,
                 start_balance=50000,
                 risk_per_trade=0.003,
                 winrate=0.52,
                 rr=2.0,
                 trades_per_day=3,
                 days=30):

        self.start_balance = start_balance
        self.balance = start_balance
        self.risk_per_trade = risk_per_trade
        self.winrate = winrate
        self.rr = rr
        self.trades_per_day = trades_per_day
        self.days = days

        self.max_drawdown = 0
        self.peak = start_balance
        self.loss_streak = 0
        self.max_loss_streak = 0

    def simulate_trade(self):

        risk_amount = self.balance * self.risk_per_trade

        # Spread spike simulation
        if random.random() < 0.05:
            risk_amount *= 1.2  # worse slippage

        # News spike
        if random.random() < 0.05:
            return -risk_amount * 1.5

        if random.random() < self.winrate:
            self.loss_streak = 0
            return risk_amount * self.rr
        else:
            self.loss_streak += 1
            self.max_loss_streak = max(self.max_loss_streak, self.loss_streak)
            return -risk_amount

    def run(self):

        daily_loss_limit = self.start_balance * 0.03
        max_loss_limit = self.start_balance * 0.08

        violated = False

        for day in range(self.days):

            daily_loss = 0

            for _ in range(self.trades_per_day):

                pnl = self.simulate_trade()

                daily_loss += min(pnl, 0)
                self.balance += pnl

                if daily_loss < -daily_loss_limit:
                    violated = True
                    break

                if self.balance < self.start_balance - max_loss_limit:
                    violated = True
                    break

            self.peak = max(self.peak, self.balance)
            dd = (self.peak - self.balance)
            self.max_drawdown = max(self.max_drawdown, dd)

        return {
            "final_balance": round(self.balance, 2),
            "profit": round(self.balance - self.start_balance, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_loss_streak": self.max_loss_streak,
            "violated": violated
        }
