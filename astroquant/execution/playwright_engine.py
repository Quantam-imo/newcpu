import threading
import time
import re
from typing import Any
from backend.execution.execution_guard import ExecutionGuard


class PlaywrightEngine:

	def __init__(self, headless=False, timeout_ms=10000, user_data_dir=None, cdp_url=None):
		self.headless = bool(headless)
		self.timeout_ms = int(timeout_ms)
		self.user_data_dir = str(user_data_dir).strip() if user_data_dir else None
		self.cdp_url = str(cdp_url).strip() if cdp_url else None
		self.p = None
		self.browser = None
		self.context = None
		self.page = None
		self._attached_over_cdp = False

	def start(self):
		if self.page is not None:
			return self.page

		try:
			from playwright.sync_api import sync_playwright
		except Exception as exc:
			raise RuntimeError("Playwright is not installed/configured. Install playwright and browser binaries.") from exc

		self.p = sync_playwright().start()
		if self.cdp_url:
			self.browser = self.p.chromium.connect_over_cdp(self.cdp_url)
			contexts = list(self.browser.contexts)
			self.context = contexts[0] if contexts else self.browser.new_context()
			candidate_pages = []
			for ctx in contexts or [self.context]:
				candidate_pages.extend(list(ctx.pages))

			selected = None
			for page in candidate_pages:
				try:
					url = str(page.url or "").lower()
					if "maven.markets" in url or "matchtrader" in url:
						selected = page
						break
				except Exception:
					continue

			self.page = selected or (candidate_pages[0] if candidate_pages else self.context.new_page())
			self._attached_over_cdp = True
			self.page.set_default_timeout(self.timeout_ms)
			return self.page

		common_args = [
			"--no-sandbox",
			"--disable-dev-shm-usage",
			"--disable-gpu",
			"--disable-setuid-sandbox",
		]
		if self.user_data_dir:
			self.context = self.p.chromium.launch_persistent_context(
				user_data_dir=self.user_data_dir,
				headless=self.headless,
				args=common_args,
			)
			self.browser = self.context.browser
			pages = self.context.pages
			self.page = pages[0] if pages else self.context.new_page()
		else:
			self.browser = self.p.chromium.launch(headless=self.headless, args=common_args)
			self.context = self.browser.new_context()
			self.page = self.context.new_page()
		self.page.set_default_timeout(self.timeout_ms)
		return self.page

	def goto(self, url):
		self.start()
		self.page.goto(str(url), wait_until="domcontentloaded")
		try:
			self.page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
		except Exception:
			pass

	def click(self, selector):
		self.start()
		self.page.wait_for_selector(selector, timeout=self.timeout_ms)
		self.page.click(selector)

	def fill(self, selector, value):
		self.start()
		self.page.wait_for_selector(selector, timeout=self.timeout_ms)
		self.page.fill(selector, str(value))

	def get_text(self, selector):
		self.start()
		self.page.wait_for_selector(selector, timeout=self.timeout_ms)
		return self.page.inner_text(selector)

	def exists(self, selector):
		self.start()
		try:
			return self.page.locator(selector).count() > 0
		except Exception:
			return False

	def is_visible(self, selector):
		self.start()
		try:
			loc = self.page.locator(selector)
			if loc.count() <= 0:
				return False
			return bool(loc.first.is_visible())
		except Exception:
			return False

	def read_many_text(self, selectors: list[str]) -> dict[str, str | None]:
		self.start()
		output = {}
		for selector in selectors:
			try:
				if self.page.locator(selector).count() <= 0:
					output[selector] = None
				else:
					output[selector] = self.page.locator(selector).first.inner_text()
			except Exception:
				output[selector] = None
		return output

	def close(self):
		if self._attached_over_cdp:
			if self.p is not None:
				try:
					self.p.stop()
				except Exception:
					pass
			self.p = None
			self.browser = None
			self.context = None
			self.page = None
			self._attached_over_cdp = False
			return

		for member in ("context", "browser", "p"):
			obj: Any = getattr(self, member, None)
			if obj is None:
				continue
			try:
				obj.close() if member != "p" else obj.stop()
			except Exception:
				pass
			setattr(self, member, None)
		self.page = None


