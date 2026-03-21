import threading
import time
import re
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen
from astroquant.backend.execution.execution_guard import ExecutionGuard


class PlaywrightExecutionEngine:
    async def connect_to_broker(self):
        import logging
        logging.basicConfig(level=logging.INFO)
        logging.info("[Playwright] connect_to_broker called")
        """
        Launch browser, navigate to broker, and login if needed (async).
        """
        from playwright.async_api import async_playwright
        try:
            async with async_playwright() as playwright:
                logging.info("[Playwright] async_playwright context entered")
                browser = await playwright.chromium.launch(headless=True)
                logging.info("[Playwright] Browser launched (headless)")
                page = await browser.new_page()
                logging.info("[Playwright] New page created")
                broker_url = os.environ.get("EXECUTION_BROWSER_URL") or os.environ.get("BROKER_URL") or "https://your-broker-login-url.com"
                await page.goto(broker_url)
                logging.info(f"[Playwright] Navigated to {broker_url}")
                self.set_page(page)
                # Optionally, perform login here using await self.login_if_needed()
                # username = os.environ.get("BROKER_USERNAME")
                # password = os.environ.get("BROKER_PASSWORD")
                # await self.login_if_needed(username, password)
                logging.info("[Playwright] Broker connection established via Playwright (async).")
                return True
        except Exception as exc:
            logging.error(f"[Playwright] Exception in connect_to_broker: {exc}")
            raise

    def get_broker_price(self, symbol):
        """
        Switch to the symbol in the broker UI and extract the price using Playwright selectors.
        This is a scaffold; you may need to implement symbol switching logic.
        """
        page = self.page
        if page is None:
            return None
        # TODO: Implement symbol switching if needed
        # Example: page.click(f"[data-testid='symbol-selector'][data-symbol='{symbol}']")
        quote = self.broker_quote_snapshot(expected_symbols=[symbol])
        if quote and quote.get("mid") is not None:
            return quote["mid"]
        elif quote and quote.get("last") is not None:
            return quote["last"]
        return None

    def execution_health(self):
        # Stub: Always return healthy status for now
        return {"execution_status": "OK", "healthy": True}

    def set_page(self, page):
        """Set the current Playwright page object."""
        self._page = page
        self.page = page

    def set_reconnect_handler(self, handler):
        self._reconnect_handler = handler

    def set_task_dispatcher(self, dispatcher):
        self._task_dispatcher = dispatcher

    def __init__(
            self,
            headless=None,
            timeout_ms=None,
            user_data_dir=None,
            cdp_url=None):
        import os
        # Force headless mode by default for all environments
        self.headless = True if headless is None else headless
        self.timeout_ms = timeout_ms if timeout_ms is not None else int(os.environ.get("EXECUTION_BROWSER_TIMEOUT_MS", 10000))
        self.user_data_dir = user_data_dir if user_data_dir is not None else os.environ.get("EXECUTION_BROWSER_USER_DATA_DIR")
        self.cdp_url = cdp_url if cdp_url is not None else os.environ.get("EXECUTION_BROWSER_CDP_URL")
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
            # Add other selectors as needed...
        }
        self.selector_aliases.update({
            "login_username": ["[data-testid='login-username']"],
            "login_password": ["[data-testid='login-password']"],
            "login_submit": ["[data-testid='login-submit']"],
        })
        self.selector_failure_count = 0
        self.selector_failure_limit = 5
        self.selector_halted = False
        self.last_selector_failure_reason = None
        self.reconnect_attempts = 0
        self.last_reconnect_attempt = None
        self.last_browser_heartbeat = None
        self.selector_profile_loaded = False
        self.selector_profile_updated_at = None
        self.partial_watchers = {}
        self.partial_watch_lock = threading.Lock()
        self.execution_guard = ExecutionGuard()
        self.fill_tolerance = 0.1
        self.reconnect_cooldown_seconds = 5.0
        self.last_error = None
        self.page = None
        self.reconnect_handler = None
        self._page = None
        self._reconnect_handler = None
        self._record_selector_failure("Initialization complete.")

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
            if self._has_any_selector(
                page, self.selector_aliases.get(
                    "order_panel", [])):
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

    def _execution_surface_ready(self, page):
        try:
            if self._has_any_selector(
                page, self.selector_aliases.get(
                    "order_panel", [])):
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
                lambda: self.login_if_needed(
                    username=username,
                    password=password),
                timeout_seconds=12.0,
            )

        page = self.page
        if page is None:
            if not self._attempt_reconnect():
                return {"ok": False, "status": "not_connected"}
            page = self.page

        if self._execution_surface_ready(page):
            return {"ok": True, "status": "already_authenticated"}

        login_user_present = self._has_any_selector(
            page, self.selector_aliases.get("login_username", []))
        login_pass_present = self._has_any_selector(
            page, self.selector_aliases.get("login_password", []))
        if not (login_user_present and login_pass_present):
            return {"ok": False, "status": "login_form_not_detected"}

        if not username or not password:
            return {"ok": False, "status": "credentials_missing"}

        user_ok = self._set_text_input(
            page, self.selector_aliases.get(
                "login_username", []), username)
        pass_ok = self._set_text_input(
            page, self.selector_aliases.get(
                "login_password", []), password)
        clicked, click_err = self._click_order_button(
            page, self.selector_aliases.get("login_submit", []))

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
            self.execution_guard.halt(
                f"Selector failure threshold reached: {reason}")

    def _record_selector_success(self):

        if self.selector_failure_count > 0:
            self.selector_failure_count = 0
        self.selector_halted = False
        self.last_selector_failure_reason = None

    def _attempt_reconnect(self):

        now = time.time()
        if self.reconnect_handler is None:
            return False
        if (now - float(self.last_reconnect_attempt or 0.0)
            ) < float(self.reconnect_cooldown_seconds):
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
            return self._run_thread_affine(
                self.broker_positions_snapshot, timeout_seconds=4.0)

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
            return self._run_thread_affine(
                self.broker_equity_snapshot, timeout_seconds=4.0)

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
                lambda: self.broker_quote_snapshot(
                    expected_symbols=expected_symbols), timeout_seconds=4.0, )

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
            # Avoid hard-halting here; execution paths still enforce strict
            # selector checks.
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
            expected = {str(s or "").upper().replace("/", "")
                        for s in expected_symbols if str(s or "").strip()}
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
            return self._run_thread_affine(
                self.order_panel_snapshot, timeout_seconds=4.0)

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

        buy_price = self._first_available_price(
            page, self.selector_aliases.get("buy_price", []))
        sell_price = self._first_available_price(
            page, self.selector_aliases.get("sell_price", []))

        ready = bool(
            panel_exists and buy_exists and sell_exists and volume_exists)
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
            return self._run_thread_affine(
                lambda: self.calibrate_selectors(
                    save=save), timeout_seconds=20.0)

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
            profile_file.write_text(
                json.dumps(
                    profile,
                    indent=2),
                encoding="utf-8")
            self.selector_profile_loaded = True
            self.selector_profile_updated_at = profile.get("updated_at")

        return {
            "ok": True,
            "profile_file": str(profile_file),
            "discovered_keys": {k: len(v) for k, v in discovered.items()},
            "profile_loaded": bool(self.selector_profile_loaded),
        }

    def _parse_price(self, text):
        cleaned = re.sub(r"[^0-9.\-]", "",
                         str(text or "").replace(",", "").strip())
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
            labels = page.locator(
                "[data-testid='instrument-symbol-name-wrapper']")
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
            return self._run_thread_affine(lambda: self.discover_broker_symbols(
                page, limit=limit, include_quotes=include_quotes), timeout_seconds=15.0, )

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
                r"""
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
            canonical = self._normalize_symbol(
                (row or {}).get("canonical") or raw)
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
                    # Detached/animating nodes can intermittently fail
                    # visibility checks.
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
            page.wait_for_selector(
                "[data-testid='open-positions-tab']", timeout=5000)
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

    def _select_position_row(self, page, symbol=None, max_rows=25):
        target_norm = self._normalize_symbol(symbol)
        try:
            rows = self._open_position_rows(page)
            if rows is None:
                return None, None
            count = min(int(rows.count()), max(1, int(max_rows)))
        except Exception:
            return None, None

        fallback_row = None
        fallback_symbol = None
        for i in range(count):
            row = rows.nth(i)
            row_symbol = self._row_symbol_text(row)
            if fallback_row is None:
                fallback_row = row
                fallback_symbol = row_symbol
            if target_norm and not self._symbol_matches(
                    row_symbol, target_norm):
                continue
            return row, row_symbol

        if target_norm and count == 1 and fallback_row is not None:
            return fallback_row, fallback_symbol
        if not target_norm:
            return fallback_row, fallback_symbol
        return None, None

    def _open_position_modify_editor(self, page, symbol=None):
        row, row_symbol = self._select_position_row(
            page, symbol=symbol, max_rows=30)
        if row is None:
            return {
                "opened": False,
                "reason": "position_row_not_found",
                "symbol": symbol}

        try:
            row.scroll_into_view_if_needed(timeout=1200)
        except Exception:
            pass

        # First click the row; some brokers expand inline editors/details on
        # row click.
        try:
            row.click(timeout=1200)
        except Exception:
            try:
                row.click(timeout=1200, force=True)
            except Exception:
                pass
        time.sleep(0.12)

        for selector in self.selector_aliases.get("position_modify", []):
            try:
                candidate = row.locator(selector)
                if candidate.count() > 0:
                    try:
                        candidate.first.click(timeout=1200)
                    except Exception:
                        candidate.first.click(timeout=1200, force=True)
                    time.sleep(0.15)
                    return {
                        "opened": True,
                        "symbol": row_symbol,
                        "source": "row_button",
                        "selector": selector}
            except Exception:
                continue

        for selector in self.selector_aliases.get("position_modify", []):
            try:
                candidate = page.locator(selector)
                if candidate.count() > 0:
                    try:
                        candidate.first.click(timeout=1200)
                    except Exception:
                        candidate.first.click(timeout=1200, force=True)
                    time.sleep(0.15)
                    return {
                        "opened": True,
                        "symbol": row_symbol,
                        "source": "page_button",
                        "selector": selector}
            except Exception:
                continue

        # Last resort: JS-click likely edit controls inside the row or its
        # nearest toolbar/details area.
        try:
            clicked = bool(row.evaluate(
                """
                (el) => {
                  const scopes = [el, el.closest('[data-testid*="row"]') || el, el.parentElement || el];
                  const hints = ['edit', 'modify', 'update', 'protection', 'stop', 'risk'];
                  for (const scope of scopes) {
                    if (!scope) continue;
                    const nodes = scope.querySelectorAll('button,[role="button"],[data-testid],[class]');
                    for (const node of nodes) {
                      const text = String(node.textContent || '').toLowerCase();
                      const testid = String(node.getAttribute('data-testid') || '').toLowerCase();
                      const cls = String(node.className || '').toLowerCase();
                      if (hints.some(h => text.includes(h) || testid.includes(h) || cls.includes(h))) {
                        try { node.click(); return true; } catch(e) {}
                      }
                    }
                  }
                  return false;
                }
                """
            ))
            if clicked:
                time.sleep(0.15)
                return {
                    "opened": True,
                    "symbol": row_symbol,
                    "source": "row_js_click",
                    "selector": "heuristic"}
        except Exception:
            pass

        return {
            "opened": True,
            "symbol": row_symbol,
            "source": "row_click_only",
            "selector": None}

    def close_position_immediately(self, page, symbol=None, max_rows=20):
        if self._should_dispatch():
            return self._run_thread_affine(lambda: self.close_position_immediately(
                page, symbol=symbol, max_rows=max_rows), timeout_seconds=12.0, )

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
                if target_norm and not self._symbol_matches(
                        row_symbol, target_norm):
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
            return filled_size < (
                float(expected_lot_size) *
                self.fill_tolerance)
        except Exception:
            return False

    def close_position_fraction(self, page, symbol=None, fraction=0.5):
        if self._should_dispatch():
            return self._run_thread_affine(lambda: self.close_position_fraction(
                page, symbol=symbol, fraction=fraction), timeout_seconds=15.0, )

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
            if target_norm and not self._symbol_matches(
                    row_symbol, target_norm):
                continue
            selected = row
            selected_symbol = row_symbol
            try:
                v_text = selected.locator(
                    "[data-testid='open-position-volume']").first.inner_text()
                selected_volume = float(self._parse_price(v_text))
            except Exception:
                selected_volume = None
            break

        if selected is None:
            # Brokers may expose BTC symbols with slight naming variants (BTC/BTCUSD/BTCUSDT).
            # If only one row is open, use it as a safe fallback for partial
            # close automation.
            if target_norm and count == 1 and fallback_row is not None:
                selected = fallback_row
                selected_symbol = fallback_symbol
            else:
                return {
                    "ok": False,
                    "reason": "symbol_not_found",
                    "symbol": symbol}

        btn = selected.locator("[data-testid='close-position-button']")
        if btn.count() <= 0:
            btn = selected.locator("[data-testid*='close-position']")
        if btn.count() <= 0:
            btn = selected.locator("button:has-text('Close Position')")
        if btn.count() <= 0:
            btn = selected.locator("button:has-text('Close')")
        if btn.count() <= 0:
            return {
                "ok": False,
                "reason": "close_button_not_found",
                "symbol": selected_symbol}

        try:
            btn.first.click(timeout=1200)
        except Exception:
            try:
                btn.first.click(timeout=1200, force=True)
            except Exception as exc:
                return {
                    "ok": False,
                    "reason": f"close_click_failed: {exc}",
                    "symbol": selected_symbol}

        if selected_volume is None:
            selected_volume = 0.0
        close_volume = max(0.01, round(float(selected_volume) * fraction, 2))
        if selected_volume > 0:
            close_volume = min(
                close_volume, max(
                    0.01, round(
                        selected_volume - 0.01, 2)))

        volume_set = self._set_price_input(
            page, self.selector_aliases.get(
                "close_partial_volume", []), close_volume)
        if not volume_set:
            self._dismiss_overlay_backdrop(page)
            return {
                "ok": False,
                "reason": "partial_volume_input_not_found",
                "symbol": selected_symbol,
                "requested_close_volume": close_volume,
            }

        clicked, err = self._click_order_button(
            page, self.selector_aliases.get(
                "close_partial_confirm", []))
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

        symbol = str(position_data.get("symbol")
                     or signal.get("symbol") or "").strip()
        direction = str(signal.get("direction") or "").upper().strip()
        entry = float(position_data.get("entry_price")
                      or signal.get("entry_price") or 0.0)
        sl = signal.get("sl")
        ratio = max(0.1, min(0.9, float(partial_cfg.get("ratio") or 0.5)))
        rr = max(0.2, min(5.0, float(partial_cfg.get("target_rr") or 1.0)))
        ttl_seconds = max(
            60, min(8 * 3600, int(partial_cfg.get("ttl_seconds") or 3 * 3600)))

        if not symbol or direction not in {
                "BUY", "SELL"} or entry <= 0.0 or sl is None:
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
                quote = self.broker_quote_snapshot(
                    expected_symbols=[symbol]) or {}
                price = quote.get("mid") or quote.get(
                    "last") or quote.get("bid") or quote.get("ask")
                if price is None:
                    time.sleep(1.0)
                    continue

                reached = (
                    float(price) >= float(target_price)) if direction == "BUY" else (
                    float(price) <= float(target_price))
                if not reached:
                    time.sleep(1.0)
                    continue

                result = self.close_position_fraction(
                    self.page, symbol=symbol, fraction=ratio)
                job["triggered"] = True
                job["trigger_price"] = float(price)
                job["result"] = result
                with self.partial_watch_lock:
                    if self.partial_watchers.get(key) is job:
                        self.partial_watchers.pop(key, None)
                return

            with self.partial_watch_lock:
                if self.partial_watchers.get(key) is job:
                    job["result"] = {
                        "ok": False, "reason": "partial_watch_timeout"}
                    self.partial_watchers.pop(key, None)

        thread = threading.Thread(
            target=_worker, daemon=True, name=f"aq-partial-{key[:8]}")
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

                # Step 0: Force-remove disabled/readonly via JS before anything else.
                # Angular/React inputs are often disabled until their toggle is switched;
                # we remove the constraint at the DOM level so Playwright can
                # interact.
                try:
                    field.evaluate(
                        """
                        (el) => {
                          const t = el.matches('input,textarea,[contenteditable="true"]') ? el
                            : el.querySelector('input,textarea,[contenteditable="true"]') || el;
                          if (t.disabled)  { t.removeAttribute('disabled');  t.disabled  = false; }
                          if (t.readOnly)  { t.removeAttribute('readonly');  t.readOnly  = false; }
                          const wrapper = t.closest('.trade-open-position-tp-sl-edit__disabled, .ui-checkbox--disabled, .trade-tp-sl-values.trade-open-position-tp-sl-edit__disabled');
                          if (wrapper) wrapper.classList.remove('trade-open-position-tp-sl-edit__disabled');
                          const saveBtn = document.querySelector("[data-testid='position-edit-dialog-save-btn']");
                          if (saveBtn) {
                            saveBtn.removeAttribute('disabled');
                            saveBtn.disabled = false;
                          }
                        }
                        """
                    )
                except Exception:
                    pass

                # Step 1: keyboard approach (most reliable for Angular-style
                # validation)
                try:
                    field.click(timeout=1500)
                    time.sleep(0.05)
                    page.keyboard.press("Control+A")
                    page.keyboard.type(value_text, delay=10)
                    page.keyboard.press("Tab")
                    time.sleep(0.08)
                    return True
                except Exception:
                    pass

                # Step 2: Playwright fill
                try:
                    field.fill(value_text, timeout=1500)
                    time.sleep(0.08)
                    return True
                except Exception:
                    pass

                # Step 3: React/Angular nativeInputValueSetter with full event
                # chain
                try:
                    result = field.evaluate(
                        """
                        (el, value) => {
                          const target = el.matches('input,textarea,[contenteditable="true"]')
                            ? el
                            : el.querySelector('input,textarea,[contenteditable="true"]') || el;
                          if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return false;
                          if (target.disabled)  { target.removeAttribute('disabled');  target.disabled  = false; }
                          if (target.readOnly)  { target.removeAttribute('readonly');  target.readOnly  = false; }
                          target.focus();
                          try {
                            const nativeSetter = Object.getOwnPropertyDescriptor(
                              window.HTMLInputElement.prototype, 'value'
                            ).set;
                            nativeSetter.call(target, String(value));
                          } catch(e) {
                            target.value = String(value);
                          }
                          target.dispatchEvent(new Event('input',   { bubbles: true }));
                          target.dispatchEvent(new Event('change',  { bubbles: true }));
                          target.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
                          target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
                          target.dispatchEvent(new KeyboardEvent('keyup',   { key: 'Tab', bubbles: true }));
                          return true;
                        }
                        """,
                        value_text,
                    )
                    time.sleep(0.08)
                    if result:
                        return True
                except Exception:
                    pass
            except Exception:
                continue
        return False

    # Candidate selectors for the SL / TP section toggle / expand button in MatchTrader-style UIs.
    # Clicking these reveals the collapsed SL/TP input row before we try to
    # fill it.
    _SL_TOGGLE_SELECTORS = [
        "[data-testid='mw-order-panel'] [data-testid*='stop-loss'] [data-testid*='toggle']",
        "[data-testid='mw-order-panel'] [data-testid*='stop-loss']:not(input)",
        "[data-testid*='stop-loss-toggle']",
        "[data-testid*='sl-toggle']",
        "label[for*='stopLoss']",
        "label[for*='stop-loss']",
        "[data-testid='mw-order-panel'] .stop-loss-label",
    ]
    _TP_TOGGLE_SELECTORS = [
        "[data-testid='mw-order-panel'] [data-testid*='take-profit'] [data-testid*='toggle']",
        "[data-testid='mw-order-panel'] [data-testid*='take-profit']:not(input)",
        "[data-testid*='take-profit-toggle']",
        "[data-testid*='tp-toggle']",
        "label[for*='takeProfit']",
        "label[for*='take-profit']",
        "[data-testid='mw-order-panel'] .take-profit-label",
    ]

    def _try_reveal_sl_tp_inputs(self, page):
        """Expand/enable SL and TP input sections in the order panel.

        MatchTrader/Angular UIs gate SL/TP inputs behind a toggle switch. This method
        finds those toggles by walking the DOM upward from any disabled SL/TP input
        and clicking all toggles/checkboxes/switches found in the ancestor chain.
        """
        # Maven layout exposes SL/TP under an "Advanced Order" button.
        for sel in self.selector_aliases.get("advanced_order_toggle", []):
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        loc.first.click(timeout=1000)
                    except Exception:
                        loc.first.click(timeout=1000, force=True)
                    time.sleep(0.2)
                    break
            except Exception:
                continue

        for sel in self.selector_aliases.get("stop_loss_toggle", []):
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        loc.first.click(timeout=1000)
                    except Exception:
                        loc.first.click(timeout=1000, force=True)
                    time.sleep(0.15)
                    break
            except Exception:
                continue

        for sel in self.selector_aliases.get("take_profit_toggle", []):
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        loc.first.click(timeout=1000)
                    except Exception:
                        loc.first.click(timeout=1000, force=True)
                    time.sleep(0.15)
                    break
            except Exception:
                continue

        # JS-based approach: walk up from each disabled SL/TP input and click
        # toggles
        try:
            page.evaluate(
                """
                () => {
                  const panel = document.querySelector("[data-testid='mw-order-panel']") || document.body;
                  const inputSelectors = [
                    "[data-testid*='stop-loss'] input",
                    "[data-testid*='take-profit'] input",
                    "input[name*='stopLoss']", "input[name*='stop_loss']",
                    "input[name*='takeProfit']", "input[name*='take_profit']",
                    "input[placeholder*='SL']", "input[placeholder*='TP']",
                    "input[placeholder*='Stop']", "input[placeholder*='Take']",
                  ];
                  function tryEnableInput(inp) {
                    // Walk up to 6 levels looking for a toggle/checkbox/switch/label
                    let parent = inp.parentElement;
                    for (let i = 0; i < 6 && parent && parent !== document.body; i++) {
                      const toggles = parent.querySelectorAll(
                        'mat-slide-toggle, mat-checkbox, [role="switch"], [role="checkbox"], ' +
                        'input[type="checkbox"], [class*="toggle"], [class*="switch"], ' +
                        '[data-testid*="toggle"], [data-testid*="switch"], [data-testid*="enable"]'
                      );
                      for (const t of toggles) {
                        if (t !== inp) { try { t.click(); } catch(e) {} }
                      }
                      parent = parent.parentElement;
                    }
                  }
                  for (const sel of inputSelectors) {
                    const inputs = panel.querySelectorAll(sel);
                    for (const inp of inputs) { tryEnableInput(inp); }
                  }
                }
                """
            )
            time.sleep(0.2)
        except Exception:
            pass
        # Fallback: direct Playwright selector clicks on known toggle patterns
        for sel in self._SL_TOGGLE_SELECTORS:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    loc.first.click(timeout=800, force=True)
                    time.sleep(0.12)
                    break
            except Exception:
                continue
        for sel in self._TP_TOGGLE_SELECTORS:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    loc.first.click(timeout=800, force=True)
                    time.sleep(0.12)
                    break
            except Exception:
                continue

    def _configure_protection(self, page, signal):
        sl = signal.get("sl")
        tp = signal.get("tp")
        if sl is None and tp is None:
            return {
                "sl_requested": None,
                "tp_requested": None,
                "sl_available": False,
                "tp_available": False,
                "sl_set": False,
                "tp_set": False,
            }

        sl_inputs_available = False
        tp_inputs_available = False
        for sel in self.selector_aliases.get("stop_loss_input", []):
            try:
                if page.locator(sel).count() > 0:
                    sl_inputs_available = True
                    break
            except Exception:
                continue
        for sel in self.selector_aliases.get("take_profit_input", []):
            try:
                if page.locator(sel).count() > 0:
                    tp_inputs_available = True
                    break
            except Exception:
                continue

        # Attempt to reveal collapsed SL/TP sections before filling
        self._try_reveal_sl_tp_inputs(page)
        time.sleep(0.15)
        sl_set = self._set_price_input(page, self.selector_aliases.get(
            "stop_loss_input", []), sl) if sl is not None else False
        tp_set = self._set_price_input(page, self.selector_aliases.get(
            "take_profit_input", []), tp) if tp is not None else False
        # Retry once if either failed — toggling may have just finished
        # animating
        if sl is not None and not sl_set:
            time.sleep(0.2)
            sl_set = self._set_price_input(
                page, self.selector_aliases.get(
                    "stop_loss_input", []), sl)
        if tp is not None and not tp_set:
            time.sleep(0.2)
            tp_set = self._set_price_input(
                page, self.selector_aliases.get(
                    "take_profit_input", []), tp)
        return {
            "sl_requested": sl,
            "tp_requested": tp,
            "sl_available": bool(sl_inputs_available),
            "tp_available": bool(tp_inputs_available),
            "sl_set": bool(sl_set),
            "tp_set": bool(tp_set),
        }

    def _configure_protection_after_fill(
            self, page, signal, target_symbol=None):
        """Attempt SL/TP apply from open-position context when order panel has no inputs."""
        sl = signal.get("sl")
        tp = signal.get("tp")
        if sl is None and tp is None:
            return {
                "sl_requested": None,
                "tp_requested": None,
                "sl_available": False,
                "tp_available": False,
                "sl_set": False,
                "tp_set": False,
                "source": "post_fill",
            }

        try:
            self._ensure_open_positions_panel(page)
        except Exception:
            pass

        modify_result = self._open_position_modify_editor(
            page, symbol=target_symbol)

        self._try_reveal_sl_tp_inputs(page)
        time.sleep(0.12)

        fallback_sl_selectors = [
            *self.selector_aliases.get("position_stop_loss_input", []),
            *self.selector_aliases.get("stop_loss_input", []),
        ]
        fallback_tp_selectors = [
            *self.selector_aliases.get("position_take_profit_input", []),
            *self.selector_aliases.get("take_profit_input", []),
        ]

        def _selector_available(selectors):
            for sel in selectors:
                try:
                    if page.locator(sel).count() > 0:
                        return True
                except Exception:
                    continue
            return False

        sl_available = _selector_available(fallback_sl_selectors)
        tp_available = _selector_available(fallback_tp_selectors)

        sl_set = self._set_price_input(
            page,
            fallback_sl_selectors,
            sl) if sl is not None else False
        tp_set = self._set_price_input(
            page,
            fallback_tp_selectors,
            tp) if tp is not None else False
        if sl is not None and not sl_set:
            time.sleep(0.15)
            sl_set = self._set_price_input(page, fallback_sl_selectors, sl)
        if tp is not None and not tp_set:
            time.sleep(0.15)
            tp_set = self._set_price_input(page, fallback_tp_selectors, tp)

        save_clicked = False
        save_selector = None
        if (sl_set or tp_set) and self.selector_aliases.get("position_save"):
            clicked, err = self._click_order_button(
                page, self.selector_aliases.get("position_save", []))
            save_clicked = bool(clicked)
            save_selector = None if not clicked else "position_save"
            if not clicked:
                try:
                    self._confirm_order_if_present(page)
                except Exception:
                    pass
        else:
            try:
                self._confirm_order_if_present(page)
            except Exception:
                pass

        time.sleep(0.2)
        verified_position = None
        try:
            verified_position = self._read_position(
                page, target_symbol=target_symbol)
        except Exception:
            verified_position = None

        verified_sl = (
            verified_position or {}).get("sl") if isinstance(
            verified_position, dict) else None
        verified_tp = (
            verified_position or {}).get("tp") if isinstance(
            verified_position, dict) else None
        if sl is not None and verified_sl is not None:
            try:
                if abs(float(verified_sl) - float(sl)) <= max(0.5,
                                                              abs(float(sl)) * 0.0002):
                    sl_set = True
            except Exception:
                pass
        if tp is not None and verified_tp is not None:
            try:
                if abs(float(verified_tp) - float(tp)) <= max(0.5,
                                                              abs(float(tp)) * 0.0002):
                    tp_set = True
            except Exception:
                pass

        return {
            "sl_requested": sl,
            "tp_requested": tp,
            "sl_available": bool(sl_available),
            "tp_available": bool(tp_available),
            "sl_set": bool(sl_set),
            "tp_set": bool(tp_set),
            "source": "post_fill",
            "modify_result": modify_result,
            "save_clicked": bool(save_clicked),
            "save_selector": save_selector,
            "verified_position": verified_position,
        }

    def _dismiss_overlay_backdrop(self, page):
        dismissed = False
        try:
            backdrop = page.locator(
                ".cdk-overlay-backdrop.cdk-overlay-backdrop-showing")
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
        # Handle overlay confirmation dialogs that require checkbox consent
        # first.
        for checkbox_selector in self.selector_aliases.get(
                "confirm_checkbox", []):
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
                lambda: self.recover_from_selector_failure(
                    force_reconnect=force_reconnect), timeout_seconds=12.0, )

        health = self.execution_guard.health_snapshot()
        execution_halted = str(
            health.get("execution_status") or "").upper() == "HALTED"
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
        quote_ok = self._first_available_price(
            page, self.selector_aliases["quote"]) is not None
        if dom_ok or quote_ok:
            self.execution_guard.reset()
            self._record_selector_success()
            self.last_error = None
            return {
                "ok": True,
                "reason": "Recovered",
                "dom_ok": dom_ok,
                "quote_ok": quote_ok}

        return {
            "ok": False,
            "reason": "Selectors still unavailable",
            "dom_ok": dom_ok,
            "quote_ok": quote_ok}

    def _read_position(
            self,
            page,
            target_symbol=None,
            fallback_entry_price=None):
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
            "[data-testid='open-position-symbol']",
        ])

        # Extract profit value
        profit = None
        try:
            profit = self._get_open_position_profit(page)
        except Exception:
            profit = None

        source = "primary"
        selected_row = None
        selected_symbol = None
        target_matched = False
        if entry_price is None or target_norm:
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
                        if target_norm and cand_norm and self._symbol_matches(
                                cand_norm, target_norm):
                            selected_row = candidate
                            selected_symbol = cand_symbol
                            target_matched = True
                            break
                        if not target_norm and selected_row is None:
                            selected_row = candidate
                            selected_symbol = cand_symbol

                    if selected_row is not None:
                        if selected_symbol:
                            symbol = selected_symbol
                        if volume is None:
                            try:
                                v_text = selected_row.locator(
                                    "[data-testid='open-position-volume']").first.inner_text()
                                volume = self._parse_price(v_text)
                            except Exception:
                                pass
                        if entry_price is None:
                            entry_price = self._first_available_price(
                                page, self.selector_aliases.get("quote", []))
                        source = "open_positions_row"
            except Exception:
                pass

        if target_norm:
            current_symbol_norm = self._normalize_symbol(symbol)
            if current_symbol_norm and self._symbol_matches(
                    current_symbol_norm, target_norm):
                target_matched = True
            if source.startswith("open_positions_row") and not target_matched:
                return None

        # Some broker layouts hide entry price in position rows. If a row exists,
        # use a safe fallback price so fill detection can still proceed.
        if entry_price is None and selected_row is not None:
            try:
                entry_price = float(
                    fallback_entry_price) if fallback_entry_price is not None else None
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
            "profit": profit,
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
        counts = {key: _count(selector)
                  for key, selector in position_selectors.items()}

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
        manual_test_mode = str(
            signal.get("model") or "").upper() == "MANUAL_TEST"
        require_strict_dom = str(
            signal.get("model") or "").upper() != "MANUAL_TEST"
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
        if expected_symbol_norm and active_symbol_norm and not self._symbol_matches(
                active_symbol_norm, expected_symbol_norm):
            switched = False
            if manual_test_mode:
                switched = self._try_switch_symbol(page, expected_symbol_raw)
                if switched:
                    time.sleep(0.4)
                    active_symbol_raw, active_symbol_norm = self._active_order_symbol(
                        page)
            if not self._symbol_matches(
                    active_symbol_norm,
                    expected_symbol_norm):
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
        direction = str(signal.get("direction", "")).upper()
        manual_levels_realigned = False
        if manual_test_mode and direction in {"BUY", "SELL"}:
            pre_button_price = self._first_available_price(
                page, self.selector_aliases.get(
                    "buy_price", []) if direction == "BUY" else self.selector_aliases.get(
                    "sell_price", []), )
            if pre_button_price is not None and expected_entry is not None:
                try:
                    entry_val = float(expected_entry)
                    button_val = float(pre_button_price)
                    if entry_val > 0.0 and button_val > 0.0:
                        scale_ratio = max(entry_val, button_val) / \
                            max(min(entry_val, button_val), 1e-9)
                        if scale_ratio >= 10.0:
                            risk_distance = abs(
                                float(expected_entry) -
                                float(expected_sl)) if expected_sl is not None else None
                            reward_distance = abs(
                                float(expected_tp) -
                                float(expected_entry)) if expected_tp is not None else None

                            expected_entry = float(button_val)
                            signal["entry_price"] = expected_entry

                            if risk_distance is not None and risk_distance > 0.0:
                                expected_sl = expected_entry - \
                                    risk_distance if direction == "BUY" else expected_entry + risk_distance
                                signal["sl"] = expected_sl
                            if reward_distance is not None and reward_distance > 0.0:
                                expected_tp = expected_entry + \
                                    reward_distance if direction == "BUY" else expected_entry - reward_distance
                                signal["tp"] = expected_tp

                            manual_levels_realigned = True
                except Exception:
                    pass

        valid, message = self.execution_guard.validate_sl_tp(
            expected_sl, expected_tp, expected_entry)
        if not valid:
            self.emergency_halt(message)
            return {"status": "Rejected", "reason": message}

        requested_price = self._first_available_price(
            page, self.selector_aliases["quote"])
        if requested_price is None:
            requested_price = expected_entry

        baseline_position = None
        if manual_test_mode:
            try:
                baseline_position = self._read_position(
                    page, target_symbol=expected_symbol_raw)
            except Exception:
                baseline_position = None

        volume_set = self._set_volume(page, lot_size)
        if not volume_set and not manual_test_mode:
            return {
                "status": "Rejected",
                "reason": "Volume selector not found"}

        protection_setup = self._configure_protection(page, signal)
        requested_protection = bool(
            expected_sl is not None or expected_tp is not None)

        # Hard gate for live safety: if SL/TP controls are not present in current DOM,
        # do not submit any order that requested protection.
        if requested_protection and self.require_protection_controls:
            sl_missing_controls = bool(
                expected_sl is not None and not bool(
                    (protection_setup or {}).get("sl_available")))
            tp_missing_controls = bool(
                expected_tp is not None and not bool(
                    (protection_setup or {}).get("tp_available")))
            if sl_missing_controls or tp_missing_controls:
                return {
                    "status": "Rejected",
                    "reason": "Protection controls unavailable on panel; order blocked before submit",
                    "active_symbol": active_symbol_raw,
                    "volume_set": bool(volume_set),
                    "protection_setup": protection_setup,
                    "protection_required": True,
                    "safety_gate": "pre_submit_protection_controls",
                }

        button_price = None
        if direction == "BUY":
            button_price = self._first_available_price(
                page, self.selector_aliases.get("buy_price", []))
            clicked, click_error = self._click_order_button(
                page, self.selector_aliases["buy"])
            if not clicked:
                return {
                    "status": "Rejected",
                    "reason": click_error or "Buy selector not found"}
        elif direction == "SELL":
            button_price = self._first_available_price(
                page, self.selector_aliases.get("sell_price", []))
            clicked, click_error = self._click_order_button(
                page, self.selector_aliases["sell"])
            if not clicked:
                return {
                    "status": "Rejected",
                    "reason": click_error or "Sell selector not found"}
        else:
            self.emergency_halt("Invalid direction")
            return {"status": "Rejected", "reason": "Invalid direction"}

        confirm_clicked, confirm_selector = self._confirm_order_if_present(
            page)
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
                    provisional_entry = button_price if button_price is not None else (
                        expected_entry if expected_entry is not None else requested_price)
                    provisional_position = {
                        "symbol": active_symbol_raw or expected_symbol_raw,
                        "entry_price": provisional_entry,
                        "volume": float(lot_size or 0.0),
                    }
                    try:
                        partial_plan = self._start_partial_watch(
                            signal, provisional_position)
                    except Exception as exc:
                        partial_plan = {
                            "enabled": False,
                            "reason": f"partial_watch_error: {exc}"}
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
                    "manual_levels_realigned": bool(manual_levels_realigned),
                    "protection_setup": protection_setup,
                    "partial_plan": partial_plan,
                    "diagnostics": diagnostics,
                }
            self.emergency_halt("Order timeout - no fill confirmation")
            return {
                "status": "Rejected",
                "reason": "Execution timeout",
                "diagnostics": diagnostics}

        executed_price = float(position_data.get("entry_price"))

        # After fill, make one more attempt from position context in case broker only
        # exposes SL/TP editors post-submit.
        if requested_protection and (
            (expected_sl is not None and not bool(
                (protection_setup or {}).get("sl_set"))) or (
                expected_tp is not None and not bool(
                (protection_setup or {}).get("tp_set")))):
            post_fill_protection = self._configure_protection_after_fill(
                page,
                signal,
                target_symbol=expected_symbol_raw,
            )
            protection_setup = {
                **(
                    protection_setup or {}), "post_fill": post_fill_protection, "sl_set": bool(
                    (protection_setup or {}).get("sl_set")) or bool(
                    (post_fill_protection or {}).get("sl_set")), "tp_set": bool(
                    (protection_setup or {}).get("tp_set")) or bool(
                        (post_fill_protection or {}).get("tp_set")), "sl_available": bool(
                            (protection_setup or {}).get("sl_available")) or bool(
                                (post_fill_protection or {}).get("sl_available")), "tp_available": bool(
                                    (protection_setup or {}).get("tp_available")) or bool(
                                        (post_fill_protection or {}).get("tp_available")), }

        protection_set_ok = (
            (expected_sl is None or bool(
                (protection_setup or {}).get("sl_set"))) and (
                expected_tp is None or bool(
                    (protection_setup or {}).get("tp_set"))))
        protection_available_ok = (
            (expected_sl is None or bool(
                (protection_setup or {}).get("sl_available"))) and (
                expected_tp is None or bool(
                    (protection_setup or {}).get("tp_available"))))

        if requested_protection and (not protection_set_ok or (
                self.require_protection_controls and not protection_available_ok)):
            auto_closed = False
            try:
                auto_closed = bool(
                    self.close_position_immediately(
                        page, symbol=expected_symbol_raw, max_rows=30))
            except Exception:
                auto_closed = False
            time.sleep(0.2)
            diagnostics = self._fill_diagnostics(page)
            if not manual_test_mode:
                self.emergency_halt("Protection not set after execution")
            return {
                "status": "Rejected",
                "reason": "Protection not set after execution; position auto-closed for safety",
                "requested_price": button_price if button_price is not None else requested_price,
                "button_price": button_price,
                "submit_clicked": submit_clicked,
                "confirm_clicked": bool(confirm_clicked),
                "confirm_selector": confirm_selector,
                "active_symbol": active_symbol_raw,
                "volume_set": bool(volume_set),
                "protection_setup": protection_setup,
                "position_data": position_data,
                "auto_close_attempted": True,
                "auto_closed": bool(auto_closed),
                "diagnostics": diagnostics,
            }

        if self._is_partial_fill(page, lot_size):
            self.close_position_immediately(page)
            self.emergency_halt("Partial fill detected")
            return {"status": "Rejected", "reason": "Partial fill detected"}

        expected_fill_price = expected_entry if expected_entry is not None else requested_price
        slippage_ok, slippage = self.execution_guard.check_slippage(
            expected_fill_price, executed_price)
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

        partial_plan = self._start_partial_watch(
            signal, position_data) if protection_set_ok else {
            "enabled": False, "reason": "protection_not_confirmed"}

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
        # Method intentionally left blank after file cleanup
        return None

    def start(self):
        # Stub: No-op for compatibility
        return None

    def close(self):
        # Stub: No-op for compatibility
        pass
