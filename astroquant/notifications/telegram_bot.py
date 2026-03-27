import os
import requests


def _credentials():
    token = str(os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    chat_id = str(os.getenv("TELEGRAM_CHAT_ID", "")).strip()
    return token, chat_id


def send_message(text):
    token, chat_id = _credentials()
    if not token or not chat_id:
        return {"ok": False, "reason": "telegram credentials missing"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": str(text),
    }
    try:
        response = requests.post(url, json=payload, timeout=8)
        response.raise_for_status()
        return {"ok": True}
    except Exception as e:
        print("Telegram error:", e)
        return {"ok": False, "reason": str(e)}
