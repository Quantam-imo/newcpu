class ModelPerformance:

    def __init__(self):
        self.history = {
            "ICT_LIQUIDITY": {"wins": 0, "losses": 0},
            "ICEBERG": {"wins": 0, "losses": 0},
            "GANN": {"wins": 0, "losses": 0},
            "NEWS_BREAKOUT": {"wins": 0, "losses": 0},
            "EXPANSION": {"wins": 0, "losses": 0},
        }

    def update(self, model, result):
        if model not in self.history:
            self.history[model] = {"wins": 0, "losses": 0}

        if str(result).lower() == "win":
            self.history[model]["wins"] += 1
        else:
            self.history[model]["losses"] += 1

    def get_weight_adjustment(self, model):
        data = self.history.get(model, {"wins": 0, "losses": 0})
        total = data["wins"] + data["losses"]
        if total == 0:
            return 1.0

        winrate = data["wins"] / total
        return 1 + (winrate - 0.5)
