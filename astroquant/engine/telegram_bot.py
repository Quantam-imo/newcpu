import requests
import os


def _credentials() -> tuple[str, str]:
    token = str(os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    chat_id = str(os.getenv("TELEGRAM_CHAT_ID", "")).strip()
    return token, chat_id


def send_telegram(message):
    token, chat_id = _credentials()
    if not token or not chat_id:
        return {"ok": False, "reason": "telegram credentials missing"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=8)
        response.raise_for_status()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
