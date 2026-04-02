#!/usr/bin/env python3
"""
AstroQuant — Cloudflare Challenge Auto-Unblock
===============================================
Connects to the already-running Chrome CDP session, waits for the
Cloudflare "Just a moment..." JS challenge on the Maven trading tab to
auto-resolve, then auto-fills login credentials if a login form appears.

Usage (standalone):
    python3 cloudflare_unblock.py [--cdp-url http://127.0.0.1:9222]
                                  [--broker-url https://manager.maven.markets/app/trade]
                                  [--max-wait 120]

Environment variables (all optional, loaded from .env if present):
    AQ_CDP_BASE              CDP base URL          (default: http://127.0.0.1:9222)
    AQ_BROKER_URL            Maven trading URL     (default: https://manager.maven.markets/app/trade)
    AQ_CF_MAX_WAIT           Max seconds to wait for CF challenge to clear (default: 120)
    AQ_LOGIN_MAX_WAIT        Max seconds to wait for login to succeed (default: 60)
    EXECUTION_LOGIN_USERNAME  Maven email/username
    EXECUTION_LOGIN_PASSWORD  Maven password
    MAVEN_EMAIL               Alias for username
    MAVEN_PASSWORD            Alias for password
"""

import os
import sys
import time
import argparse
import urllib.request
import urllib.error
import json
from pathlib import Path

# ── Load .env if present ────────────────────────────────────────────────────
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        _k = _k.strip()
        _v = _v.strip().strip('"').strip("'")
        if _k and _k not in os.environ:
            os.environ[_k] = _v

# ── Config from environment ──────────────────────────────────────────────────
CDP_BASE = os.getenv("AQ_CDP_BASE", "http://127.0.0.1:9222").rstrip("/")
BROKER_URL = os.getenv("AQ_BROKER_URL", "https://manager.maven.markets/app/trade")
MAX_WAIT_CF = int(os.getenv("AQ_CF_MAX_WAIT", "120"))
MAX_WAIT_LOGIN = int(os.getenv("AQ_LOGIN_MAX_WAIT", "60"))
LOGIN_USERNAME = (
    os.getenv("EXECUTION_LOGIN_USERNAME")
    or os.getenv("MAVEN_EMAIL")
    or os.getenv("MAVEN_USERNAME")
    or ""
).strip()
LOGIN_PASSWORD = (
    os.getenv("EXECUTION_LOGIN_PASSWORD")
    or os.getenv("MAVEN_PASSWORD")
    or ""
).strip()

# ── Helpers ──────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[cf-unblock {ts}] {msg}", flush=True)


