import requests
import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

class TelegramEngine:

    def send(self, message):

        if not BOT_TOKEN or not CHAT_ID:
            print("Telegram not configured.")
            return

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        payload = {
            "chat_id": CHAT_ID,
            "text": message
        }

        try:
            requests.post(url, json=payload)
        except:
            print("Telegram send failed.")

    def daily_summary(self, balance, profit, drawdown):
        message = (
            f"\U0001F4CA Daily Report\n"
            f"Balance: {balance}\n"
            f"Profit: {profit}\n"
            f"Drawdown: {drawdown}"
        )
        self.send(message)
