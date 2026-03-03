import sqlite3
from statistics import mean

DB_PATH = "ai_trade_journal.db"


class ModelLearningEngine:

    def analyze(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            """
            SELECT model, result, r_multiple
            FROM trades
            """
        )
        rows = c.fetchall()
        conn.close()

        model_stats = {}

        for model, result, r_multiple in rows:
            if model not in model_stats:
                model_stats[model] = {"wins": 0, "losses": 0, "r": []}

            if str(result).upper() == "WIN":
                model_stats[model]["wins"] += 1
            else:
                model_stats[model]["losses"] += 1

            try:
                model_stats[model]["r"].append(float(r_multiple))
            except Exception:
                model_stats[model]["r"].append(0.0)

        performance = {}

        for model, stats in model_stats.items():
            total = stats["wins"] + stats["losses"]
            if total == 0:
                continue

            win_rate = stats["wins"] / total
            avg_r = mean(stats["r"]) if stats["r"] else 0.0
            confidence_score = (win_rate * 0.6) + (avg_r * 0.4)

            performance[model] = {
                "win_rate": win_rate,
                "avg_r": avg_r,
                "confidence_score": confidence_score,
                "trades": total,
            }

        return performance
