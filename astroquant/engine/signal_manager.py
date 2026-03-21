from astroquant.engine.models.ict_model import ICTModel
from astroquant.engine.models.iceberg_model import IcebergModel
from astroquant.engine.models.expansion_model import ExpansionModel
from astroquant.engine.models.gann_model import GannModel
from astroquant.engine.models.news_model import NewsModel
from astroquant.engine.models.orderflow_imbalance_model import OrderflowImbalanceModel
from astroquant.engine.models.liquidity_trap_model import LiquidityTrapModel
from astroquant.engine.orderflow_engine import OrderflowEngine
from astroquant.backend.config import SYMBOLS


class SignalManager:

    def __init__(self, api_key):
        self.orderflow_engine = OrderflowEngine(api_key) if api_key else None

        self.models = [
            ICTModel(),
            IcebergModel(self.orderflow_engine),
            OrderflowImbalanceModel(self.orderflow_engine),
            LiquidityTrapModel(self.orderflow_engine),
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
