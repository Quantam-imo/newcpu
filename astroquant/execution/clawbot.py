"""ClawBot execution helper.

This module was the original playwright-based execution entrypoint.
The live engine now uses ClawbotEngine (astroquant.telegram.clawbot) as a
risk/mode evaluator and astroquant.engine.execution.ExecutionEngine for
broker execution.  This module is kept for backward-compatibility but
delegates properly instead of running a duplicate Playwright session.
"""

from astroquant.risk.equity_guard import allow_trade
from astroquant.notifications.telegram_bot import send_message
import time

_last_send_ts: float = 0.0
_SEND_COOLDOWN = 30.0  # seconds between Telegram sends


class ClawBot:
    """Thin wrapper used by standalone scripts.  For production use
    MultiSymbolRunner which uses ClawbotEngine + ExecutionEngine."""

    def __init__(self):
        try:
            from astroquant.execution.playwright_engine import PlaywrightExecution
            self.engine = PlaywrightExecution()
            self.engine.start()
        except Exception as exc:
            self.engine = None
            print(f"[ClawBot] Playwright engine unavailable: {exc}")

    def process_signal(self, signal_data):
        global _last_send_ts
        signal = signal_data["signal"]
        confidence = signal_data.get("confidence", 0)
        entry = signal_data.get("broker_entry", signal_data.get("entry"))
        stop_loss = signal_data.get("broker_sl", signal_data.get("sl"))
        take_profit = signal_data.get("broker_tp", signal_data.get("tp"))

        if not allow_trade():
            print("Trade blocked by risk system")
            return
        if confidence < 0.7:
            print("Low confidence")
            return
        if self.engine is None:
            print("[ClawBot] No execution engine available")
            return

        position = self.engine.get_position()
        if signal == "BUY" and position != "BUY":
            self.engine.execute_trade("BUY")
        elif signal == "SELL" and position != "SELL":
            self.engine.execute_trade("SELL")
        else:
            return

        if entry is not None and stop_loss is not None and take_profit is not None:
            self.engine.set_sl_tp(
                sl=float(stop_loss),
                tp=float(take_profit),
            )

        if time.time() - _last_send_ts > _SEND_COOLDOWN:
            send_message(f"{signal} executed\nConfidence: {confidence:.0%}")
            _last_send_ts = time.time()

