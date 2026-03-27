import requests
import os

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        return {"ok": False, "reason": "telegram credentials missing"}
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        response = requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=8)
        response.raise_for_status()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
