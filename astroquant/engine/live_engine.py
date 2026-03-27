import time
from astroquant.engine.databento_live import get_live_data
from core.orchestrator import run_cycle
from astroquant.engine.trade_execution import execute_trade
from astroquant.engine.telegram_bot import send_telegram

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
