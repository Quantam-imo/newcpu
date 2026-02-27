from engine.models.expansion_model import ExpansionModel
from engine.models.gann_model import GannModel
from engine.models.iceberg_model import IcebergModel
from engine.models.ict_model import ICTModel
from engine.models.news_model import NewsModel


class SignalManager:

    def __init__(self):
        self.models = [
            ICTModel(),
            IcebergModel(),
            GannModel(),
            NewsModel(),
            ExpansionModel(),
        ]

    def evaluate(self, data):
        signals = []
        for model in self.models:
            signal = model.generate(data)
            if signal:
                signals.append(signal)

        return signals

    def evaluate_exit(self, signals, current_side):
        active_side = str(current_side or "").upper()
        if active_side not in ["BUY", "SELL"]:
            return None

        for signal in signals or []:
            side = str(signal.get("side", "")).upper()
            if side in ["BUY", "SELL"] and side != active_side:
                return {
                    "model": signal.get("model"),
                    "reason": "Opposite model signal",
                }

        return None
