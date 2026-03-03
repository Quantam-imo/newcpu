import json
from pathlib import Path


class CapitalEngine:

    def __init__(self):
        self.file = Path("data/capital_stats.json")
        self._load()

    def _load(self):
        try:
            self.data = json.loads(self.file.read_text())
        except Exception:
            self.data = {
                "equity_peak": 50000,
                "max_drawdown": 0,
                "monthly_returns": []
            }
            self._save()

    def _save(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.data, indent=2))

    def update_equity(self, equity):
        if equity > self.data["equity_peak"]:
            self.data["equity_peak"] = equity

        drawdown = self.data["equity_peak"] - equity

        if drawdown > self.data["max_drawdown"]:
            self.data["max_drawdown"] = drawdown

        self._save()

    def get_drawdown(self, equity):
        return self.data["equity_peak"] - equity
