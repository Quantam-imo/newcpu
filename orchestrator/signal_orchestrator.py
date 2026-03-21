from astroquant.engine.strategy.strategy_brain import StrategyBrain
import asyncio
import time

from astroquant.engine.engine_manager import EngineManager
from astroquant.engine.consensus_engine import ConsensusEngine
from astroquant.engine.regime_engine import RegimeEngine as MarketRegimeEngine
from astroquant.engine.prop_safe_trade_filter import PropSafeTradeFilter
# You may need to implement or adjust these imports:
# from astroquant.engine.risk_manager import RiskManager
# from astroquant.execution.execution_manager import ExecutionManager

class DummyRiskManager:
    def calculate_position_size(self, balance, risk_percent, entry, stop_loss):
        # Dummy implementation
        return 1.0

class DummyExecutionManager:
    def execute_trade(self, signal, lot_size):
        # Dummy implementation
        return {"signal": signal, "lot_size": lot_size, "status": "executed"}



# Use Candle Engine for structured candle data
from astroquant.engine.candle.candle_reader import get_latest_candle

class SignalOrchestrator:
    def __init__(self):
        self.engine_manager = EngineManager()
        self.engine_manager.load_engines()
        self.engine_names = self.engine_manager.get_engine_names() if hasattr(self.engine_manager, 'get_engine_names') else ["ICT", "Gann", "Astro"]
        self.strategy_brain = StrategyBrain(self.engine_names)
        self.regime = MarketRegimeEngine()
        self.trade_filter = PropSafeTradeFilter()
        self.risk_manager = DummyRiskManager()
        self.execution = DummyExecutionManager()

    def get_market_data(self):
        symbol = "GC.FUT"
        candle = get_latest_candle(symbol, timeframe=1)
        if not candle:
            print("No candle data")
            return None
        market_data = {
            "symbol": candle["symbol"],
            "price": candle["close"],
            "high": candle["high"],
            "low": candle["low"],
            "volume": candle["volume"],
            "timestamp": candle["timestamp"]
        }
        print("[ORCHESTRATOR DATA]:", market_data)
        return market_data

    async def analyze_market(self):
        market_data = self.get_market_data()
        if not market_data:
            print("No market data")
            return
        # Run all engines and collect signals as a dict
        engine_results = await self.engine_manager.run_engines(market_data)
        # engine_results should be a dict {engine_name: signal or None}
        if isinstance(engine_results, list):
            # fallback for legacy: map to engine names
            engine_results = {name: res for name, res in zip(self.engine_names, engine_results)}
        signals = {k: v for k, v in engine_results.items() if v}
        if not signals:
            print("No signals")
            return
        # Use strategy brain to select best signal
        best_signal, best_engine, weights = self.strategy_brain.decide(signals)
        print(f"[STRATEGY BRAIN] Weights: {weights}")
        if not best_signal:
            print("No valid strategy decision")
            return
        regime = self.regime  # .detect(market_data.get("volatility", 0), market_data.get("trend_strength", 0))
        print("Market regime:", regime)
        approved, reason = self.trade_filter.is_trade_allowed(
            best_signal.get("entry", market_data["price"]),
            time.time(),
            market_data.get("spread", 0),
            best_signal.get("rr", 2.0)
        )
        if not approved:
            print("Trade blocked:", reason)
            self.strategy_brain.update_performance(best_engine, 0)
            return
        lot_size = self.risk_manager.calculate_position_size(
            balance=100000,
            risk_percent=0.5,
            entry=best_signal.get("entry", market_data["price"]),
            stop_loss=best_signal.get("stop_loss", market_data["price"] - 5)
        )
        order = self.execution.execute_trade(best_signal, lot_size)
        print(f"Trade executed by {best_engine}: {order}")
        # Example: update performance (dummy, should be based on real PnL)
        self.strategy_brain.update_performance(best_engine, 1)
        # self.trade_filter.register_trade()  # Add if you implement trade registration

    async def run(self):
        while True:
            print("========== PIPELINE START ==========")
            try:
                await self.analyze_market()
            except Exception as e:
                print("Error:", e)
            print("========== PIPELINE END ==========")
            await asyncio.sleep(60)
