import json
from pathlib import Path


class PerformanceMemory:

    def __init__(self):
        self.file = Path("data/performance_memory.json")
        self._load()

    def _load(self):
        try:
            self.data = json.loads(self.file.read_text())
        except Exception:
            self.data = {}
            self._save()

    def _save(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.data, indent=4))

    def _key(self, model, symbol, session, volatility, news_mode):
        return f"{model}|{symbol}|{session}|{volatility}|{news_mode}"

    def record_trade(self, model, symbol, session, volatility, news_mode, result):
        key = self._key(model, symbol, session, volatility, news_mode)

        if key not in self.data:
            self.data[key] = {
                "wins": 0,
                "losses": 0,
            }

        if result == "win":
            self.data[key]["wins"] += 1
        else:
            self.data[key]["losses"] += 1

        self._save()

    def score(self, model, symbol, session, volatility, news_mode):
        key = self._key(model, symbol, session, volatility, news_mode)

        if key not in self.data:
            return 0.5

        wins = self.data[key]["wins"]
        losses = self.data[key]["losses"]
        total = wins + losses

        if total < 10:
            return 0.5

        return wins / total
