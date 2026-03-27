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


# --- Playwright/Execution Imports ---
from astroquant.execution.playwright_engine import PlaywrightExecution
from astroquant.execution.safe_trade import safe_trade
from astroquant.execution.position_detector import PositionDetector
from astroquant.execution.sl_tp_manager import SLTPManager
from astroquant.core.sl_tp_calculator import calculate_sl_tp

class StateManager:
    def __init__(self):
        self.position = None

def dummy_logger(msg):
    print(f"[EXECUTION LOG] {msg}")



# Use Candle Engine for structured candle data
from astroquant.engine.candle.candle_reader import get_latest_candle

class SignalOrchestrator:
    def __init__(self, page=None):
        self.engine_manager = EngineManager()
        self.engine_manager.load_engines()
        self.engine_names = self.engine_manager.get_engine_names() if hasattr(self.engine_manager, 'get_engine_names') else ["ICT", "Gann", "Astro"]
        self.strategy_brain = StrategyBrain(self.engine_names)
        self.regime = MarketRegimeEngine()
        self.trade_filter = PropSafeTradeFilter()
        self.risk_manager = DummyRiskManager()
        # --- Execution system ---
        self.page = page  # Playwright page object (should be set externally)
        self.state_manager = StateManager()
        self.position_detector = PositionDetector(self.page, dummy_logger) if self.page else None
        self.exec_engine = PlaywrightExecution(self.page, self.state_manager, dummy_logger) if self.page else None
        self.sl_tp_manager = SLTPManager(self.page, dummy_logger) if self.page else None

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
        if isinstance(engine_results, list):
            engine_results = {name: res for name, res in zip(self.engine_names, engine_results)}
        signals = {k: v for k, v in engine_results.items() if v}
        if not signals:
            print("No signals")
            return
        best_signal, best_engine, weights = self.strategy_brain.decide(signals)
        print(f"[STRATEGY BRAIN] Weights: {weights}")
        if not best_signal:
            print("No valid strategy decision")
            return
        regime = self.regime
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

        # --- Position Detection & State Sync ---
        if self.position_detector:
            current_position = self.position_detector.detect_position()
            self.state_manager.position = current_position
            if current_position is not None:
                print("ALREADY IN TRADE (UI detected)")
                return "ALREADY IN TRADE"

        # --- Trade Execution ---
        direction = best_signal.get("direction", "BUY")
        entry_price = best_signal.get("entry", market_data["price"])
        result = None
        if self.exec_engine:
            result = safe_trade(self.exec_engine, direction, lot_size)
        else:
            print("[WARN] No execution engine attached!")
            return

        # --- SL/TP Calculation & Automation ---
        if result == "SUCCESS" and self.sl_tp_manager:
            sl_price, tp_price = calculate_sl_tp(entry_price, direction)
            sl_tp_applied = self.sl_tp_manager.set_sl_tp(sl_price, tp_price)
            if sl_tp_applied != "SUCCESS":
                print("[CRITICAL] SL/TP not applied, closing trade!")
                # Optionally: self.exec_engine.close_trade()  # Implement as needed

        print(f"Trade executed by {best_engine}: {result}")
        self.strategy_brain.update_performance(best_engine, 1)

    async def run(self):
        while True:
            print("========== PIPELINE START ==========")
            try:
                await self.analyze_market()
            except Exception as e:
                print("Error:", e)
            print("========== PIPELINE END ==========")
            await asyncio.sleep(60)
