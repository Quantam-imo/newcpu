import os
from datetime import datetime, timezone, timedelta

import requests

_IST = timezone(timedelta(hours=5, minutes=30))


def _news_market_impact(title: str, currency: str) -> str:
    """Return a directional market impact hint for XAUUSD/Gold based on the news event."""
    t = (title or "").upper()
    c = (currency or "").upper()
    if c == "USD":
        if any(k in t for k in ("CPI", "PPI", "PCE", "INFLATION")):
            return "Gold: HOT data = bearish (USD up) | COOL data = bullish (USD down)"
        if any(k in t for k in ("NFP", "NON-FARM", "UNEMPLOYMENT", "JOBS", "ADP")):
            return "Gold: STRONG jobs = bearish | WEAK jobs = bullish"
        if any(k in t for k in ("FOMC", "RATE DECISION", "INTEREST RATE", "POWELL", "FED ")):
            return "Gold: HAWKISH = bearish (USD up) | DOVISH = bullish (rate cut)"
        if any(k in t for k in ("GDP", "RETAIL SALES", "ISM", "DURABLE", "CONFIDENCE")):
            return "Gold: STRONG data = bearish (risk-on) | WEAK data = bullish (safe-haven)"
        return "Gold: USD event — watch DXY, expect 15-30pt spike"
    if c == "EUR":
        if any(k in t for k in ("ECB", "RATE", "LAGARDE")):
            return "Gold: ECB HAWKISH = EUR up → DXY down → Gold bullish"
        return "Gold: EUR event — indirect USD index (DXY) impact"
    return f"Gold: {c} news — monitor USD correlation for directional bias"


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
        mins = event.get("minutes_to_event")
        # Build IST timing string
        if mins is not None:
            timing = f"T-{int(abs(mins))}min"
        else:
            raw_time = event.get("time")
            if isinstance(raw_time, datetime):
                timing = raw_time.astimezone(_IST).strftime("%d %b %I:%M %p IST")
            else:
                timing = str(raw_time or "N/A")
        impact = str(event.get("impact", "HIGH")).upper()
        currency = str(event.get("currency", "?"))
        title = str(event.get("title", "?"))
        impact_hint = _news_market_impact(title, currency)
        message = (
            f"NEWS HALT: {currency} {title}\n"
            f"Impact : {impact}\n"
            f"Time   : {timing}\n"
            f"Market : {impact_hint}\n"
            f"Action : All {currency}-correlated signals suspended"
        )
        self.send(message)
