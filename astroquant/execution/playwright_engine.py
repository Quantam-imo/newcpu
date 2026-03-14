import threading
import time
import re
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen
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
			cdp_target = self._resolve_cdp_url(self.cdp_url)
			self.browser = self.p.chromium.connect_over_cdp(cdp_target)
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

	def _resolve_cdp_url(self, endpoint):
		value = str(endpoint or "").strip()
		if not value:
			return value

		parsed = urlparse(value)
		if parsed.scheme in {"ws", "wss"} and "/devtools/browser/" in str(parsed.path or ""):
			return value

		discovery_url = None
		if parsed.scheme in {"http", "https"} and parsed.netloc:
			discovery_url = value.rstrip("/")
			if not str(parsed.path or "").endswith("/json/version"):
				discovery_url = f"{discovery_url}/json/version"
		elif parsed.scheme in {"ws", "wss"} and parsed.netloc and str(parsed.path or "") in {"", "/"}:
			discovery_scheme = "https" if parsed.scheme == "wss" else "http"
			discovery_url = f"{discovery_scheme}://{parsed.netloc}/json/version"

		if not discovery_url:
			return value

		try:
			with urlopen(discovery_url, timeout=max(2.0, min(float(self.timeout_ms) / 1000.0, 5.0))) as response:
				payload = json.loads(response.read().decode("utf-8"))
			websocket_url = str((payload or {}).get("webSocketDebuggerUrl") or "").strip()
			return websocket_url or value
		except Exception:
			return value

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
		self.task_dispatcher = None
		self._dispatch_thread_ident = None
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
		self.partial_watchers = {}
		self.partial_watch_lock = threading.Lock()
		self.selector_profile_path = Path(os.getenv("EXECUTION_SELECTOR_PROFILE_FILE", "data/matchtrader_selectors.json"))
		self.selector_profile_loaded = False
		self.selector_profile_updated_at = None
		self.selector_aliases = {
			"order_panel": [
				"trade-order-panel[data-testid='mw-order-panel']",
				"[data-testid='mw-order-panel']",
			],
			"quote": [
				"[data-testid='quotation']",
				"[data-testid='quotation-last']",
				"[data-testid='last-price']",
				"[data-testid='quotation-bid']",
				"[data-testid='quotation-ask']",
			],
			"volume": [
				"[data-testid='mw-order-panel'] [data-testid='input-stepper-input']",
				"[data-testid='input-stepper-input']",
				"[data-testid='order-lot-size']",
			],
			"buy": [
				"[data-testid='mw-order-panel'] [data-testid='order-panel-buy-button']",
				"[data-testid='order-panel-buy-button']",
				"button:has-text('Buy')",
			],
			"sell": [
				"[data-testid='mw-order-panel'] [data-testid='order-panel-sell-button']",
				"[data-testid='order-panel-sell-button']",
				"button:has-text('Sell')",
			],
			"buy_price": [
				"[data-testid='mw-order-panel'] [data-testid='order-panel-buy-button'] .ui-order-button__price",
				"[data-testid='order-panel-buy-button'] .ui-order-button__price",
			],
			"sell_price": [
				"[data-testid='mw-order-panel'] [data-testid='order-panel-sell-button'] .ui-order-button__price",
				"[data-testid='order-panel-sell-button'] .ui-order-button__price",
			],
			"confirm": [
				"[data-testid='overlay-confirm-actions-confirm']",
				"[data-testid='order-panel-confirm-button']",
				"button:has-text('Confirm')",
				"button:has-text('Place order')",
				"button:has-text('Place Order')",
				"button:has-text('Submit')",
			],
			"confirm_cancel": [
				"[data-testid='overlay-confirm-actions-cancel']",
				"button:has-text('Cancel')",
				"div.ui-secondary-button__content:has-text('Cancel')",
			],
			"confirm_checkbox": [
				"[data-testid='checkbox-input']",
			],
			"stop_loss_input": [
				"[data-testid='mw-order-panel'] [data-testid*='stop-loss'] input",
				"[data-testid='mw-order-panel'] [data-testid='position-sl'] input",
				"[data-testid*='stop-loss'] input",
				"input[name='stopLoss']",
				"input[placeholder*='SL']",
			],
			"take_profit_input": [
				"[data-testid='mw-order-panel'] [data-testid*='take-profit'] input",
				"[data-testid='mw-order-panel'] [data-testid='position-tp'] input",
				"[data-testid*='take-profit'] input",
				"input[name='takeProfit']",
				"input[placeholder*='TP']",
			],
			"close_partial_volume": [
				"[data-testid*='close-volume'] input",
				"[data-testid*='close-position-volume'] input",
				"[data-testid*='volume'] input",
				"input[name='volume']",
			],
			"close_partial_confirm": [
				"[data-testid*='confirm-close']",
				"[data-testid='overlay-confirm-actions-confirm']",
				"button:has-text('Close Position')",
				"button:has-text('Close partially')",
				"button:has-text('Confirm')",
			],
			"login_username": [
				"input[type='email']",
				"input[name='email']",
				"input[name='username']",
				"input[autocomplete='username']",
				"input[placeholder*='Email']",
				"input[placeholder*='User']",
			],
			"login_password": [
				"input[type='password']",
				"input[name='password']",
				"input[autocomplete='current-password']",
				"input[placeholder*='Password']",
			],
			"login_submit": [
				"button[type='submit']",
				"button:has-text('Login')",
				"button:has-text('Log in')",
				"button:has-text('Sign in')",
			],
		}
		self.max_execution_retries = 2
		self.retry_backoff_seconds = 0.9
		self.fixed_lot_size = float(os.getenv("EXECUTION_FIXED_LOT", "0.2") or 0.2)
		self.force_fixed_lot = str(os.getenv("EXECUTION_FORCE_FIXED_LOT", "true") or "true").strip().lower() in {"1", "true", "yes", "on"}
		self._load_selector_profile()

	def _merge_selector_values(self, key, values):
		if key not in self.selector_aliases or not isinstance(values, list):
			return
		current = list(self.selector_aliases.get(key, []))
		merged = []
		seen = set()
		for selector in [*values, *current]:
			text = str(selector or "").strip()
			if not text or text in seen:
				continue
			seen.add(text)
			merged.append(text)
		self.selector_aliases[key] = merged

	def _selector_profile_targets(self, key):
		mapping = {
			"login_email": ["login_username"],
			"login_button": ["login_submit"],
			"volume": ["volume"],
			"lot": ["volume"],
			"quote": ["quote"],
			"bid": ["quote"],
			"ask": ["quote"],
			"last": ["quote"],
			"sl": ["stop_loss_input"],
			"tp": ["take_profit_input"],
		}
		if key in self.selector_aliases:
			return [key]
		return mapping.get(str(key or "").strip(), [])

	def _load_selector_profile(self):
		path = self.selector_profile_path
		if not path.exists():
			return
		try:
			payload = json.loads(path.read_text(encoding="utf-8"))
		except Exception:
			return

		if not isinstance(payload, dict):
			return

		selectors = payload.get("selectors", {})
		if not isinstance(selectors, dict):
			return

		loaded_any = False
		for key, values in selectors.items():
			if not isinstance(values, list):
				continue
			for target in self._selector_profile_targets(key):
				self._merge_selector_values(target, [str(v) for v in values])
				loaded_any = True

		if not loaded_any:
			return

		self.selector_profile_loaded = True
		updated_at = payload.get("updated_at")
		try:
			self.selector_profile_updated_at = int(updated_at) if updated_at is not None else None
		except Exception:
			self.selector_profile_updated_at = None

	def set_page(self, page):
		self.page = page

	def set_task_dispatcher(self, dispatcher):
		self.task_dispatcher = dispatcher

	def mark_dispatch_thread(self):
		self._dispatch_thread_ident = threading.get_ident()

	def _run_thread_affine(self, func, timeout_seconds=None):
		if self._dispatch_thread_ident is not None and threading.get_ident() == self._dispatch_thread_ident:
			return func()
		if callable(self.task_dispatcher):
			return self.task_dispatcher(func, timeout_seconds=timeout_seconds)
		return func()

	def _should_dispatch(self):
		return callable(self.task_dispatcher) and threading.get_ident() != self._dispatch_thread_ident

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
		snapshot["selector_profile_loaded"] = bool(self.selector_profile_loaded)
		snapshot["selector_profile_updated_at"] = self.selector_profile_updated_at
		return snapshot

	def _has_any_selector(self, page, selectors):
		for selector in selectors or []:
			try:
				loc = page.locator(selector)
				if loc.count() > 0 and bool(loc.first.is_visible()):
					return True
			except Exception:
				continue
		return False

	def _set_text_input(self, page, selectors, value):
		text = str(value or "")
		if not text:
			return False
		for selector in selectors or []:
			try:
				loc = page.locator(selector)
				if loc.count() <= 0:
					continue
				field = loc.first
				try:
					field.click(timeout=1200)
					field.fill("")
					field.type(text, delay=5)
					return True
				except Exception:
					pass
				try:
					field.fill(text)
					return True
				except Exception:
					continue
			except Exception:
				continue
		return False

	def _execution_surface_ready(self, page):
		try:
			if self._has_any_selector(page, self.selector_aliases.get("order_panel", [])):
				return True
		except Exception:
			pass
		try:
			quote = self.broker_quote_snapshot(expected_symbols=None) or {}
			if quote.get("mid") is not None or quote.get("last") is not None:
				return True
		except Exception:
			pass
		return False

	def login_if_needed(self, username=None, password=None):
		if self._should_dispatch():
			return self._run_thread_affine(
				lambda: self.login_if_needed(username=username, password=password),
				timeout_seconds=12.0,
			)

		page = self.page
		if page is None:
			if not self._attempt_reconnect():
				return {"ok": False, "status": "not_connected"}
			page = self.page

		if self._execution_surface_ready(page):
			return {"ok": True, "status": "already_authenticated"}

		login_user_present = self._has_any_selector(page, self.selector_aliases.get("login_username", []))
		login_pass_present = self._has_any_selector(page, self.selector_aliases.get("login_password", []))
		if not (login_user_present and login_pass_present):
			return {"ok": False, "status": "login_form_not_detected"}

		if not username or not password:
			return {"ok": False, "status": "credentials_missing"}

		user_ok = self._set_text_input(page, self.selector_aliases.get("login_username", []), username)
		pass_ok = self._set_text_input(page, self.selector_aliases.get("login_password", []), password)
		clicked, click_err = self._click_order_button(page, self.selector_aliases.get("login_submit", []))

		if not (user_ok and pass_ok and clicked):
			return {
				"ok": False,
				"status": "login_submit_failed",
				"user_ok": bool(user_ok),
				"pass_ok": bool(pass_ok),
				"click_ok": bool(clicked),
				"click_error": click_err,
			}

		try:
			time.sleep(2.0)
			if self._execution_surface_ready(page):
				self.last_browser_heartbeat = int(time.time())
				return {"ok": True, "status": "login_success"}
		except Exception:
			pass

		return {"ok": False, "status": "login_attempted_pending"}

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
		if self._should_dispatch():
			return self._run_thread_affine(self.broker_positions_snapshot, timeout_seconds=4.0)

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
		if self._should_dispatch():
			return self._run_thread_affine(self.broker_equity_snapshot, timeout_seconds=4.0)

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
		if self._should_dispatch():
			return self._run_thread_affine(
				lambda: self.broker_quote_snapshot(expected_symbols=expected_symbols),
				timeout_seconds=4.0,
			)

		page = self.page
		if page is None:
			if not self._attempt_reconnect():
				# Quote polling is observational and should not halt execution when
				# browser attach is temporarily unavailable.
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
			# Quote polling can briefly fail on page transitions/login screens.
			# Avoid hard-halting here; execution paths still enforce strict selector checks.
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

	def order_panel_snapshot(self):
		if self._should_dispatch():
			return self._run_thread_affine(self.order_panel_snapshot, timeout_seconds=4.0)

		page = self.page
		if page is None:
			return {
				"ready": False,
				"reason": "page_unavailable",
				"buy_price": None,
				"sell_price": None,
				"volume_control": False,
			}

		def _exists(selectors):
			for selector in selectors or []:
				try:
					if page.locator(selector).count() > 0:
						return True
				except Exception:
					continue
			return False

		buy_exists = _exists(self.selector_aliases.get("buy", []))
		sell_exists = _exists(self.selector_aliases.get("sell", []))
		volume_exists = _exists(self.selector_aliases.get("volume", []))
		panel_exists = _exists(self.selector_aliases.get("order_panel", []))

		buy_price = self._first_available_price(page, self.selector_aliases.get("buy_price", []))
		sell_price = self._first_available_price(page, self.selector_aliases.get("sell_price", []))

		ready = bool(panel_exists and buy_exists and sell_exists and volume_exists)
		reason = "ok" if ready else "selectors_missing"
		if not panel_exists:
			reason = "order_panel_missing"

		return {
			"ready": ready,
			"reason": reason,
			"panel": panel_exists,
			"buy_button": buy_exists,
			"sell_button": sell_exists,
			"volume_control": volume_exists,
			"buy_price": buy_price,
			"sell_price": sell_price,
			"captured_at": int(time.time()),
		}

	def calibrate_selectors(self, save: bool = True):
		if self._should_dispatch():
			return self._run_thread_affine(lambda: self.calibrate_selectors(save=save), timeout_seconds=20.0)

		page = self.page
		if page is None:
			return {"ok": False, "reason": "page_unavailable"}

		discovered = {}
		for key, selectors in self.selector_aliases.items():
			valid = []
			for selector in selectors or []:
				try:
					if page.locator(selector).count() > 0:
						valid.append(selector)
				except Exception:
					continue
			discovered[key] = valid

		for key, values in discovered.items():
			if not values:
				continue
			self._merge_selector_values(key, values)

		profile = {
			"updated_at": int(time.time()),
			"selectors": self.selector_aliases,
		}

		profile_file = self.selector_profile_path
		if save:
			profile_file.parent.mkdir(parents=True, exist_ok=True)
			profile_file.write_text(json.dumps(profile, indent=2), encoding="utf-8")
			self.selector_profile_loaded = True
			self.selector_profile_updated_at = profile.get("updated_at")

		return {
			"ok": True,
			"profile_file": str(profile_file),
			"discovered_keys": {k: len(v) for k, v in discovered.items()},
			"profile_loaded": bool(self.selector_profile_loaded),
		}

	def _parse_price(self, text):
		cleaned = re.sub(r"[^0-9.\-]", "", str(text or "").replace(",", "").strip())
		return float(cleaned)

	def _normalize_symbol(self, value):
		text = str(value or "").upper().replace("/", "").strip()
		return re.sub(r"[^A-Z0-9]", "", text)

	def _symbol_matches(self, actual, expected):
		actual_norm = self._normalize_symbol(actual)
		expected_norm = self._normalize_symbol(expected)
		if not expected_norm:
			return True
		if not actual_norm:
			return False
		if actual_norm == expected_norm:
			return True

		# Broker symbols can vary across BTC aliases.
		btc_aliases = {"BTC", "BTCUSD", "BTCUSDT"}
		if actual_norm in btc_aliases and expected_norm in btc_aliases:
			return True
		return False

	def _ensure_open_positions_panel(self, page):
		selectors = [
			"[data-testid='open-positions-tab']",
			"[data-testid*='open-positions'][data-testid*='tab']",
			"button:has-text('Open Positions')",
		]
		for selector in selectors:
			try:
				loc = page.locator(selector)
				if loc.count() <= 0:
					continue
				tab = loc.first
				try:
					tab.click(timeout=900)
				except Exception:
					try:
						tab.click(timeout=900, force=True)
					except Exception:
						continue
				time.sleep(0.08)
				return True
			except Exception:
				continue
		return False

	def _active_order_symbol(self, page):
		raw = self._first_visible_text(page, [
			"[data-testid='header-symbol']",
			"[data-testid='quotation-symbol']",
			"[data-testid='instrument-symbol']",
			"[data-testid='symbol-name']",
			"[data-testid='instrument-symbol-name-wrapper']",
		])
		return raw, self._normalize_symbol(raw)

	def _try_switch_symbol(self, page, target_symbol):
		target_norm = self._normalize_symbol(target_symbol)
		if not target_norm:
			return False

		# First try direct click on visible symbol labels.
		try:
			labels = page.locator("[data-testid='instrument-symbol-name-wrapper']")
			count = int(labels.count())
			for i in range(min(count, 120)):
				label = labels.nth(i)
				try:
					text = str(label.inner_text() or "")
				except Exception:
					continue
				norm = self._normalize_symbol(text)
				if norm != target_norm:
					continue
				try:
					label.click(timeout=1200)
				except Exception:
					label.click(timeout=1200, force=True)
				time.sleep(0.35)
				return True
		except Exception:
			pass

		# Fallback: DOM scan and click closest market row.
		try:
			clicked = bool(page.evaluate(
				"""
				(target) => {
				  const normalize = (v) => String(v || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
				  const all = Array.from(document.querySelectorAll('[data-testid="instrument-symbol-name-wrapper"]'));
				  for (const el of all) {
				    if (normalize(el.textContent) !== normalize(target)) continue;
				    const row = el.closest('[data-testid="list-row"], [data-testid="favorites-list-el"], [data-testid*="row"]') || el;
				    row.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
				    return true;
				  }
				  return false;
				}
				""",
				target_symbol,
			))
			if clicked:
				time.sleep(0.35)
				return True
		except Exception:
			pass

		return False

	def discover_broker_symbols(self, page, limit=300, include_quotes=True):
		if self._should_dispatch():
			return self._run_thread_affine(
				lambda: self.discover_broker_symbols(page, limit=limit, include_quotes=include_quotes),
				timeout_seconds=15.0,
			)

		max_items = max(10, min(int(limit or 300), 2000))
		nodes = [
			"[data-testid='instrument-symbol-name-wrapper']",
			"[data-testid='quotation-symbol']",
			"[data-testid='symbol-name']",
			"[data-testid='instrument-symbol']",
		]
		if include_quotes:
			nodes.extend([
				"[data-testid='quotation-bid']",
				"[data-testid='quotation-ask']",
			])

		try:
			rows = page.evaluate(
				"""
				(selectors, maxItems) => {
				  const out = [];
				  const seen = new Set();
				  const normalize = (v) => String(v || '').replace(/\s+/g, ' ').trim();
				  const toCanonical = (v) => normalize(v).toUpperCase().replace(/[^A-Z0-9/]/g, '');
				  for (const selector of selectors) {
				    const all = Array.from(document.querySelectorAll(selector));
				    for (const el of all) {
				      const text = normalize(el.textContent || el.innerText || '');
				      if (!text) continue;
				      const canonical = toCanonical(text);
				      if (!canonical) continue;
				      if (seen.has(canonical)) continue;
				      seen.add(canonical);
				      out.push({
				        symbol: text,
				        canonical,
				        selector,
				      });
				      if (out.length >= maxItems) return out;
				    }
				  }
				  return out;
				}
				""",
				nodes,
				max_items,
			) or []
		except Exception:
			rows = []

		clean = []
		seen = set()
		for row in list(rows or []):
			raw = str((row or {}).get("symbol") or "").strip()
			canonical = self._normalize_symbol((row or {}).get("canonical") or raw)
			if not re.search(r"[A-Z]", canonical):
				continue
			if not canonical or canonical in seen:
				continue
			seen.add(canonical)
			clean.append({
				"symbol": raw,
				"canonical": canonical,
				"selector": str((row or {}).get("selector") or ""),
			})

		active_raw, active_norm = self._active_order_symbol(page)
		return {
			"ok": True,
			"active_symbol": active_raw,
			"active_symbol_canonical": active_norm,
			"count": len(clean),
			"symbols": clean,
			"captured_at": int(time.time()),
		}

	def _dom_stable(self, page):
		def _has_actionable(selectors):
			for selector in selectors:
				try:
					locator = page.locator(selector)
					if locator.count() <= 0:
						continue
					# Detached/animating nodes can intermittently fail visibility checks.
					try:
						if locator.first.is_visible():
							return True
					except Exception:
						return True
				except Exception:
					continue
			return False

		buy_visible = _has_actionable(self.selector_aliases.get("buy", []))
		sell_visible = _has_actionable(self.selector_aliases.get("sell", []))
		stable = bool(buy_visible and sell_visible)
		if stable:
			self._record_selector_success()
			self.last_browser_heartbeat = int(time.time())
		else:
			self._record_selector_failure("order panel selectors missing")
		return stable

	def confirm_execution(self, page):
		try:
			page.wait_for_selector("[data-testid='open-positions-tab']", timeout=5000)
			return True
		except Exception:
			return False

	def _open_position_rows(self, page):
		self._ensure_open_positions_panel(page)
		selectors = [
			"[data-testid='open-positions-desktop-list-row']",
			"[data-testid*='open-positions'][data-testid*='row']",
			"[data-testid*='open-position'][data-testid*='row']",
			"[data-testid*='position'][data-testid*='row']",
			"[data-testid='position-row']",
			"[data-testid='positions-row']",
		]
		for selector in selectors:
			try:
				loc = page.locator(selector)
				if int(loc.count()) > 0:
					return loc
			except Exception:
				continue
		return None

	def _row_symbol_text(self, row):
		selectors = [
			"[data-testid='instrument-symbol-name-wrapper']",
			"[data-testid='position-symbol']",
			"[data-testid*='position-symbol']",
			"[data-testid='symbol-name']",
		]
		for selector in selectors:
			try:
				loc = row.locator(selector)
				if int(loc.count()) <= 0:
					continue
				text = str(loc.first.inner_text() or "").strip()
				if text:
					return text
			except Exception:
				continue
		return None

	def close_position_immediately(self, page, symbol=None, max_rows=20):
		if self._should_dispatch():
			return self._run_thread_affine(
				lambda: self.close_position_immediately(page, symbol=symbol, max_rows=max_rows),
				timeout_seconds=12.0,
			)

		target_norm = self._normalize_symbol(symbol)

		def _click_button(btn):
			try:
				btn.scroll_into_view_if_needed(timeout=1200)
			except Exception:
				pass
			try:
				btn.click(timeout=1500)
			except Exception:
				try:
					btn.click(timeout=1500, force=True)
				except Exception:
					btn.evaluate("el => el.click()")

		closed_any = False
		try:
			rows = self._open_position_rows(page)
			if rows is None:
				raise RuntimeError("open_position_rows_not_found")
			count = min(int(rows.count()), max(1, int(max_rows)))
			for i in range(count):
				row = rows.nth(i)
				row_symbol = self._row_symbol_text(row)
				if target_norm and not self._symbol_matches(row_symbol, target_norm):
					continue
				btn = None
				for selector in [
					"[data-testid='close-position-button']",
					"[data-testid*='close-position']",
					"button:has-text('Close')",
					"button:has-text('Close Position')",
				]:
					try:
						candidate = row.locator(selector)
						if candidate.count() > 0:
							btn = candidate
							break
					except Exception:
						continue
				if btn is None or btn.count() <= 0:
					continue
				try:
					_click_button(btn.first)
					self._confirm_order_if_present(page)
					closed_any = True
					time.sleep(0.15)
				except Exception:
					continue
		except Exception:
			pass

		if closed_any:
			return True

		selectors = [
			"[data-testid='position-close-button']",
			"[data-testid='close-position-button']",
			"[data-testid*='close-position']",
			"button:has-text('Close Position')",
			"button:has-text('Close')",
		]
		for selector in selectors:
			try:
				loc = page.locator(selector)
				if loc.count() <= 0:
					continue
				_click_button(loc.first)
				self._confirm_order_if_present(page)
				return True
			except Exception:
				continue
		return False

	def _is_partial_fill(self, page, expected_lot_size):
		try:
			filled_size = self._parse_price(
				page.locator("[data-testid='position-volume']").inner_text()
			)
			return filled_size < (float(expected_lot_size) * self.fill_tolerance)
		except Exception:
			return False

	def close_position_fraction(self, page, symbol=None, fraction=0.5):
		if self._should_dispatch():
			return self._run_thread_affine(
				lambda: self.close_position_fraction(page, symbol=symbol, fraction=fraction),
				timeout_seconds=15.0,
			)

		target_norm = self._normalize_symbol(symbol)
		fraction = max(0.01, min(0.99, float(fraction or 0.5)))

		try:
			rows = self._open_position_rows(page)
			if rows is None:
				return {"ok": False, "reason": "positions_unavailable"}
			count = int(rows.count())
		except Exception:
			return {"ok": False, "reason": "positions_unavailable"}

		selected = None
		selected_symbol = None
		selected_volume = None
		fallback_row = None
		fallback_symbol = None
		for i in range(min(count, 25)):
			row = rows.nth(i)
			row_symbol = self._row_symbol_text(row)
			if fallback_row is None:
				fallback_row = row
				fallback_symbol = row_symbol
			if target_norm and not self._symbol_matches(row_symbol, target_norm):
				continue
			selected = row
			selected_symbol = row_symbol
			try:
				v_text = selected.locator("[data-testid='open-position-volume']").first.inner_text()
				selected_volume = float(self._parse_price(v_text))
			except Exception:
				selected_volume = None
			break

		if selected is None:
			# Brokers may expose BTC symbols with slight naming variants (BTC/BTCUSD/BTCUSDT).
			# If only one row is open, use it as a safe fallback for partial close automation.
			if target_norm and count == 1 and fallback_row is not None:
				selected = fallback_row
				selected_symbol = fallback_symbol
			else:
				return {"ok": False, "reason": "symbol_not_found", "symbol": symbol}

		btn = selected.locator("[data-testid='close-position-button']")
		if btn.count() <= 0:
			btn = selected.locator("[data-testid*='close-position']")
		if btn.count() <= 0:
			btn = selected.locator("button:has-text('Close Position')")
		if btn.count() <= 0:
			btn = selected.locator("button:has-text('Close')")
		if btn.count() <= 0:
			return {"ok": False, "reason": "close_button_not_found", "symbol": selected_symbol}

		try:
			btn.first.click(timeout=1200)
		except Exception:
			try:
				btn.first.click(timeout=1200, force=True)
			except Exception as exc:
				return {"ok": False, "reason": f"close_click_failed: {exc}", "symbol": selected_symbol}

		if selected_volume is None:
			selected_volume = 0.0
		close_volume = max(0.01, round(float(selected_volume) * fraction, 2))
		if selected_volume > 0:
			close_volume = min(close_volume, max(0.01, round(selected_volume - 0.01, 2)))

		volume_set = self._set_price_input(page, self.selector_aliases.get("close_partial_volume", []), close_volume)
		if not volume_set:
			self._dismiss_overlay_backdrop(page)
			return {
				"ok": False,
				"reason": "partial_volume_input_not_found",
				"symbol": selected_symbol,
				"requested_close_volume": close_volume,
			}

		clicked, err = self._click_order_button(page, self.selector_aliases.get("close_partial_confirm", []))
		if not clicked:
			self._dismiss_overlay_backdrop(page)
			return {
				"ok": False,
				"reason": err or "close_partial_confirm_missing",
				"symbol": selected_symbol,
				"requested_close_volume": close_volume,
			}

		self._confirm_order_if_present(page)
		return {
			"ok": True,
			"symbol": selected_symbol,
			"fraction": fraction,
			"requested_close_volume": close_volume,
			"source_volume": selected_volume,
		}

	def _cancel_partial_watch(self, symbol):
		key = self._normalize_symbol(symbol)
		if not key:
			return
		with self.partial_watch_lock:
			active = self.partial_watchers.get(key)
			if active and isinstance(active, dict):
				active["cancelled"] = True

	def _start_partial_watch(self, signal, position_data):
		partial_cfg = dict(signal.get("partial") or {})
		if not partial_cfg or not bool(partial_cfg.get("enabled", False)):
			return {"enabled": False}

		symbol = str(position_data.get("symbol") or signal.get("symbol") or "").strip()
		direction = str(signal.get("direction") or "").upper().strip()
		entry = float(position_data.get("entry_price") or signal.get("entry_price") or 0.0)
		sl = signal.get("sl")
		ratio = max(0.1, min(0.9, float(partial_cfg.get("ratio") or 0.5)))
		rr = max(0.2, min(5.0, float(partial_cfg.get("target_rr") or 1.0)))
		ttl_seconds = max(60, min(8 * 3600, int(partial_cfg.get("ttl_seconds") or 3 * 3600)))

		if not symbol or direction not in {"BUY", "SELL"} or entry <= 0.0 or sl is None:
			return {"enabled": False, "reason": "invalid_partial_parameters"}

		stop_distance = abs(float(entry) - float(sl))
		if stop_distance <= 0.0:
			return {"enabled": False, "reason": "invalid_stop_distance"}

		target_price = float(partial_cfg.get("target_price") or 0.0)
		if target_price <= 0.0:
			if direction == "BUY":
				target_price = float(entry) + (stop_distance * rr)
			else:
				target_price = float(entry) - (stop_distance * rr)

		key = self._normalize_symbol(symbol)
		if not key:
			return {"enabled": False, "reason": "invalid_symbol"}

		self._cancel_partial_watch(symbol)
		job = {
			"symbol": symbol,
			"key": key,
			"direction": direction,
			"target_price": target_price,
			"ratio": ratio,
			"started_at": int(time.time()),
			"ttl_seconds": ttl_seconds,
			"cancelled": False,
			"triggered": False,
			"result": None,
		}

		def _worker():
			deadline = time.time() + ttl_seconds
			while time.time() < deadline:
				with self.partial_watch_lock:
					active = self.partial_watchers.get(key)
					if active is not job or bool(job.get("cancelled")):
						return
				if self.page is None:
					if not self._attempt_reconnect():
						time.sleep(1.0)
						continue
				quote = self.broker_quote_snapshot(expected_symbols=[symbol]) or {}
				price = quote.get("mid") or quote.get("last") or quote.get("bid") or quote.get("ask")
				if price is None:
					time.sleep(1.0)
					continue

				reached = (float(price) >= float(target_price)) if direction == "BUY" else (float(price) <= float(target_price))
				if not reached:
					time.sleep(1.0)
					continue

				result = self.close_position_fraction(self.page, symbol=symbol, fraction=ratio)
				job["triggered"] = True
				job["trigger_price"] = float(price)
				job["result"] = result
				with self.partial_watch_lock:
					if self.partial_watchers.get(key) is job:
						self.partial_watchers.pop(key, None)
				return

			with self.partial_watch_lock:
				if self.partial_watchers.get(key) is job:
					job["result"] = {"ok": False, "reason": "partial_watch_timeout"}
					self.partial_watchers.pop(key, None)

		thread = threading.Thread(target=_worker, daemon=True, name=f"aq-partial-{key[:8]}")
		job["thread"] = thread
		with self.partial_watch_lock:
			self.partial_watchers[key] = job
		thread.start()

		return {
			"enabled": True,
			"symbol": symbol,
			"target_price": round(float(target_price), 5),
			"ratio": ratio,
			"target_rr": rr,
			"ttl_seconds": ttl_seconds,
		}

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

	def _set_volume(self, page, lot_size):
		value_text = str(lot_size)
		for selector in self.selector_aliases.get("volume", []):
			try:
				locator = page.locator(selector)
				if locator.count() <= 0:
					continue
				field = locator.first

				# Standard edit path via keyboard.
				try:
					field.click()
					page.keyboard.press("Control+A")
					page.keyboard.type(value_text, delay=8)
					page.keyboard.press("Enter")
					time.sleep(0.05)
					return True
				except Exception:
					pass

				# Direct locator fill for input-like controls.
				try:
					field.fill(value_text)
					time.sleep(0.05)
					return True
				except Exception:
					pass

				# JS-driven update for stepper/custom components.
				try:
					field.evaluate(
						"""
						(el, value) => {
						  const target = el.matches('input,textarea,[contenteditable="true"]')
						    ? el
						    : el.querySelector('input,textarea,[contenteditable="true"]') || el;
						  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
						    target.focus();
						    target.value = String(value);
						    target.dispatchEvent(new Event('input', { bubbles: true }));
						    target.dispatchEvent(new Event('change', { bubbles: true }));
						    return true;
						  }
						  if (target && target.isContentEditable) {
						    target.focus();
						    target.textContent = String(value);
						    target.dispatchEvent(new Event('input', { bubbles: true }));
						    target.dispatchEvent(new Event('change', { bubbles: true }));
						    return true;
						  }
						  return false;
						}
						""",
						value_text,
					)
					time.sleep(0.05)
					return True
				except Exception:
					continue
			except Exception:
				continue
		return False

	def _set_price_input(self, page, selectors, price_value):
		if price_value is None:
			return False
		value_text = str(round(float(price_value), 5))
		for selector in selectors or []:
			try:
				locator = page.locator(selector)
				if locator.count() <= 0:
					continue
				field = locator.first

				try:
					field.click(timeout=1000)
					page.keyboard.press("Control+A")
					page.keyboard.type(value_text, delay=8)
					page.keyboard.press("Enter")
					time.sleep(0.05)
					return True
				except Exception:
					pass

				try:
					field.fill(value_text)
					time.sleep(0.05)
					return True
				except Exception:
					pass

				try:
					field.evaluate(
						"""
						(el, value) => {
						  const target = el.matches('input,textarea,[contenteditable="true"]')
						    ? el
						    : el.querySelector('input,textarea,[contenteditable="true"]') || el;
						  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
						    target.focus();
						    target.value = String(value);
						    target.dispatchEvent(new Event('input', { bubbles: true }));
						    target.dispatchEvent(new Event('change', { bubbles: true }));
						    return true;
						  }
						  return false;
						}
						""",
						value_text,
					)
					time.sleep(0.05)
					return True
				except Exception:
					continue
			except Exception:
				continue
		return False

	def _configure_protection(self, page, signal):
		sl = signal.get("sl")
		tp = signal.get("tp")
		sl_set = self._set_price_input(page, self.selector_aliases.get("stop_loss_input", []), sl) if sl is not None else False
		tp_set = self._set_price_input(page, self.selector_aliases.get("take_profit_input", []), tp) if tp is not None else False
		return {
			"sl_requested": sl,
			"tp_requested": tp,
			"sl_set": bool(sl_set),
			"tp_set": bool(tp_set),
		}

	def _dismiss_overlay_backdrop(self, page):
		dismissed = False
		try:
			backdrop = page.locator(".cdk-overlay-backdrop.cdk-overlay-backdrop-showing")
			if backdrop.count() > 0:
				try:
					backdrop.first.click(force=True, timeout=1000)
				except Exception:
					pass
				dismissed = True
		except Exception:
			pass

		try:
			page.keyboard.press("Escape")
			time.sleep(0.05)
		except Exception:
			pass
		return dismissed

	def _click_order_button(self, page, selectors):
		last_error = None
		for selector in selectors:
			try:
				locator = page.locator(selector)
				if locator.count() <= 0:
					continue
				target = locator.first
				try:
					target.scroll_into_view_if_needed(timeout=1200)
				except Exception:
					pass
				try:
					target.click(timeout=3000)
					return True, None
				except Exception as exc:
					message = str(exc)
					last_error = message
					lowered = message.lower()
					if "intercepts pointer events" in lowered or "overlay" in lowered:
						self._dismiss_overlay_backdrop(page)
						try:
							target.click(timeout=1500, force=True)
							return True, None
						except Exception as force_exc:
							message = str(force_exc)
							last_error = message
					try:
						target.click(timeout=1200, force=True)
						return True, None
					except Exception as force_exc:
						last_error = str(force_exc)
					try:
						target.evaluate("el => { el.click(); return true; }")
						return True, None
					except Exception as js_exc:
						last_error = str(js_exc)
					continue
			except Exception:
				continue
		return False, f"Order button click failed: {last_error}" if last_error else "Order button click failed"

	def _confirm_order_if_present(self, page):
		# Handle overlay confirmation dialogs that require checkbox consent first.
		for checkbox_selector in self.selector_aliases.get("confirm_checkbox", []):
			try:
				checkbox = page.locator(checkbox_selector)
				if checkbox.count() <= 0:
					continue
				target = checkbox.first
				is_checked = False
				try:
					is_checked = bool(target.is_checked())
				except Exception:
					is_checked = False
				if not is_checked:
					try:
						target.click(timeout=1200)
					except Exception:
						target.click(timeout=1200, force=True)
					time.sleep(0.05)
			except Exception:
				continue

		for selector in self.selector_aliases.get("confirm", []):
			try:
				locator = page.locator(selector)
				if locator.count() <= 0:
					continue
				try:
					locator.first.click(timeout=1500)
				except Exception:
					self._dismiss_overlay_backdrop(page)
					locator.first.click(timeout=1500, force=True)
				time.sleep(0.1)
				return True, selector
			except Exception:
				continue
		return False, None

	def recover_from_selector_failure(self, force_reconnect=False):
		if self._should_dispatch():
			return self._run_thread_affine(
				lambda: self.recover_from_selector_failure(force_reconnect=force_reconnect),
				timeout_seconds=12.0,
			)

		health = self.execution_guard.health_snapshot()
		execution_halted = str(health.get("execution_status") or "").upper() == "HALTED"
		if not self.selector_halted and not force_reconnect and not execution_halted:
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

	def _read_position(self, page, target_symbol=None, fallback_entry_price=None):
		target_norm = self._normalize_symbol(target_symbol)
		self._ensure_open_positions_panel(page)
		entry_price = self._first_available_price(page, [
			"[data-testid='position-entry-price']",
			"[data-testid*='entry-price']",
			"[data-testid*='open-price']",
			"[data-testid*='avg-price']",
			"[data-testid='open-position-entry-price']",
		])
		volume = self._first_available_price(page, [
			"[data-testid='position-volume']",
			"[data-testid*='position-volume']",
			"[data-testid*='open-volume']",
			"[data-testid*='quantity']",
			"[data-testid='open-position-volume']",
		])
		sl = self._first_available_price(page, [
			"[data-testid='position-sl']",
			"[data-testid*='position-sl']",
			"[data-testid*='stop-loss']",
		])
		tp = self._first_available_price(page, [
			"[data-testid='position-tp']",
			"[data-testid*='position-tp']",
			"[data-testid*='take-profit']",
		])
		symbol = self._first_visible_text(page, [
			"[data-testid='position-symbol']",
			"[data-testid*='position-symbol']",
			"[data-testid='quotation-symbol']",
			"[data-testid='instrument-symbol']",
			"[data-testid='instrument-symbol-name-wrapper']",
		])

		source = "primary"
		selected_row = None
		selected_symbol = None
		if entry_price is None:
			try:
				row = self._open_position_rows(page)
				if row is None:
					raise RuntimeError("open_position_rows_not_found")
				if row.count() > 0:
					count = int(row.count())
					for i in range(min(count, 30)):
						candidate = row.nth(i)
						cand_symbol = self._row_symbol_text(candidate)
						cand_norm = self._normalize_symbol(cand_symbol)
						if target_norm and cand_norm and self._symbol_matches(cand_norm, target_norm):
							selected_row = candidate
							selected_symbol = cand_symbol
							break
						if selected_row is None:
							selected_row = candidate
							selected_symbol = cand_symbol

					if selected_row is not None:
						if symbol is None:
							symbol = selected_symbol or symbol
						if volume is None:
							try:
								v_text = selected_row.locator("[data-testid='open-position-volume']").first.inner_text()
								volume = self._parse_price(v_text)
							except Exception:
								pass
						entry_price = self._first_available_price(page, self.selector_aliases.get("quote", []))
						source = "open_positions_row"
			except Exception:
				pass

		# Some broker layouts hide entry price in position rows. If a row exists,
		# use a safe fallback price so fill detection can still proceed.
		if entry_price is None and selected_row is not None:
			try:
				entry_price = float(fallback_entry_price) if fallback_entry_price is not None else None
			except Exception:
				entry_price = None
			if entry_price is None or entry_price <= 0.0:
				entry_price = self._first_available_price(
					page,
					[
						*self.selector_aliases.get("buy_price", []),
						*self.selector_aliases.get("sell_price", []),
						*self.selector_aliases.get("quote", []),
					],
				)
			if entry_price is not None and float(entry_price) > 0.0:
				source = "open_positions_row_fallback"

		if entry_price is None:
			return None

		return {
			"entry_price": entry_price,
			"volume": volume,
			"sl": sl,
			"tp": tp,
			"symbol": symbol,
			"source": source,
		}

	def _fill_diagnostics(self, page):
		def _count(selector):
			try:
				return int(page.locator(selector).count())
			except Exception:
				return 0

		position_selectors = {
			"open_positions_row_exact": "[data-testid='open-positions-desktop-list-row']",
			"open_positions_row_wild": "[data-testid*='open-position'][data-testid*='row']",
			"position_row": "[data-testid*='position-row']",
			"position_entry_price": "[data-testid*='entry-price']",
			"position_volume": "[data-testid*='position-volume']",
			"position_symbol": "[data-testid*='position-symbol']",
			"positions_tab": "[data-testid='open-positions-tab']",
			"confirm_button": "[data-testid='order-panel-confirm-button']",
			"overlay_backdrop": ".cdk-overlay-backdrop.cdk-overlay-backdrop-showing",
			"order_reject_banner": "[data-testid*='reject'], [data-testid*='error'], [data-testid*='notification']",
		}
		counts = {key: _count(selector) for key, selector in position_selectors.items()}

		toast_text = None
		try:
			toast_text = page.evaluate(
				"""
				() => {
				  const selectors = [
				    '[data-testid*="toast"]',
				    '[role="alert"]',
				    '.toast',
				    '.notification',
				  ];
				  for (const sel of selectors) {
				    const el = document.querySelector(sel);
				    if (el && el.textContent) return el.textContent.trim().slice(0, 300);
				  }
				  return null;
				}
				"""
			)
		except Exception:
			toast_text = None

		return {
			"position_selector_counts": counts,
			"toast": toast_text,
		}

	def _place_order(self, signal, lot_size, page):
		manual_test_mode = str(signal.get("model") or "").upper() == "MANUAL_TEST"
		require_strict_dom = str(signal.get("model") or "").upper() != "MANUAL_TEST"
		if require_strict_dom and not self._dom_stable(page):
			panel_ready = False
			for _ in range(6):
				panel = self.order_panel_snapshot()
				if panel.get("ready"):
					panel_ready = True
					break
				time.sleep(0.3)

			if panel_ready:
				self._record_selector_success()
				self.last_browser_heartbeat = int(time.time())
			elif self._attempt_reconnect() and self.page is not None and self._dom_stable(self.page):
				page = self.page
			else:
				self.emergency_halt("Broker disconnected / DOM unstable")
				return {"status": "Rejected", "reason": "DOM not stable"}

		expected_entry = signal.get("entry_price")
		expected_symbol_raw = str(signal.get("symbol") or "").strip()
		expected_symbol_norm = self._normalize_symbol(expected_symbol_raw)
		active_symbol_raw, active_symbol_norm = self._active_order_symbol(page)
		if expected_symbol_norm and active_symbol_norm and not self._symbol_matches(active_symbol_norm, expected_symbol_norm):
			switched = False
			if manual_test_mode:
				switched = self._try_switch_symbol(page, expected_symbol_raw)
				if switched:
					time.sleep(0.4)
					active_symbol_raw, active_symbol_norm = self._active_order_symbol(page)
			if not self._symbol_matches(active_symbol_norm, expected_symbol_norm):
				reason = f"Symbol mismatch (expected={expected_symbol_raw}, active={active_symbol_raw})"
				if not manual_test_mode:
					self.emergency_halt(reason)
				return {
					"status": "Rejected",
					"reason": reason,
					"expected_symbol": expected_symbol_raw,
					"active_symbol": active_symbol_raw,
					"symbol_switch_attempted": bool(manual_test_mode),
					"symbol_switched": bool(switched),
				}
		expected_sl = signal.get("sl")
		expected_tp = signal.get("tp")
		valid, message = self.execution_guard.validate_sl_tp(expected_sl, expected_tp, expected_entry)
		if not valid:
			self.emergency_halt(message)
			return {"status": "Rejected", "reason": message}

		requested_price = self._first_available_price(page, self.selector_aliases["quote"])
		if requested_price is None:
			requested_price = expected_entry

		volume_set = self._set_volume(page, lot_size)
		if not volume_set and not manual_test_mode:
			return {"status": "Rejected", "reason": "Volume selector not found"}

		protection_setup = self._configure_protection(page, signal)

		direction = signal.get("direction", "").upper()
		button_price = None
		if direction == "BUY":
			button_price = self._first_available_price(page, self.selector_aliases.get("buy_price", []))
			clicked, click_error = self._click_order_button(page, self.selector_aliases["buy"])
			if not clicked:
				return {"status": "Rejected", "reason": click_error or "Buy selector not found"}
		elif direction == "SELL":
			button_price = self._first_available_price(page, self.selector_aliases.get("sell_price", []))
			clicked, click_error = self._click_order_button(page, self.selector_aliases["sell"])
			if not clicked:
				return {"status": "Rejected", "reason": click_error or "Sell selector not found"}
		else:
			self.emergency_halt("Invalid direction")
			return {"status": "Rejected", "reason": "Invalid direction"}

		confirm_clicked, confirm_selector = self._confirm_order_if_present(page)
		submit_clicked = bool(clicked)

		fill_timeout = 15.0 if manual_test_mode else None
		filled, position_data = self.execution_guard.wait_for_fill(
			lambda: self._read_position(
				page,
				target_symbol=expected_symbol_raw,
				fallback_entry_price=(button_price if button_price is not None else expected_entry),
			),
			timeout_seconds=fill_timeout,
		)
		if not filled or not position_data:
			diagnostics = self._fill_diagnostics(page)
			if manual_test_mode:
				partial_plan = {"enabled": False, "reason": "fill_unconfirmed"}
				if submit_clicked:
					provisional_entry = button_price if button_price is not None else (expected_entry if expected_entry is not None else requested_price)
					provisional_position = {
						"symbol": active_symbol_raw or expected_symbol_raw,
						"entry_price": provisional_entry,
						"volume": float(lot_size or 0.0),
					}
					try:
						partial_plan = self._start_partial_watch(signal, provisional_position)
					except Exception as exc:
						partial_plan = {"enabled": False, "reason": f"partial_watch_error: {exc}"}
				return {
					"status": "SUBMITTED_NO_CONFIRM",
					"reason": "Fill confirmation timeout",
					"requested_price": button_price if button_price is not None else requested_price,
					"button_price": button_price,
					"submit_clicked": submit_clicked,
					"confirm_clicked": bool(confirm_clicked),
					"confirm_selector": confirm_selector,
					"active_symbol": active_symbol_raw,
					"volume_set": bool(volume_set),
					"protection_setup": protection_setup,
					"partial_plan": partial_plan,
					"diagnostics": diagnostics,
				}
			self.emergency_halt("Order timeout - no fill confirmation")
			return {"status": "Rejected", "reason": "Execution timeout", "diagnostics": diagnostics}

		executed_price = float(position_data.get("entry_price"))
		if manual_test_mode:
			return {
				"status": "EXECUTED",
				"model": signal.get("model"),
				"direction": direction,
				"lot_size": lot_size,
				"requested_price": requested_price,
				"button_price": button_price,
				"submit_clicked": submit_clicked,
				"entry_price": executed_price,
				"fill_price": executed_price,
				"position_data": position_data,
				"confirm_clicked": bool(confirm_clicked),
				"confirm_selector": confirm_selector,
				"active_symbol": active_symbol_raw,
				"volume_set": bool(volume_set),
				"verification_mode": "manual_relaxed",
				"execution_source": "PLAYWRIGHT",
				"protection_setup": protection_setup,
			}

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

		partial_plan = self._start_partial_watch(signal, position_data)

		return {
			"status": "EXECUTED",
			"model": signal.get("model"),
			"direction": direction,
			"lot_size": lot_size,
			"requested_price": requested_price,
			"button_price": button_price,
			"entry_price": executed_price,
			"slippage": slippage,
			"fill_price": executed_price,
			"position_data": position_data,
			"confirm_clicked": bool(confirm_clicked),
			"confirm_selector": confirm_selector,
			"active_symbol": active_symbol_raw,
			"volume_set": bool(volume_set),
			"execution_source": "PLAYWRIGHT",
			"protection_setup": protection_setup,
			"partial_plan": partial_plan,
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
		if self._should_dispatch():
			return self._run_thread_affine(
				lambda: self.execute(signal, lot_size, page=page),
				timeout_seconds=max(15.0, float(self.timeout_seconds or 10) + 10.0),
			)

		manual_test_mode = str((signal or {}).get("model") or "").upper() == "MANUAL_TEST"
		if not isinstance(signal, dict):
			return {"status": "Rejected", "reason": "Invalid signal payload"}

		if not manual_test_mode:
			direction = str(signal.get("direction") or "").upper().strip()
			symbol = str(signal.get("symbol") or "").upper().strip()
			if direction not in {"BUY", "SELL"}:
				return {"status": "Rejected", "reason": "Invalid signal direction"}
			if not symbol:
				return {"status": "Rejected", "reason": "Missing signal symbol"}
			if signal.get("sl") is None or signal.get("tp") is None:
				return {"status": "Rejected", "reason": "Missing SL/TP for strict execution"}

		if self.execution_guard.is_halted():
			return {"status": "Rejected", "reason": "Execution HALTED"}

		if self.force_fixed_lot and self.fixed_lot_size > 0:
			lot_size = float(self.fixed_lot_size)

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

			max_attempts = 1 if manual_test_mode else max(1, int(self.max_execution_retries) + 1)
			for attempt in range(1, max_attempts + 1):
				result = self._place_order(signal, lot_size, page)

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
			if not manual_test_mode:
				self.emergency_halt(f"Playwright crash / execution failure: {exc}")
			return {"status": "Rejected", "reason": f"Execution failed: {exc}"}
		finally:
			self.order_in_progress = False

