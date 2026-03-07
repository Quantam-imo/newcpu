import threading
import time
import re
import json
from pathlib import Path
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

		profile = {
			"updated_at": int(time.time()),
			"selectors": self.selector_aliases,
		}

		profile_file = Path("data/matchtrader_selectors.json")
		if save:
			profile_file.parent.mkdir(parents=True, exist_ok=True)
			profile_file.write_text(json.dumps(profile, indent=2), encoding="utf-8")

		return {
			"ok": True,
			"profile_file": str(profile_file),
			"discovered_keys": {k: len(v) for k, v in discovered.items()},
		}

	def _parse_price(self, text):
		cleaned = re.sub(r"[^0-9.\-]", "", str(text or "").replace(",", "").strip())
		return float(cleaned)

	def _normalize_symbol(self, value):
		text = str(value or "").upper().replace("/", "").strip()
		return re.sub(r"[^A-Z0-9]", "", text)

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

	def close_position_immediately(self, page, symbol=None, max_rows=20):
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
			rows = page.locator("[data-testid='open-positions-desktop-list-row']")
			count = min(int(rows.count()), max(1, int(max_rows)))
			for i in range(count):
				row = rows.nth(i)
				row_symbol = None
				try:
					row_symbol = str(row.locator("[data-testid='instrument-symbol-name-wrapper']").first.inner_text() or "").strip()
				except Exception:
					row_symbol = None
				if target_norm and self._normalize_symbol(row_symbol) not in {target_norm}:
					continue
				btn = row.locator("[data-testid='close-position-button']")
				if btn.count() <= 0:
					btn = row.locator("[data-testid*='close-position']")
				if btn.count() <= 0:
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

	def _read_position(self, page, target_symbol=None):
		target_norm = self._normalize_symbol(target_symbol)
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
		if entry_price is None:
			try:
				row = page.locator("[data-testid='open-positions-desktop-list-row']")
				if row.count() > 0:
					selected_row = None
					selected_symbol = None
					count = int(row.count())
					for i in range(min(count, 30)):
						candidate = row.nth(i)
						cand_symbol = None
						try:
							s_text = candidate.locator("[data-testid='instrument-symbol-name-wrapper']").first.inner_text()
							cand_symbol = str(s_text or "").strip()
						except Exception:
							cand_symbol = None
						cand_norm = self._normalize_symbol(cand_symbol)
						if target_norm and cand_norm and cand_norm == target_norm:
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
			"position_row": "[data-testid*='position-row']",
			"position_entry_price": "[data-testid*='entry-price']",
			"position_volume": "[data-testid*='position-volume']",
			"position_symbol": "[data-testid*='position-symbol']",
			"positions_tab": "[data-testid='open-positions-tab']",
			"confirm_button": "[data-testid='order-panel-confirm-button']",
			"overlay_backdrop": ".cdk-overlay-backdrop.cdk-overlay-backdrop-showing",
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
		if expected_symbol_norm and active_symbol_norm and expected_symbol_norm != active_symbol_norm:
			switched = False
			if manual_test_mode:
				switched = self._try_switch_symbol(page, expected_symbol_raw)
				if switched:
					time.sleep(0.4)
					active_symbol_raw, active_symbol_norm = self._active_order_symbol(page)
			if expected_symbol_norm != active_symbol_norm:
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

		fill_timeout = 15.0 if manual_test_mode else None
		filled, position_data = self.execution_guard.wait_for_fill(
			lambda: self._read_position(page, target_symbol=expected_symbol_raw),
			timeout_seconds=fill_timeout,
		)
		if not filled or not position_data:
			diagnostics = self._fill_diagnostics(page)
			if manual_test_mode:
				return {
					"status": "SUBMITTED_NO_CONFIRM",
					"reason": "Fill confirmation timeout",
					"requested_price": requested_price,
					"button_price": button_price,
					"confirm_clicked": bool(confirm_clicked),
					"confirm_selector": confirm_selector,
					"active_symbol": active_symbol_raw,
					"volume_set": bool(volume_set),
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
				"entry_price": executed_price,
				"fill_price": executed_price,
				"position_data": position_data,
				"confirm_clicked": bool(confirm_clicked),
				"confirm_selector": confirm_selector,
				"active_symbol": active_symbol_raw,
				"volume_set": bool(volume_set),
				"verification_mode": "manual_relaxed",
				"execution_source": "PLAYWRIGHT",
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

