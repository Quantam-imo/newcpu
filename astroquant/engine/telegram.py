import os
import requests


class TelegramEngine:

    def __init__(self):
        self.token = ""
        self.chat_id = ""
        self.last_error = None

    def _refresh_credentials(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    def status(self):
        self._refresh_credentials()
        configured = bool(self.token and self.chat_id)
        if not configured:
            return {
                "configured": False,
                "active": False,
                "reason": "telegram credentials missing",
            }
        if self.last_error:
            return {
                "configured": True,
                "active": False,
                "reason": str(self.last_error),
            }
        return {
            "configured": True,
            "active": True,
            "reason": "OK",
        }

    def send(self, message):
        self._refresh_credentials()
        if not self.token or not self.chat_id:
            self.last_error = "telegram credentials missing"
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": message}

        try:
            response = requests.post(url, json=payload, timeout=5)
            response.raise_for_status()
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def send_news_alert(self, event):
        message = f"""
⚠ HIGH IMPACT NEWS ALERT

Event: {event['title']}
Currency: {event['currency']}
Time: {event['time']}

System entering risk control mode.
"""
        self.send(message)
