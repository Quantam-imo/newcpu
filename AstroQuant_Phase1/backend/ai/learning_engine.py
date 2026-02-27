import json
import os
from datetime import datetime

MEMORY_PATH = "data/learning_memory.json"

class LearningEngine:

    def __init__(self):
        if not os.path.exists(MEMORY_PATH):
            with open(MEMORY_PATH, "w") as f:
                json.dump({
                    "models": {},
                    "symbols": {},
                    "sessions": {},
                    "total_trades": 0
                }, f)

    def _load(self):
        with open(MEMORY_PATH, "r") as f:
            return json.load(f)

    def _save(self, data):
        with open(MEMORY_PATH, "w") as f:
            json.dump(data, f, indent=4)

    def record_trade(self, symbol, model, result):
        data = self._load()

        # Model stats
        if model not in data["models"]:
            data["models"][model] = {"wins": 0, "losses": 0}

        if result == "WIN":
            data["models"][model]["wins"] += 1
        else:
            data["models"][model]["losses"] += 1

        # Symbol stats
        if symbol not in data["symbols"]:
            data["symbols"][symbol] = {"wins": 0, "losses": 0}

        if result == "WIN":
            data["symbols"][symbol]["wins"] += 1
        else:
            data["symbols"][symbol]["losses"] += 1

        # Session stats
        hour = datetime.now().hour
        session = "ASIA" if hour < 8 else "LONDON" if hour < 16 else "NY"

        if session not in data["sessions"]:
            data["sessions"][session] = {"wins": 0, "losses": 0}

        if result == "WIN":
            data["sessions"][session]["wins"] += 1
        else:
            data["sessions"][session]["losses"] += 1

        data["total_trades"] += 1

        self._save(data)

    def get_model_weight(self, model):
        data = self._load()

        if model not in data["models"]:
            return 1.0

        wins = data["models"][model]["wins"]
        losses = data["models"][model]["losses"]

        total = wins + losses
        if total < 10:
            return 1.0  # not enough data

        winrate = wins / total

        # Weight range: 0.8 to 1.2
        return 0.8 + (winrate * 0.4)
