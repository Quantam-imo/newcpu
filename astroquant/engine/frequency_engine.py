import datetime
import json
from pathlib import Path


class FrequencyEngine:

    def __init__(self):
        self.file = Path("data/frequency_stats.json")
        self._load()

    def _default_state(self):
        return {
            "today": str(datetime.date.today()),
            "daily_trades": 0,
            "symbol_trades": {},
            "session_trades": {},
            "consecutive_losses": 0,
        }

    def _load(self):
        try:
            self.data = json.loads(self.file.read_text())
        except Exception:
            self.data = self._default_state()
            self._save()

    def _save(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.data, indent=4))

    def reset_if_new_day(self):
        today = str(datetime.date.today())

        if self.data.get("today") != today:
            self.data = self._default_state()
            self._save()

    def record_trade(self, symbol, result, session="UNKNOWN"):
        self.reset_if_new_day()

        self.data["daily_trades"] += 1
        self.data["symbol_trades"][symbol] = self.data["symbol_trades"].get(symbol, 0) + 1
        self.data["session_trades"][session] = self.data["session_trades"].get(session, 0) + 1

        if result == "loss":
            self.data["consecutive_losses"] += 1
        else:
            self.data["consecutive_losses"] = 0

        self._save()

    def allowed_to_trade(self, symbol, session="UNKNOWN"):
        self.reset_if_new_day()

        if self.data.get("daily_trades", 0) >= 6:
            return False, "Daily trade limit reached"

        if self.data.get("symbol_trades", {}).get(symbol, 0) >= 3:
            return False, "Symbol trade limit reached"

        if self.data.get("session_trades", {}).get(session, 0) >= 4:
            return False, "Session trade limit reached"

        if self.data.get("consecutive_losses", 0) >= 3:
            return False, "Loss streak throttle active"

        return True, "Allowed"
