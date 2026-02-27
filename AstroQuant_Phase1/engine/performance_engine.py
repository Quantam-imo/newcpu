class PerformanceEngine:

    def evaluate(self, trades):

        if not trades:
            return {"win_rate": 0}

        wins = sum(1 for t in trades if t["result"] > 0)
        win_rate = wins / len(trades)

        return {
            "win_rate": round(win_rate * 100, 2),
            "total_trades": len(trades)
        }
