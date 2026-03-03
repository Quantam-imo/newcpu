import json
from pathlib import Path


class ModelWeightEngine:

    def __init__(self):
        self.file = Path("data/model_stats.json")
        self.window_size = 30
        self._load()

    def _load(self):
        try:
            self.stats = json.loads(self.file.read_text())
        except Exception:
            self.stats = {}
            self._save()

    def _save(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.stats, indent=4))

    def record_trade(self, model_name, result):
        if model_name not in self.stats:
            self.stats[model_name] = {"history": []}

        self.stats[model_name]["history"].append(result)

        if len(self.stats[model_name]["history"]) > self.window_size:
            self.stats[model_name]["history"].pop(0)

        self._save()

    def win_rate(self, model_name):
        if model_name not in self.stats:
            return 0.5

        history = self.stats[model_name].get("history", [])
        if len(history) < 10:
            return 0.5

        wins = history.count("win")
        total = len(history)
        return wins / total if total else 0.5

    def model_weight(self, model_name):
        wr = self.win_rate(model_name)

        if wr >= 0.65:
            return 1.3
        if wr >= 0.55:
            return 1.1
        if wr >= 0.45:
            return 1.0
        if wr >= 0.35:
            return 0.8
        return 0.5
