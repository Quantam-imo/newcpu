from __future__ import annotations

import argparse
import json
import time
import sys
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from execution.basis_engine import BasisEngine
from execution.broker_guard import BrokerGuard
from execution.playwright_engine import PlaywrightEngine


@dataclass
class MatchTraderConfig:
    url: str = "https://manager.maven.markets/app/trade"
    cdp_url: str = ""
    headless: bool = False
    timeout_ms: int = 12000
    user_data_dir: str = "./data/playwright_matchtrader"
    max_spread: float = 1.2
    price_tolerance: float = 1.5
    basis_threshold: float = 3.0
    cooldown_seconds: int = 60
    max_daily_loss: float = 1500.0
    kill_switch_file: str = "./data/automation.stop"
    selector_profile_file: str = "./data/matchtrader_selectors.json"
    require_calibrated_for_live: bool = True
    position_table_selectors: list[str] = field(default_factory=lambda: [
        "[data-testid='open-positions-table']",
        ".open-positions-table",
    ])
    selectors: dict[str, list[str]] = field(default_factory=lambda: {
        "login_email": [
            "#login-email",
            "input[type='email']",
            "input[name='email']",
            "input[autocomplete='username']",
        ],
        "login_password": [
            "#login-password",
            "input[type='password']",
            "input[name='password']",
            "input[autocomplete='current-password']",
        ],
        "login_button": [
            "#login-button",
            "button[type='submit']",
            "button:has-text('Login')",
            "button:has-text('Sign in')",
        ],
        "symbol": [
            "[data-testid='quotation-symbol']",
            "[data-testid='instrument-symbol']",
            "[data-testid='symbol-name']",
            ".symbol-name",
            "[class*='symbol']",
            "[id*='symbol']",
        ],
        "bid": [
            "[data-testid='quotation-bid']",
            "[data-testid='bid-price']",
            ".bid-price",
            "[class*='bid']",
            "[id*='bid']",
        ],
        "ask": [
            "[data-testid='quotation-ask']",
            "[data-testid='ask-price']",
            ".ask-price",
            "[class*='ask']",
            "[id*='ask']",
        ],
        "last": [
            "[data-testid='quotation']",
            "[data-testid='quotation-last']",
            "[data-testid='last-price']",
            ".last-price",
            "[class*='last']",
            "[id*='last']",
        ],
        "buy": [
            "[data-testid='order-panel-buy-button']",
            "#buy-button",
        ],
        "sell": [
            "[data-testid='order-panel-sell-button']",
            "#sell-button",
        ],
        "lot": [
            "[data-testid='order-lot-size']",
            "#lot-size",
        ],
        "sl": [
            "[data-testid='order-stop-loss']",
            "#stop-loss",
        ],
        "tp": [
            "[data-testid='order-take-profit']",
            "#take-profit",
        ],
        "confirm": [
            "[data-testid='order-panel-confirm-button']",
            "#confirm-order",
        ],
    })


