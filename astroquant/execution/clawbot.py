from astroquant.execution.playwright_engine import PlaywrightExecution as PlaywrightEngine
from astroquant.risk.equity_guard import allow_trade
from astroquant.notifications.telegram_bot import send_message

class ClawBot:
    def __init__(self):
        self.engine = PlaywrightEngine()
        self.engine.start()

    def process_signal(self, signal_data):
        signal = signal_data["signal"]
        confidence = signal_data.get("confidence", 0)
        # Accept either spot execution levels or futures-native levels.
        entry = signal_data.get("broker_entry", signal_data.get("entry"))
        stop_loss = signal_data.get("broker_sl", signal_data.get("sl"))
        take_profit = signal_data.get("broker_tp", signal_data.get("tp"))
        # ---------------------------------
        # SAFETY CHECKS
        # ---------------------------------
        if not allow_trade():
            print("Trade blocked by risk system")
            return
        if confidence < 0.7:
            print("Low confidence")
            return
        # ---------------------------------
        # POSITION CHECK
        # ---------------------------------
        position = self.engine.get_position()
        if signal == "BUY" and position != "BUY":
            self.engine.execute_trade("BUY")
        elif signal == "SELL" and position != "SELL":
            self.engine.execute_trade("SELL")
        else:
            return
        # ---------------------------------
        # SET SL / TP
        # ---------------------------------
        if entry is not None and stop_loss is not None and take_profit is not None:
            self.engine.set_sl_tp(
                sl=float(stop_loss),
                tp=float(take_profit)
            )
        # ---------------------------------
        # TELEGRAM ALERT
        # ---------------------------------
        send_message(f"{signal} executed 🚀\nConfidence: {confidence}")
