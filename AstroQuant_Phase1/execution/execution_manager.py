import os
import threading
import time
from collections import deque

from execution.playwright_engine import PlaywrightEngine
from engine.risk_engine import RiskEngine
from engine.prop_phase_engine import PropPhaseEngine

from engine.ai_governance_engine import AIGovernanceEngine
from execution.broker_adaptation_engine import BrokerAdaptationEngine
from execution.trade_guardian import TradeGuardian
from execution.config import SYMBOL_SPREAD_LIMITS
from execution.symbol_mapper import is_execution_supported, to_execution_symbol
from backend.communication.telegram_engine import TelegramEngine
from backend.communication.clawbot_engine import ClawbotEngine


_shared_execution_manager = None


def get_execution_manager():
    global _shared_execution_manager
    if _shared_execution_manager is None:
        _shared_execution_manager = ExecutionManager()
    return _shared_execution_manager

class ExecutionManager:

    def __init__(self):
        self.execution_engine = PlaywrightEngine()
        self.risk_engine = RiskEngine()
        self.phase_engine = PropPhaseEngine()
        self.governance = AIGovernanceEngine()
        self.broker_brain = BrokerAdaptationEngine()

        self.telegram = TelegramEngine()
        self.clawbot = ClawbotEngine()

        self.trade_active = False
        self.emergency_stop = False
        self.active_symbols = {}
        self.last_trade_time = 0
        self.broker_feed_poll_ms = max(300, int(float(os.getenv("BROKER_FEED_POLL_MS", "1000"))))
        self.broker_feed_recent = deque(maxlen=max(20, int(float(os.getenv("BROKER_FEED_RECENT_SIZE", "80")))))
        self._broker_feed_loop_running = False
        self._broker_feed_thread = None

    def _record_broker_feed_snapshot(self, source, feed_state):
        snapshot = {
            "source": str(source or "loop"),
            "captured_at": time.time(),
            "state": feed_state or {},
        }
        self.broker_feed_recent.append(snapshot)

    def _broker_feed_loop(self):
        while self._broker_feed_loop_running:
            try:
                preferred_symbol = next(iter(self.active_symbols.keys()), "XAUUSD")
                feed_state = self.execution_engine.update_broker_feed(symbol=preferred_symbol)
                self._record_broker_feed_snapshot("loop", feed_state)
            except Exception as error:
                print(f"Broker feed loop error: {error}")

            time.sleep(self.broker_feed_poll_ms / 1000.0)

    def _start_broker_feed_loop(self):
        if self._broker_feed_loop_running:
            return

        if not getattr(self.execution_engine, "page", None):
            return

        self._broker_feed_loop_running = True
        self._broker_feed_thread = threading.Thread(target=self._broker_feed_loop, daemon=True)
        self._broker_feed_thread.start()

    def _stop_broker_feed_loop(self):
        self._broker_feed_loop_running = False

    def start_browser(self):
        self.execution_engine.start()
        self.execution_engine.wait_for_login()
        self._start_broker_feed_loop()

    def enable_emergency_stop(self):
        self.emergency_stop = True

    def disable_emergency_stop(self):
        self.emergency_stop = False



    def execute_trade(self, fusion_result, symbol="XAUUSD", expected_price=None, loss_streak=0, spread=0, slippage=0, allow_concurrent=False):
        from execution.config import dynamic_lot

        self._start_broker_feed_loop()

        requested_symbol = symbol or "XAUUSD"
        execution_symbol = to_execution_symbol(requested_symbol)

        broker_feed = self.execution_engine.update_broker_feed(symbol=execution_symbol)
        self._record_broker_feed_snapshot("execute_trade", broker_feed)
        broker_health = (broker_feed or {}).get("health", {})
        if broker_health.get("kill_switch"):
            self.enable_emergency_stop()
            reason = ", ".join(broker_health.get("reasons", [])) or "Broker feed unhealthy"
            print(f"Broker feed kill-switch triggered: {reason}")
            self.telegram.send(f"🛑 Trade Blocked\nReason: Broker feed unhealthy ({reason})")
            return False

        broker_price_symbol = str(((broker_feed or {}).get("price", {}) or {}).get("symbol", "") or "").strip()
        if broker_price_symbol:
            broker_exec_symbol = to_execution_symbol(broker_price_symbol)
            if broker_exec_symbol != execution_symbol:
                reason = f"Broker symbol mismatch (feed={broker_price_symbol} mapped={broker_exec_symbol}, expected={execution_symbol})"
                print(reason)
                self.telegram.send(f"⚠ Trade Blocked\nReason: {reason}")
                return False

        if not is_execution_supported(execution_symbol):
            print(f"Execution symbol unsupported: {execution_symbol}")
            self.telegram.send(
                f"⚠ Trade Blocked\nReason: Unsupported execution symbol ({execution_symbol})"
            )
            return False

        max_spread = SYMBOL_SPREAD_LIMITS.get(execution_symbol, 30)
        broker_allowed, broker_reason, adapted = self.broker_brain.assess(
            execution_symbol,
            fusion_result,
            broker_feed,
            max_spread=max_spread,
        )
        if not broker_allowed:
            print(f"Broker brain blocked trade: {broker_reason}")
            self.telegram.send(f"⚠ Trade Blocked\nReason: Broker adaptation blocked ({broker_reason})")
            return False

        working_signal = dict(fusion_result or {})
        working_signal.update(adapted)

        direction = str(working_signal.get("direction") or working_signal.get("side") or "").upper().strip()
        if direction not in {"BUY", "SELL"}:
            print("Invalid or missing direction. Trade blocked.")
            self.telegram.send("⚠ Trade Blocked\nReason: Invalid or missing direction.")
            return False
        working_signal["direction"] = direction

        # --- Clawbot anomaly detection ---
        anomaly = self.clawbot.check_anomaly(loss_streak, spread, slippage)
        if anomaly:
            self.telegram.send(f"🛑 Clawbot Alert: {anomaly}")
            return False

        # --- Multi-symbol concurrent control ---
        if self.emergency_stop:
            print("Emergency stop active. Trade blocked.")
            self.telegram.send("🛑 Emergency stop active. Trade blocked.")
            return False

        if execution_symbol in self.active_symbols:
            print(f"{execution_symbol} already active.")
            self.telegram.send(f"⚠ Trade Blocked\nReason: {execution_symbol} already active.")
            return False

        if len(self.active_symbols) >= 2:
            print("Max concurrent trades reached.")
            self.telegram.send("⚠ Trade Blocked\nReason: Max concurrent trades reached.")
            return False

        if (not allow_concurrent) and time.time() - self.last_trade_time < 300:
            print("Trade throttle active.")
            self.telegram.send("⚠ Trade Blocked\nReason: Trade throttle active.")
            return False

        if not self.risk_engine.allowed():
            print("Risk engine blocked trade.")
            self.telegram.send("⚠ Trade Blocked\nReason: Risk engine blocked trade.")
            return False

        if self.risk_engine.daily_loss_exceeded():
            self.enable_emergency_stop()
            print("Daily loss exceeded. Emergency stop enabled.")
            self.telegram.send("🛑 Daily loss exceeded. Emergency stop enabled.")
            return False

        if working_signal.get("confidence", 0) < 70:
            print("Confidence below threshold. Blocked.")
            self.telegram.send("⚠ Trade Blocked\nReason: Confidence below threshold.")
            return False

        allowed, reason = self.governance.trade_allowed(working_signal)
        if not allowed:
            print("Governance blocked trade:", reason)
            self.telegram.send(f"⚠ Trade Blocked\nReason: {reason}")
            return False

        guardian = TradeGuardian(self.execution_engine.page)

        if not guardian.spread_allowed(max_spread=max_spread):
            print("Spread filter blocked trade.")
            self.telegram.send("⚠ Trade Blocked\nReason: Spread filter blocked trade.")
            return False

        if not guardian.news_lock():
            print("News lock active.")
            self.telegram.send("⚠ Trade Blocked\nReason: News lock active.")
            return False

        if hasattr(guardian, 'sentiment_lock') and not guardian.sentiment_lock(working_signal.get("sentiment", 0)):
            print("Sentiment lock blocked trade.")
            self.telegram.send("⚠ Trade Blocked\nReason: Sentiment lock active.")
            return False

        if not guardian.volatility_halt():
            print("Volatility halt triggered.")
            self.telegram.send("⚠ Trade Blocked\nReason: Volatility halt triggered.")
            return False


        # --- Dynamic AI lot sizing with phase-based risk ---
        balance = self.risk_engine.get_balance() if hasattr(self.risk_engine, 'get_balance') else 50000
        rules = self.risk_engine.prop_lock.get_rules()
        prop_risk_fraction = float(rules.get("risk_per_trade", 0.003))
        signal_risk_percent = float(working_signal.get("risk_percent", prop_risk_fraction * 100) or (prop_risk_fraction * 100))
        signal_risk_fraction = max(0.0, signal_risk_percent / 100.0)
        effective_risk_fraction = min(prop_risk_fraction, signal_risk_fraction if signal_risk_fraction > 0 else prop_risk_fraction)

        lot = dynamic_lot(balance, effective_risk_fraction, 150)

        print(f"All checks passed. Executing trade for {execution_symbol} with lot {lot}.")

        success = self.execution_engine.execute_market_order(working_signal["direction"])

        if success:
            self.active_symbols[execution_symbol] = str(working_signal.get("direction", "")).upper() or "ACTIVE"
            self.trade_active = True
            self.last_trade_time = time.time()
            self.governance.register_trade()
            print("Trade officially active.")

            # Telegram trade execution alert
            self.telegram.send(
                f"🚀 Trade Executed\n"
                f"Symbol: {execution_symbol}\n"
                f"Source: {requested_symbol}\n"
                f"Direction: {working_signal['direction']}\n"
                f"Lot: {lot}\n"
                f"Confidence: {working_signal.get('confidence', 0)}%\n"
                f"Spread: {working_signal.get('broker_spread', '--')}"
            )

            # Slippage check (optional expected_price)
            if expected_price is not None:
                slippage = guardian.calculate_slippage(expected_price)
                if slippage and slippage > 1.5:
                    print("Excessive slippage detected.")
                    # Optionally auto-close or alert
                self.broker_brain.register_fill(execution_symbol, expected_price, working_signal.get("execution_price"))

            # --- Audit log ---
            self.log_trade(execution_symbol, working_signal["direction"], lot, working_signal.get("confidence", 0))
        else:
            print("Execution rejected or failed.")

        return success

    def mark_trade_closed(self, symbol=None, model_name="fusion", result="WIN"):
        self.trade_active = False

        if symbol and symbol in self.active_symbols:
            del self.active_symbols[symbol]

        if not symbol:
            return

        try:
            from backend.ai.learning_engine import LearningEngine
            learning = LearningEngine()
            learning.record_trade(symbol, model_name, result)
        except Exception as e:
            print(f"Learning record error: {e}")

    def log_trade(self, symbol, direction, lot, confidence):
        with open("logs/execution_log.csv", "a") as f:
            f.write(f"{symbol},{direction},{lot},{confidence}\n")

    def sync_position_state(self):
        if not self.execution_engine.page:
            return

        try:
            feed_state = self.execution_engine.update_broker_feed(symbol="XAUUSD")
            self._record_broker_feed_snapshot("sync", feed_state)
        except Exception as error:
            print(f"Broker feed update error: {error}")

        from execution.position_monitor import PositionMonitor
        monitor = PositionMonitor(self.execution_engine.page)

        if not monitor.has_open_position():
            self.trade_active = False
            print("Position closed. State reset.")

    def get_broker_feed_status(self):
        return self.execution_engine.get_broker_feed_state()

    def get_broker_brain_status(self):
        return self.broker_brain.get_state()

    def get_broker_feed_recent(self, limit=20):
        safe_limit = max(1, min(int(limit or 20), len(self.broker_feed_recent) or 1))
        return list(self.broker_feed_recent)[-safe_limit:]

    def stop(self):
        self._stop_broker_feed_loop()