class MatchTraderExecutor:

    def __init__(self, config: MatchTraderConfig):
        self.config = config
        self.engine = PlaywrightEngine(
            headless=config.headless,
            timeout_ms=config.timeout_ms,
            user_data_dir=config.user_data_dir,
            cdp_url=config.cdp_url,
        )
        self.basis_engine = BasisEngine(window=30)
        self.order_active = False
        self.last_trade_at = 0.0
        self.killed = False
        self.layout_failures = 0
        self.selector_profile_loaded = False
        self.selector_profile_path = Path(self.config.selector_profile_file)
        self._load_selector_profile()

    def _merge_selector_candidates(self, key: str, discovered: list[str]):
        existing = list(self.config.selectors.get(key, []))
        merged = []
        seen = set()
        for selector in [*discovered, *existing]:
            value = str(selector or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            merged.append(value)
        self.config.selectors[key] = merged

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

        for key, values in selectors.items():
            if key not in self.config.selectors:
                continue
            if not isinstance(values, list):
                continue
            self._merge_selector_candidates(key, [str(v) for v in values])

        self.selector_profile_loaded = True

    def _kill_switch_triggered(self) -> bool:
        path = Path(self.config.kill_switch_file)
        if path.exists():
            import logging, traceback
            logging.basicConfig(level=logging.ERROR)
            logging.error("Kill switch file detected: %s\n%s", path, traceback.format_stack())
            return True
        return False

    def start(self):
        self.engine.start()
        if self.config.cdp_url:
            try:
                current_url = str(self.engine.page.url or "") if self.engine.page is not None else ""
            except Exception:
                current_url = ""
            if not current_url or current_url in {"about:blank", "chrome://new-tab-page/"}:
                self.engine.goto(self.config.url)
            return

        self.engine.goto(self.config.url)

    def kill_switch(self):
        self.killed = True

    def release_order_lock(self):
        self.order_active = False

    def _find_selector_value(self, candidates: list[str]) -> str | None:
        value, _ = self._find_selector_value_with_source(candidates)
        return value

    def _find_selector_value_with_source(self, candidates: list[str]) -> tuple[str | None, str | None]:
        page = self.engine.page
        if page is None:
            return None, None

        for selector in candidates:
            try:
                locator = page.locator(selector)
                if locator.count() <= 0:
                    continue
                value = locator.first.inner_text()
                value = str(value or "").strip()
                if value:
                    return value, selector
            except Exception:
                continue
        return None, None

    def _find_selector_price(self, candidates: list[str]) -> float | None:
        value, _ = self._find_selector_price_with_source(candidates)
        return value

    def _find_selector_price_with_source(self, candidates: list[str]) -> tuple[float | None, str | None]:
        page = self.engine.page
        if page is None:
            return None, None

        for selector in candidates:
            try:
                locator = page.locator(selector)
                if locator.count() <= 0:
                    continue
                text = str(locator.first.inner_text() or "").replace(",", "").strip()
                filtered = "".join(ch for ch in text if ch.isdigit() or ch in {".", "-"})
                if not filtered:
                    continue
                return float(filtered), selector
            except Exception:
                continue
        return None, None

    def _click_first(self, candidates: list[str]) -> bool:
        page = self.engine.page
        if page is None:
            return False
        for selector in candidates:
            try:
                locator = page.locator(selector)
                if locator.count() <= 0:
                    continue
                locator.first.click(timeout=self.config.timeout_ms)
                return True
            except Exception:
                continue
        return False

    def _fill_first(self, candidates: list[str], value: Any) -> bool:
        page = self.engine.page
        if page is None:
            return False
        for selector in candidates:
            try:
                locator = page.locator(selector)
                if locator.count() <= 0:
                    continue
                locator.first.fill(str(value), timeout=self.config.timeout_ms)
                return True
            except Exception:
                continue
        return False

    def _layout_ready_for_execution(self) -> tuple[bool, list[str]]:
        page = self.engine.page
        if page is None:
            return False, ["page_unavailable"]
        missing = []
        required = {
            "buy": self.config.selectors["buy"],
            "sell": self.config.selectors["sell"],
            "lot": self.config.selectors["lot"],
            "sl": self.config.selectors["sl"],
            "tp": self.config.selectors["tp"],
            "confirm": self.config.selectors["confirm"],
        }
        for key, selectors in required.items():
            found = False
            for selector in selectors:
                try:
                    if page.locator(selector).count() > 0:
                        found = True
                        break
                except Exception:
                    continue
            if not found:
                missing.append(key)
        return len(missing) == 0, missing

        def calibrate_selectors(self, save: bool = True) -> dict[str, Any]:
                page = self.engine.page
                if page is None:
                        return {"ok": False, "reason": "page unavailable"}

                script = r"""
() => {
    const byKey = {
        symbol: [], bid: [], ask: [], last: [], buy: [], sell: [], lot: [], sl: [], tp: [], confirm: []
    };

    const uniquePush = (arr, value) => {
        if (!value || arr.includes(value)) return;
        arr.push(value);
    };

    const selectorOf = (el) => {
        if (!el) return null;
        const id = (el.id || '').trim();
        if (id) return `#${id}`;
        const testid = (el.getAttribute('data-testid') || '').trim();
        if (testid) return `[data-testid='${testid}']`;
        const name = (el.getAttribute('name') || '').trim();
        if (name) return `[name='${name}']`;
        const cls = (el.className || '').toString().trim().split(/\s+/).filter(Boolean);
        if (cls.length > 0) return `.${cls.slice(0, 2).join('.')}`;
        return el.tagName ? el.tagName.toLowerCase() : null;
    };

    const textOf = (el) => (el && el.innerText ? el.innerText : '').trim();
    const attrBlob = (el) => {
        if (!el) return '';
        return [
            el.getAttribute('data-testid') || '',
            el.getAttribute('id') || '',
            el.getAttribute('name') || '',
            el.getAttribute('placeholder') || '',
            el.className || '',
            textOf(el).slice(0, 40),
        ].join(' ').toLowerCase();
    };

    const all = Array.from(document.querySelectorAll('*'));
    for (const el of all) {
        const blob = attrBlob(el);
        const text = textOf(el);
        const selector = selectorOf(el);
        if (!selector) continue;

        if (/xau\/?usd|gold|gc/.test(blob) || /xau\/?usd|gold|gc/.test(text.toLowerCase())) {
            uniquePush(byKey.symbol, selector);
        }

        const numLike = /^-?[0-9][0-9,]*(\.[0-9]+)?$/.test(text.replace(/\s+/g, ''));
        if (/\bbid\b/.test(blob) && (numLike || /[0-9]/.test(text))) uniquePush(byKey.bid, selector);
        if (/\bask\b/.test(blob) && (numLike || /[0-9]/.test(text))) uniquePush(byKey.ask, selector);
        if (/\blast\b|quote|price/.test(blob) && (numLike || /[0-9]/.test(text))) uniquePush(byKey.last, selector);

        if (/buy/.test(blob)) uniquePush(byKey.buy, selector);
        if (/sell/.test(blob)) uniquePush(byKey.sell, selector);
        if (/lot|volume|qty|quantity/.test(blob)) uniquePush(byKey.lot, selector);
        if (/\bsl\b|stop[-_\s]?loss/.test(blob)) uniquePush(byKey.sl, selector);
        if (/\btp\b|take[-_\s]?profit/.test(blob)) uniquePush(byKey.tp, selector);
        if (/confirm|place|submit|execute|open\\s*trade/.test(blob)) uniquePush(byKey.confirm, selector);
    }

    return byKey;
}
"""

                try:
                        discovered = page.evaluate(script)
                except Exception as exc:
                        return {"ok": False, "reason": f"calibration evaluate failed: {exc}"}

                for key in self.config.selectors.keys():
                        values = discovered.get(key, []) if isinstance(discovered, dict) else []
                        if isinstance(values, list):
                                self._merge_selector_candidates(key, [str(v) for v in values[:20]])

                profile = {
                        "updated_at": int(time.time()),
                        "selectors": self.config.selectors,
                }

                if save:
                        self.selector_profile_path.parent.mkdir(parents=True, exist_ok=True)
                        self.selector_profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
                        self.selector_profile_loaded = True

                quote_check = self.read_quote()
                return {
                        "ok": True,
                        "profile_file": str(self.selector_profile_path),
                        "discovered_keys": {k: len(v) for k, v in discovered.items()} if isinstance(discovered, dict) else {},
                        "quote_check": quote_check,
                }

    def read_quote(self) -> dict[str, Any]:
        symbol, symbol_selector = self._find_selector_value_with_source(self.config.selectors["symbol"])
        bid, bid_selector = self._find_selector_price_with_source(self.config.selectors["bid"])
        ask, ask_selector = self._find_selector_price_with_source(self.config.selectors["ask"])
        last, last_selector = self._find_selector_price_with_source(self.config.selectors["last"])

        if bid is None and ask is None and last is None:
            self.layout_failures += 1
            return {
                "ok": False,
                "reason": "quote selectors unavailable",
                "layout_failures": self.layout_failures,
                "timestamp": int(time.time()),
            }

        if bid is not None and ask is not None:
            mid = (bid + ask) / 2.0
            spread = ask - bid
        else:
            mid = last
            spread = None

        return {
            "ok": True,
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "last": last,
            "mid": mid,
            "spread": spread,
            "selector_sources": {
                "symbol": symbol_selector,
                "bid": bid_selector,
                "ask": ask_selector,
                "last": last_selector,
            },
            "profile_loaded": self.selector_profile_loaded,
            "timestamp": int(time.time()),
        }

    def wait_for_manual_login(self, timeout_seconds: int = 300, poll_seconds: int = 2):
        deadline = time.time() + max(5, int(timeout_seconds))
        while time.time() < deadline:
            quote = self.read_quote()
            if quote.get("ok"):
                return quote
            time.sleep(max(1, int(poll_seconds)))
        return None

    def is_logged_in(self) -> bool:
        quote = self.read_quote()
        if quote.get("ok"):
            return True
        layout_ready, _ = self._layout_ready_for_execution()
        return bool(layout_ready)

    def is_login_screen(self) -> bool:
        page = self.engine.page
        if page is None:
            return False

        email_present = any(page.locator(sel).count() > 0 for sel in self.config.selectors.get("login_email", []))
        password_present = any(page.locator(sel).count() > 0 for sel in self.config.selectors.get("login_password", []))
        return bool(email_present and password_present)

    def login_if_needed(self, email: str | None, password: str | None) -> dict[str, Any]:
        if self.is_logged_in():
            return {"ok": True, "status": "already_authenticated", "quote": self.read_quote()}

        login_screen = self.is_login_screen()
        if not login_screen:
            return {
                "ok": False,
                "status": "auth_unknown",
                "reason": "Neither active quote panel nor login form detected",
            }

        if not email or not password:
            return {"ok": False, "status": "credentials_missing"}

        email_ok = self._fill_first(self.config.selectors.get("login_email", []), email)
        password_ok = self._fill_first(self.config.selectors.get("login_password", []), password)
        button_ok = self._click_first(self.config.selectors.get("login_button", []))

        if not (email_ok and password_ok and button_ok):
            return {
                "ok": False,
                "status": "login_selectors_failed",
                "email_ok": email_ok,
                "password_ok": password_ok,
                "button_ok": button_ok,
            }

        time.sleep(4)
        quote = self.read_quote()
        return {
            "ok": bool(quote.get("ok")),
            "status": "login_attempted",
            "quote": quote,
        }

    def run_stability_test(self, duration_minutes: int = 30, poll_seconds: int = 2, log_file: str = "logs/matchtrader_stability.jsonl"):
        start_ts = time.time()
        end_ts = start_ts + (max(1, int(duration_minutes)) * 60)
        samples = 0
        failures = 0
        disconnects = 0
        last_ok_at = None

        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with log_path.open("a", encoding="utf-8") as handle:
            while time.time() < end_ts:
                if self.killed or self._kill_switch_triggered():
                    self.killed = True
                    break

                quote = self.read_quote()
                if quote.get("ok"):
                    samples += 1
                    last_ok_at = quote.get("timestamp")
                else:
                    failures += 1
                    if (time.time() - (last_ok_at or start_ts)) > 10:
                        disconnects += 1

                handle.write(json.dumps(quote) + "\n")
                handle.flush()
                time.sleep(max(1, int(poll_seconds)))

        return {
            "status": "stopped" if self.killed else "completed",
            "samples": samples,
            "failures": failures,
            "disconnects": disconnects,
            "layout_failures": self.layout_failures,
            "log_file": str(log_path),
            "duration_minutes": duration_minutes,
        }

    def simulate_order(self, signal: dict[str, Any], futures_price: float, daily_loss: float = 0.0) -> dict[str, Any]:
        if self.killed or self._kill_switch_triggered():
            self.killed = True
            return {"allowed": False, "reason": "kill switch active"}

        quote = self.read_quote()
        if not quote.get("ok"):
            return {"allowed": False, "reason": "broker quote unavailable", "quote": quote}

        if daily_loss > self.config.max_daily_loss:
            return {"allowed": False, "reason": "daily loss guard"}

        if self.order_active:
            return {"allowed": False, "reason": "execution lock active"}

        now = time.time()
        if (now - float(self.last_trade_at or 0.0)) < int(self.config.cooldown_seconds):
            return {"allowed": False, "reason": "cooldown active"}

        bid = quote.get("bid")
        ask = quote.get("ask")
        broker_price = ask if str(signal.get("direction", "")).upper() == "BUY" else bid
        if broker_price is None:
            broker_price = quote.get("mid")
        if broker_price is None:
            return {"allowed": False, "reason": "broker price unavailable"}

        self.basis_engine.update(float(futures_price), float(broker_price))
        converted = self.basis_engine.convert_signal(signal)

        if ask is not None and bid is not None and not BrokerGuard.spread_ok(bid, ask, self.config.max_spread):
            return {
                "allowed": False,
                "reason": "spread too high",
                "spread": BrokerGuard.notional_spread(bid, ask),
            }

        if not BrokerGuard.price_sync_ok(
            converted["broker_entry"],
            float(broker_price),
            self.config.price_tolerance,
        ):
            return {
                "allowed": False,
                "reason": "price sync mismatch",
                "broker_entry": converted["broker_entry"],
                "broker_price": broker_price,
            }

        current_basis = float(broker_price) - float(futures_price)
        rolling_basis = self.basis_engine.get_smoothed_basis()
        if abs(current_basis - rolling_basis) > float(self.config.basis_threshold):
            return {
                "allowed": False,
                "reason": "basis anomaly guard",
                "current_basis": current_basis,
                "rolling_basis": rolling_basis,
                "threshold": self.config.basis_threshold,
            }

        return {
            "allowed": True,
            "mode": "READ_ONLY_SIMULATION",
            "message": f"Would {converted['direction']} XAUUSD",
            "entry": round(float(converted["broker_entry"]), 3),
            "sl": round(float(converted["broker_sl"]), 3),
            "tp": round(float(converted["broker_tp"]), 3),
            "spread": round(float((ask - bid) if (ask is not None and bid is not None) else 0.0), 3),
            "price_sync": "OK",
            "basis": round(float(converted["basis"]), 4),
            "lot": float(converted["lot"]),
            "quote": quote,
        }

    def place_order(self, simulated: dict[str, Any]) -> dict[str, Any]:
        if self.killed or self._kill_switch_triggered():
            self.killed = True
            return {"status": "blocked", "reason": "kill switch active"}

        if self.order_active:
            return {"status": "blocked", "reason": "execution lock active"}

        if self.config.require_calibrated_for_live and not self.selector_profile_loaded:
            self.killed = True
            return {
                "status": "blocked",
                "reason": "selector profile not calibrated",
                "profile_file": str(self.selector_profile_path),
            }

        now = time.time()
        if (now - float(self.last_trade_at or 0.0)) < int(self.config.cooldown_seconds):
            return {"status": "blocked", "reason": "cooldown active"}

        ready, missing = self._layout_ready_for_execution()
        if not ready:
            self.killed = True
            return {"status": "blocked", "reason": "layout failure detected", "missing": missing}

        direction = str(simulated.get("message", "")).upper()
        side_buy = "BUY" in direction
        side_ok = self._click_first(self.config.selectors["buy"] if side_buy else self.config.selectors["sell"])
        if not side_ok:
            self.killed = True
            return {"status": "blocked", "reason": "failed to click side button"}

        lot_ok = self._fill_first(self.config.selectors["lot"], simulated.get("lot"))
        sl_ok = self._fill_first(self.config.selectors["sl"], simulated.get("sl"))
        tp_ok = self._fill_first(self.config.selectors["tp"], simulated.get("tp"))
        if not (lot_ok and sl_ok and tp_ok):
            self.killed = True
            return {"status": "blocked", "reason": "failed to fill lot/sl/tp"}

        self.order_active = True
        confirm_ok = self._click_first(self.config.selectors["confirm"])
        if not confirm_ok:
            self.killed = True
            self.order_active = False
            return {"status": "blocked", "reason": "failed to confirm order"}

        self.last_trade_at = time.time()
        position_text = self._find_selector_value(self.config.position_table_selectors)
        return {
            "status": "submitted",
            "lock_active": self.order_active,
            "position_snapshot": position_text,
            "message": "Order submitted; verify SL/TP and close manually for micro-lot test",
        }


def _sample_signal() -> dict[str, Any]:
    return {
        "direction": "BUY",
        "entry": 2374.50,
        "stop": 2370.20,
        "target": 2382.10,
        "lot": 0.01,
    }


def main():
    parser = argparse.ArgumentParser(description="Controlled MatchTrader automation tester")
    parser.add_argument("--mode", choices=["calibrate", "step1", "step2", "step3"], default="step1")
    parser.add_argument("--duration-min", type=int, default=30)
    parser.add_argument("--poll-sec", type=int, default=2)
    parser.add_argument("--futures-price", type=float, default=2374.10)
    parser.add_argument("--manual-login-timeout", type=int, default=300)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--live", action="store_true", help="Allow live click execution in step3")
    parser.add_argument("--daily-loss", type=float, default=0.0)
    parser.add_argument("--recalibrate", action="store_true", help="Re-run selector calibration after login")
    parser.add_argument("--email", type=str, default="")
    parser.add_argument("--password", type=str, default="")
    parser.add_argument("--password-env", type=str, default="MAVEN_PASSWORD")
    parser.add_argument("--email-env", type=str, default="MAVEN_EMAIL")
    parser.add_argument("--cdp-url", type=str, default="", help="Attach to an existing browser via CDP, e.g. http://127.0.0.1:9222")
    args = parser.parse_args()

    inferred_headless = bool(args.headless) or not bool(os.getenv("DISPLAY", "").strip())
    config = MatchTraderConfig(
        headless=inferred_headless,
        cdp_url=str(args.cdp_url or "").strip(),
    )
    runner = MatchTraderExecutor(config)
    runner.start()

    print(f"Browser opened. headless={config.headless}. cdp_attach={bool(config.cdp_url)}. Login manually if required.")
    email = str(args.email or os.getenv(str(args.email_env), "")).strip()
    password = str(args.password or os.getenv(str(args.password_env), "")).strip()
    login_result = runner.login_if_needed(email=email, password=password)
    if login_result.get("status") == "already_authenticated":
        print("Detected existing logged-in session. Skipping login.")
    if login_result.get("status") == "login_attempted":
        print("Automated login result:", login_result)
    if login_result.get("status") == "credentials_missing":
        print("Login form detected but credentials missing. Set --email/--password or env vars.")

    quote = runner.wait_for_manual_login(timeout_seconds=args.manual_login_timeout, poll_seconds=max(1, args.poll_sec))
    if not quote:
        print("Login/quote detection timeout. Stop.")
        return

    print("Quote feed detected:", quote)

    if args.mode == "calibrate" or args.recalibrate:
        calibration = runner.calibrate_selectors(save=True)
        print(json.dumps(calibration, indent=2))
        if args.mode == "calibrate":
            return

    if args.mode == "step1":
        result = runner.run_stability_test(duration_minutes=args.duration_min, poll_seconds=args.poll_sec)
        print(json.dumps(result, indent=2))
        return

    signal = _sample_signal()
    simulated = runner.simulate_order(
        signal=signal,
        futures_price=float(args.futures_price),
        daily_loss=float(args.daily_loss),
    )
    print(json.dumps(simulated, indent=2))

    if args.mode == "step2":
        return

    if not args.live:
        print("Step3 in SAFE mode: no clicks. Re-run with --live only on challenge account.")
        return

    if not simulated.get("allowed"):
        print("Execution blocked by guards; no order sent.")
        return

    order_result = runner.place_order(simulated)
    print(json.dumps(order_result, indent=2))


if __name__ == "__main__":
    main()
