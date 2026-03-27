import time
from astroquant.engine.databento_live import get_live_data
from astroquant.engine.trade_execution import execute_trade
from astroquant.engine.telegram_bot import send_telegram
from astroquant.engine.multi_symbol_runner import MultiSymbolRunner


def run_cycle(df_1m, df_5m, df_15m, price):
    """Minimal orchestration shim — delegates to MultiSymbolRunner signal logic."""
    runner = MultiSymbolRunner(["XAUUSD"])
    try:
        signal = runner.compute_signal("XAUUSD")
    except Exception:
        signal = {"action": "NO_TRADE", "reason": "runner unavailable"}
    return signal

def start_live_trading():
    while True:
        try:
            df = get_live_data()
            price = df["close"].iloc[-1]

            decision = run_cycle(df, df, df, price)

            if decision["action"] != "NO_TRADE":
                trade = execute_trade(decision, price)

                send_telegram(f"""
                🚀 TRADE ALERT
                Action: {decision['action']}
                Entry: {trade['entry']}
                SL: {trade['sl']}
                TP: {trade['tp']}
                """)

                print("Trade Executed:", trade)

        except Exception as e:
            print("Error:", e)

        time.sleep(60)