def execution_timeout(seconds, func):
	result = {"value": None, "error": None}

	def wrapper():
		try:
			result["value"] = func()
		except Exception as exc:
			result["error"] = exc

	thread = threading.Thread(target=wrapper, daemon=True)
	thread.start()
	thread.join(seconds)

	if thread.is_alive():
		return "TIMEOUT"

	if result["error"] is not None:
		raise result["error"]

	return result["value"]


class PlaywrightExecutionEngine:

	def __init__(self):
		self.order_in_progress = False
		self.last_trade_time = None
		self.page = None
		self.last_error = None
		self.slippage_limit = 0.5
		self.fill_tolerance = 0.95
		self.duplicate_window_seconds = 30
		self.timeout_seconds = 10
		self.selector_failure_count = 0
		self.selector_failure_limit = 5
		self.last_selector_failure_at = None
		self.reconnect_handler = None
		self.reconnect_attempts = 0
		self.last_reconnect_attempt = 0
		self.reconnect_cooldown_seconds = 15
		self.last_browser_heartbeat = 0
		self.execution_guard = ExecutionGuard()
		self.selector_halted = False
		self.last_selector_failure_reason = None
		self.selector_aliases = {
			"quote": [
				"[data-testid='quotation']",
				"[data-testid='quotation-last']",
				"[data-testid='last-price']",
				"[data-testid='quotation-bid']",
				"[data-testid='quotation-ask']",
			],
			"buy": [
				"[data-testid='order-panel-buy-button']",
				"button:has-text('Buy')",
			],
			"sell": [
				"[data-testid='order-panel-sell-button']",
				"button:has-text('Sell')",
			],
		}
		self.max_execution_retries = 2
		self.retry_backoff_seconds = 0.9

	def set_page(self, page):
		self.page = page

	def set_reconnect_handler(self, handler):
		self.reconnect_handler = handler

	def emergency_halt(self, reason):
		self.last_error = str(reason)
		self.execution_guard.halt(reason)

	def execution_health(self):
		snapshot = self.execution_guard.health_snapshot()
		snapshot["selector_failure_count"] = self.selector_failure_count
		snapshot["selector_failure_limit"] = self.selector_failure_limit
		snapshot["selector_halted"] = bool(self.selector_halted)
		snapshot["selector_last_reason"] = self.last_selector_failure_reason
		snapshot["reconnect_attempts"] = self.reconnect_attempts
		snapshot["last_reconnect_attempt"] = self.last_reconnect_attempt
		snapshot["last_browser_heartbeat"] = self.last_browser_heartbeat
		return snapshot

	def _record_selector_failure(self, reason):
		self.selector_failure_count += 1
		self.last_selector_failure_at = int(time.time())
		self.last_selector_failure_reason = str(reason)
		if self.selector_failure_count >= int(self.selector_failure_limit):
			self.selector_halted = True
			self.execution_guard.halt(f"Selector failure threshold reached: {reason}")

	def _record_selector_success(self):
		if self.selector_failure_count > 0:
			self.selector_failure_count = 0
		self.selector_halted = False
		self.last_selector_failure_reason = None

	def _attempt_reconnect(self):
		now = time.time()
		if self.reconnect_handler is None:
			return False
		if (now - float(self.last_reconnect_attempt or 0.0)) < float(self.reconnect_cooldown_seconds):
			return False

		self.last_reconnect_attempt = int(now)
		self.reconnect_attempts += 1

		try:
			page = self.reconnect_handler()
			if page is None:
				return False
			self.page = page
			self.last_browser_heartbeat = int(time.time())
			self.execution_guard.reset()
			self.last_error = None
			self._record_selector_success()
			return True
		except Exception:
			return False

	def broker_positions_snapshot(self):
		page = self.page
		if page is None:
			return None

		try:
			position = self._read_position(page)
		except Exception:
			return None

		if not position:
			return []

		return [position]

	def broker_equity_snapshot(self):
		page = self.page
		if page is None:
			return None

		value = self._safe_price(page, "[data-testid='account-equity']")
		if value is None:
			return None
		return float(value)

	def _first_visible_text(self, page, selectors):
		for selector in selectors:
			value = self._safe_text(page, selector)
			if value:
				return value
		return None

	def _first_visible_price(self, page, selectors):
		for selector in selectors:
			value = self._safe_price(page, selector)
			if value is not None:
				return float(value)
		return None

	def broker_quote_snapshot(self, expected_symbols=None):
		page = self.page
		if page is None:
			if not self._attempt_reconnect():
				self._record_selector_failure("broker quote page unavailable")
				return None
			page = self.page

		symbol_text = self._first_visible_text(
			page,
			[
				"[data-testid='quotation-symbol']",
				"[data-testid='instrument-symbol']",
				"[data-testid='symbol-name']",
				"[data-testid='position-symbol']",
			],
		)

		bid = self._first_visible_price(
			page,
			[
				"[data-testid='quotation-bid']",
				"[data-testid='bid-price']",
			],
		)
		ask = self._first_visible_price(
			page,
			[
				"[data-testid='quotation-ask']",
				"[data-testid='ask-price']",
			],
		)
		last = self._first_visible_price(
			page,
			[
				"[data-testid='quotation']",
				"[data-testid='quotation-last']",
				"[data-testid='last-price']",
			],
		)

		if bid is None and ask is None and last is None:
			self._record_selector_failure("quote selectors unavailable")
			return None

		self._record_selector_success()
		self.last_browser_heartbeat = int(time.time())

		mid = None
		spread = None
		if bid is not None and ask is not None:
			mid = (float(bid) + float(ask)) / 2.0
			spread = abs(float(ask) - float(bid))
		elif last is not None:
			mid = float(last)

		symbol_mismatch = False
		if expected_symbols:
			expected = {str(s or "").upper().replace("/", "") for s in expected_symbols if str(s or "").strip()}
			seen_symbol = str(symbol_text or "").upper().replace("/", "")
			if expected and seen_symbol and seen_symbol not in expected:
				symbol_mismatch = True

		return {
			"symbol": symbol_text,
			"bid": bid,
			"ask": ask,
			"last": last,
			"mid": mid,
			"spread": spread,
			"symbol_mismatch": symbol_mismatch,
			"source": "PLAYWRIGHT_BROWSER",
			"captured_at": int(time.time()),
		}

	def _parse_price(self, text):
		cleaned = re.sub(r"[^0-9.\-]", "", str(text or "").replace(",", "").strip())
		return float(cleaned)

	def _dom_stable(self, page):
		try:
			buy_visible = any(page.locator(selector).count() > 0 and page.locator(selector).first.is_visible() for selector in self.selector_aliases["buy"])
			sell_visible = any(page.locator(selector).count() > 0 and page.locator(selector).first.is_visible() for selector in self.selector_aliases["sell"])
			stable = bool(buy_visible and sell_visible)
			if stable:
				self._record_selector_success()
				self.last_browser_heartbeat = int(time.time())
			else:
				self._record_selector_failure("order panel selectors missing")
			return stable
		except Exception:
			self._record_selector_failure("order panel selectors exception")
			return False

	def confirm_execution(self, page):
		try:
			page.wait_for_selector("[data-testid='open-positions-tab']", timeout=5000)
			return True
		except Exception:
			return False

	def close_position_immediately(self, page):
		try:
			if page.locator("[data-testid='position-close-button']").is_visible():
				page.locator("[data-testid='position-close-button']").click()
				return True
		except Exception:
			return False
		return False

	def _is_partial_fill(self, page, expected_lot_size):
		try:
			filled_size = self._parse_price(
				page.locator("[data-testid='position-volume']").inner_text()
			)
			return filled_size < (float(expected_lot_size) * self.fill_tolerance)
		except Exception:
			return False

	def _safe_text(self, page, selector):
		try:
			locator = page.locator(selector)
			if locator.count() <= 0:
				return None
			text = locator.first.inner_text()
			return str(text).strip() if text is not None else None
		except Exception:
			return None

	def _safe_price(self, page, selector):
		text = self._safe_text(page, selector)
		if text is None or text == "":
			return None
		try:
			return self._parse_price(text)
		except Exception:
			return None

	def _first_available_price(self, page, selectors):
		for selector in selectors or []:
			value = self._safe_price(page, selector)
			if value is not None:
				return value
		return None

	def recover_from_selector_failure(self, force_reconnect=False):
		if not self.selector_halted and not force_reconnect:
			return {"ok": True, "reason": "No selector halt active"}

		if force_reconnect:
			self.last_reconnect_attempt = 0

		if self.page is None and not self._attempt_reconnect():
			return {"ok": False, "reason": "Reconnect failed"}

		page = self.page
		if page is None:
			return {"ok": False, "reason": "Page unavailable"}

		dom_ok = self._dom_stable(page)
		quote_ok = self._first_available_price(page, self.selector_aliases["quote"]) is not None
		if dom_ok or quote_ok:
			self.execution_guard.reset()
			self._record_selector_success()
			self.last_error = None
			return {"ok": True, "reason": "Recovered", "dom_ok": dom_ok, "quote_ok": quote_ok}

		return {"ok": False, "reason": "Selectors still unavailable", "dom_ok": dom_ok, "quote_ok": quote_ok}

	def _read_position(self, page):
		entry_price = self._safe_price(page, "[data-testid='position-entry-price']")
		volume = self._safe_price(page, "[data-testid='position-volume']")
		sl = self._safe_price(page, "[data-testid='position-sl']")
		tp = self._safe_price(page, "[data-testid='position-tp']")
		symbol = self._safe_text(page, "[data-testid='position-symbol']")

		if entry_price is None:
			return None

		return {
			"entry_price": entry_price,
			"volume": volume,
			"sl": sl,
			"tp": tp,
			"symbol": symbol,
		}

	def _place_order(self, signal, lot_size, page):
		if not self._dom_stable(page):
			if self._attempt_reconnect() and self.page is not None and self._dom_stable(self.page):
				page = self.page
			else:
				self.emergency_halt("Broker disconnected / DOM unstable")
				return {"status": "Rejected", "reason": "DOM not stable"}

		expected_entry = signal.get("entry_price")
		expected_sl = signal.get("sl")
		expected_tp = signal.get("tp")
		valid, message = self.execution_guard.validate_sl_tp(expected_sl, expected_tp, expected_entry)
		if not valid:
			self.emergency_halt(message)
			return {"status": "Rejected", "reason": message}

		requested_price = self._first_available_price(page, self.selector_aliases["quote"])
		if requested_price is None:
			requested_price = expected_entry

		direction = signal.get("direction", "").upper()
		if direction == "BUY":
			clicked = False
			for selector in self.selector_aliases["buy"]:
				if page.locator(selector).count() > 0:
					page.locator(selector).first.click()
					clicked = True
					break
			if not clicked:
				return {"status": "Rejected", "reason": "Buy selector not found"}
		elif direction == "SELL":
			clicked = False
			for selector in self.selector_aliases["sell"]:
				if page.locator(selector).count() > 0:
					page.locator(selector).first.click()
					clicked = True
					break
			if not clicked:
				return {"status": "Rejected", "reason": "Sell selector not found"}
		else:
			self.emergency_halt("Invalid direction")
			return {"status": "Rejected", "reason": "Invalid direction"}

		filled, position_data = self.execution_guard.wait_for_fill(
			lambda: self._read_position(page)
		)
		if not filled or not position_data:
			self.emergency_halt("Order timeout - no fill confirmation")
			return {"status": "Rejected", "reason": "Execution timeout"}

		executed_price = float(position_data.get("entry_price"))

		if self._is_partial_fill(page, lot_size):
			self.close_position_immediately(page)
			self.emergency_halt("Partial fill detected")
			return {"status": "Rejected", "reason": "Partial fill detected"}

		expected_fill_price = expected_entry if expected_entry is not None else requested_price
		slippage_ok, slippage = self.execution_guard.check_slippage(expected_fill_price, executed_price)
		if not slippage_ok:
			self.close_position_immediately(page)
			self.emergency_halt(f"Slippage breach ({slippage})")
			return {"status": "Rejected", "reason": "Slippage exceeded limit"}

		verify_ok, verify_reason = self.execution_guard.verify_position(
			position_data,
			expected_symbol=signal.get("symbol"),
			expected_volume=lot_size,
		)
		if not verify_ok:
			self.close_position_immediately(page)
			self.emergency_halt(verify_reason)
			return {"status": "Rejected", "reason": verify_reason}

		return {
			"status": "EXECUTED",
			"model": signal.get("model"),
			"direction": direction,
			"lot_size": lot_size,
			"requested_price": requested_price,
			"entry_price": executed_price,
			"slippage": slippage,
			"fill_price": executed_price,
			"position_data": position_data,
			"execution_source": "PLAYWRIGHT",
		}

	def _is_transient_rejection(self, result):
		if not isinstance(result, dict):
			return False
		if str(result.get("status") or "").upper() == "EXECUTED":
			return False
		reason = str(result.get("reason") or "").lower()
		if "timeout" in reason:
			return True
		if "disconnected" in reason:
			return True
		if "dom not stable" in reason:
			return True
		if "in progress" in reason:
			return True
		return False

	def execute(self, signal, lot_size, page=None):
		if self.execution_guard.is_halted():
			return {"status": "Rejected", "reason": "Execution HALTED"}

		if lot_size <= 0:
			return {"status": "Rejected", "reason": "Invalid lot size"}

		page = page or self.page

		if self.order_in_progress:
			return {"status": "Rejected", "reason": "Order already in progress"}

		now = time.time()
		if self.last_trade_time and (now - self.last_trade_time) < self.duplicate_window_seconds:
			return {"status": "Rejected", "reason": "Trade blocked - duplicate within 30s"}

		self.order_in_progress = True
		result = {"status": "Rejected", "reason": "Execution not attempted"}
		try:
			if page is None:
				if self._attempt_reconnect():
					page = self.page
				if page is None:
					self.emergency_halt("Broker disconnected")
					return {"status": "Rejected", "reason": "Broker disconnected", "retry_attempts": 0}

			max_attempts = max(1, int(self.max_execution_retries) + 1)
			for attempt in range(1, max_attempts + 1):
				result = execution_timeout(
					self.timeout_seconds,
					lambda: self._place_order(signal, lot_size, page),
				)
				if result == "TIMEOUT":
					result = {"status": "Rejected", "reason": "Execution timeout"}

				if str(result.get("status") or "").upper() == "EXECUTED":
					result["retry_attempts"] = attempt - 1
					break

				if attempt >= max_attempts or not self._is_transient_rejection(result):
					result["retry_attempts"] = attempt - 1
					break

				time.sleep(float(self.retry_backoff_seconds))
				if self._attempt_reconnect() and self.page is not None:
					page = self.page

			if result.get("status") == "EXECUTED":
				self.last_trade_time = now
				self.last_browser_heartbeat = int(time.time())
			return result
		except Exception as exc:
			self.emergency_halt(f"Playwright crash / execution failure: {exc}")
			return {"status": "Rejected", "reason": f"Execution failed: {exc}"}
		finally:
			self.order_in_progress = False

