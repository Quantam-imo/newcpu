from engine.models.ict_model import ICTModel
from engine.models.iceberg_model import IcebergModel
from engine.models.expansion_model import ExpansionModel
from engine.models.gann_model import GannModel
from engine.models.news_model import NewsModel
from engine.orderflow_engine import OrderflowEngine
from backend.config import SYMBOLS


class SignalManager:

    def __init__(self, api_key):
        self.orderflow_engine = OrderflowEngine(api_key) if api_key else None

        self.models = [
            ICTModel(),
            IcebergModel(self.orderflow_engine),
            ExpansionModel(),
            GannModel(),
            NewsModel()
        ]

    def generate_signals(self, market_data, symbol):
        signals = []
        data_symbol = SYMBOLS.get(symbol, {}).get("databento", symbol)

        for model in self.models:
            signal = model.check(market_data, data_symbol)
            if signal:
                signals.append(signal)

        return signals