def _cdp_json(path: str, timeout: float = 5.0):
    url = f"{CDP_BASE}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def wait_for_cdp(max_wait: int = 30) -> bool:
    """Wait until Chrome CDP is reachable."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        data = _cdp_json("/json/version")
        if data and data.get("Browser"):
            _log(f"CDP ready: {data.get('Browser', 'unknown')}")
            return True
        time.sleep(1.5)
    return False


def get_maven_tab() -> dict | None:
    """Return the CDP tab entry for the Maven trading page."""
    tabs = _cdp_json("/json/list") or []
    # Prefer an exact match, fall back to any maven.markets tab
    for tab in tabs:
        url = str(tab.get("url") or "")
        if "manager.maven.markets/app/trade" in url:
            return tab
    for tab in tabs:
        url = str(tab.get("url") or "")
        if "maven.markets" in url:
            return tab
    return None


def open_maven_tab() -> None:
    """Open a new Maven tab if none exists."""
    encoded = urllib.request.quote(BROKER_URL, safe=":/?.=&")
    _cdp_json(f"/json/new?{encoded}")
    time.sleep(2)


# ── Playwright-based challenge + login handler ───────────────────────────────

def _playwright_handle_challenge_and_login() -> str:
    """
    Uses Playwright connect_over_cdp to:
      1. Wait for Cloudflare JS challenge to auto-clear (up to MAX_WAIT_CF s).
      2. Reload and retry if challenge persists.
      3. Auto-fill login form if it appears after challenge clears.
    Returns one of: 'ok' | 'challenge_persist' | 'login_ok' | 'login_failed' | 'error'
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        _log("Playwright not installed — skipping auto-unblock.")
        return "error"

    _log("Connecting to Chrome via CDP...")
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.connect_over_cdp(CDP_BASE)
        except Exception as exc:
            _log(f"CDP connect failed: {exc}")
            return "error"

        _log("Connected. Scanning contexts for Maven tab...")
        page = None
        # Search all contexts
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if "maven.markets" in (pg.url or ""):
                    page = pg
                    break
            if page:
                break

        if page is None:
            _log(f"No Maven tab found, opening {BROKER_URL} ...")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            page.goto(BROKER_URL, timeout=30_000, wait_until="domcontentloaded")

        # ── Phase 1: Wait for Cloudflare challenge to clear ──────────────────
        cf_deadline = time.time() + MAX_WAIT_CF
        reload_count = 0

        # Inject stealth properties to help Cloudflare JS challenge pass.
        # This removes headless/automation fingerprints from the current context.
        _STEALTH_JS = """
            // Remove webdriver flag
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            // Add chrome object that real Chrome has
            if (!window.chrome) {
                window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
            }
            // Remove headless indicators
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                    { name: 'Native Client', filename: 'internal-nacl-plugin' }
                ]
            });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            // Override permission query to avoid bot detection signal
            const origQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (params) =>
                params.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : origQuery(params);
        """

        try:
            # Add stealth init script to context for future navigations
            for ctx in browser.contexts:
                try:
                    ctx.add_init_script(_STEALTH_JS)
                except Exception:
                    pass
            # Also evaluate immediately on current page
            try:
                page.evaluate(_STEALTH_JS)
            except Exception:
                pass
        except Exception:
            pass

        while time.time() < cf_deadline:
            title = (page.title() or "").strip().lower()

            if "just a moment" not in title and "challenge" not in title:
                _log(f"Challenge cleared. Current title: '{page.title()}'")
                break

            elapsed = int(cf_deadline - time.time())
            _log(f"Cloudflare challenge active ('{page.title()}'), waiting... {elapsed}s left")

            # Reload with stealth JS injected — up to 3 reloads, every ~25 s
            if reload_count < 3 and elapsed <= (MAX_WAIT_CF - 20 * (reload_count + 1)):
                _log(f"Reloading tab (attempt {reload_count + 1}/3) to get fresh challenge pass...")
                try:
                    page.reload(timeout=20_000, wait_until="domcontentloaded")
                    reload_count += 1
                    try:
                        page.evaluate(_STEALTH_JS)
                    except Exception:
                        pass
                except Exception:
                    pass
                time.sleep(6)
            else:
                time.sleep(4)
        else:
            title = (page.title() or "").strip().lower()
            if "just a moment" in title or "challenge" in title:
                _log("Challenge did not clear within timeout.")
                _log("TIP: Run Chrome once manually (headed/non-headless) to solve the challenge.")
                _log("     The cf_clearance cookie will be saved in the persistent profile,")
                _log("     and future restarts will skip the Cloudflare challenge entirely.")
                return "challenge_persist"

        # ── Phase 2: Auto-login if credentials are available ─────────────────
        if not LOGIN_USERNAME or not LOGIN_PASSWORD:
            _log("No login credentials set — skipping auto-login.")
            return "ok"

        login_deadline = time.time() + MAX_WAIT_LOGIN
        login_selectors_email = [
            "#login-email",
            "input[type='email']",
            "input[name='email']",
            "input[autocomplete='username']",
            "input[name='username']",
        ]
        login_selectors_pass = [
            "#login-password",
            "input[type='password']",
            "input[name='password']",
            "input[autocomplete='current-password']",
        ]
        login_submit = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Login')",
            "button:has-text('Sign in')",
            "button:has-text('Log in')",
        ]

        while time.time() < login_deadline:
            # Check if any login input exists
            email_visible = any(
                page.locator(sel).count() > 0
                for sel in login_selectors_email
            )
            if email_visible:
                _log("Login form detected — filling credentials...")
                try:
                    for sel in login_selectors_email:
                        loc = page.locator(sel)
                        if loc.count() > 0:
                            loc.first.fill(LOGIN_USERNAME, timeout=5_000)
                            break
                    for sel in login_selectors_pass:
                        loc = page.locator(sel)
                        if loc.count() > 0:
                            loc.first.fill(LOGIN_PASSWORD, timeout=5_000)
                            break
                    for sel in login_submit:
                        loc = page.locator(sel)
                        if loc.count() > 0:
                            loc.first.click(timeout=5_000)
                            break
                    _log("Login form submitted.")
                    # Wait for page to navigate away from login
                    try:
                        page.wait_for_url(
                            lambda u: "login" not in (u or "").lower()
                                      and "signin" not in (u or "").lower(),
                            timeout=20_000,
                        )
                        _log("Login succeeded — trading page loaded.")
                        return "login_ok"
                    except PWTimeout:
                        _log("Login navigation timeout — page may still be loading.")
                        return "login_failed"
                except Exception as exc:
                    _log(f"Login fill error: {exc}")
                    return "login_failed"

            # If we're already on the trade page, we're good
            if "app/trade" in (page.url or "") and "login" not in (page.url or "").lower():
                _log("Already on trade page — no login needed.")
                return "ok"

            time.sleep(2)

        _log("Login form did not appear within timeout — assuming already logged in.")
        return "ok"


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    global CDP_BASE, BROKER_URL, MAX_WAIT_CF
    parser = argparse.ArgumentParser(description="AstroQuant Cloudflare Auto-Unblock")
    parser.add_argument("--cdp-url", default=CDP_BASE, help="Chrome CDP base URL")
    parser.add_argument("--broker-url", default=BROKER_URL, help="Maven trading URL")
    parser.add_argument("--max-wait", type=int, default=MAX_WAIT_CF, help="Max seconds for CF challenge wait")
    parser.add_argument("--cdp-wait", type=int, default=60, help="Max seconds to wait for Chrome CDP to be ready")
    args = parser.parse_args()

    # Override module-level config from CLI args
    CDP_BASE = args.cdp_url.rstrip("/")
    BROKER_URL = args.broker_url
    MAX_WAIT_CF = args.max_wait

    _log("=== AstroQuant Cloudflare Auto-Unblock starting ===")
    _log(f"CDP: {CDP_BASE}  |  Broker: {BROKER_URL}  |  Max-wait: {MAX_WAIT_CF}s")
    _log(f"Credentials: {'SET' if (LOGIN_USERNAME and LOGIN_PASSWORD) else 'NOT SET'}")

    # 1. Wait for Chrome CDP
    _log("Waiting for Chrome CDP to become available...")
    if not wait_for_cdp(max_wait=args.cdp_wait):
        _log("ERROR: Chrome CDP not reachable after waiting. Is Chrome running?")
        return 1

    # 2. Ensure Maven tab exists
    tab = get_maven_tab()
    if tab is None:
        _log("No Maven tab found in Chrome — opening one now...")
        open_maven_tab()
        time.sleep(3)
        tab = get_maven_tab()
        if tab is None:
            _log("WARNING: Still no Maven tab — proceeding anyway.")

    if tab:
        title = tab.get("title", "")
        url = tab.get("url", "")
        _log(f"Maven tab found: '{title}' @ {url}")
        if "just a moment" not in title.lower() and "challenge" not in title.lower():
            if "login" not in url.lower():
                _log("No challenge or login detected — bridge should be ready.")
                return 0

    # 3. Use Playwright to handle challenge + login
    result = _playwright_handle_challenge_and_login()

    if result in ("ok", "login_ok"):
        _log(f"Success: {result}. Maven bridge should be ready.")
        return 0
    elif result == "challenge_persist":
        _log("Cloudflare challenge persisted beyond timeout.")
        _log("NOTE: A persistent browser profile helps cache Cloudflare clearance.")
        _log("      Once you manually clear it once, subsequent restarts skip the challenge.")
        return 2
    elif result == "login_failed":
        _log("Login attempt failed — check EXECUTION_LOGIN_USERNAME / EXECUTION_LOGIN_PASSWORD in .env")
        return 3
    else:
        _log(f"Unexpected result: {result}")
        return 4


if __name__ == "__main__":
    sys.exit(main())
