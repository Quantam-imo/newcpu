import os
from dataclasses import dataclass

import requests


@dataclass
class TelegramBotStatus:
	configured: bool
	active: bool
	reason: str


class TelegramBotClient:

	def __init__(self, token: str | None = None, chat_id: str | None = None):
		self.token = str(token if token is not None else os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
		self.chat_id = str(chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID", "")).strip()
		self.last_error = None

	def status(self):
		configured = bool(self.token and self.chat_id)
		if not configured:
			return TelegramBotStatus(configured=False, active=False, reason="telegram credentials missing")
		if self.last_error:
			return TelegramBotStatus(configured=True, active=False, reason=str(self.last_error))
		return TelegramBotStatus(configured=True, active=True, reason="OK")

	def send(self, message: str):
		if not self.token or not self.chat_id:
			self.last_error = "telegram credentials missing"
			return False

		payload = {
			"chat_id": self.chat_id,
			"text": str(message or ""),
		}
		url = f"https://api.telegram.org/bot{self.token}/sendMessage"

		try:
			response = requests.post(url, json=payload, timeout=8)
			response.raise_for_status()
			self.last_error = None
			return True
		except Exception as exc:
			self.last_error = str(exc)
			return False
