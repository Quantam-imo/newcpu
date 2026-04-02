#!/usr/bin/env python3
"""
Maven Markets Login via Chrome CDP
-----------------------------------
Uses the already-running Chrome session to auto-fill and submit the login form.
"""
import asyncio
import getpass
import json
import sys
import websockets

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222

async def cdp_send(ws, method, params=None, msg_id=1):
    payload = {"id": msg_id, "method": method, "params": params or {}}
    await ws.send(json.dumps(payload))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        msg = json.loads(raw)
        if msg.get("id") == msg_id:
            return msg.get("result", {})

async def get_page_ws_url():
    import urllib.request
    url = f"http://{CDP_HOST}:{CDP_PORT}/json"
    with urllib.request.urlopen(url, timeout=5) as r:
        tabs = json.loads(r.read())
    for tab in tabs:
        if tab.get("type") == "page" and "maven.markets" in tab.get("url", ""):
            return tab["webSocketDebuggerUrl"]
    # fallback: first page tab
    for tab in tabs:
        if tab.get("type") == "page":
            return tab["webSocketDebuggerUrl"]
    raise RuntimeError("No Chrome page tab found on CDP port 9222")

async def login(email: str, password: str):
    ws_url = await get_page_ws_url()
    print(f"[+] Connecting to Chrome tab: {ws_url}")

    async with websockets.connect(ws_url, max_size=10_000_000) as ws:
        # Navigate to login page
        print("[*] Navigating to Maven Markets login page...")
        await cdp_send(ws, "Page.navigate", {"url": "https://manager.maven.markets/login"}, 1)
        await asyncio.sleep(4)  # Wait for page load

        # Enable Runtime
        await cdp_send(ws, "Runtime.enable", {}, 2)

        js_login = f"""
        (async () => {{
            const wait = (ms) => new Promise(r => setTimeout(r, ms));

            // Find email field
            let email = document.querySelector('input[type="email"], input[name="email"], input[placeholder*="email" i], input[placeholder*="Email" i]');
            if (!email) {{
                const inputs = document.querySelectorAll('input');
                for (const inp of inputs) {{
                    if (inp.type !== 'password' && inp.type !== 'hidden') {{ email = inp; break; }}
                }}
            }}
            if (!email) return 'ERROR: email field not found';
            email.focus();
            email.value = '';
            email.dispatchEvent(new Event('input', {{bubbles: true}}));
            document.execCommand('insertText', false, '{email}');
            email.dispatchEvent(new Event('change', {{bubbles: true}}));
            await wait(300);

            // Find password field
            let pwd = document.querySelector('input[type="password"]');
            if (!pwd) return 'ERROR: password field not found';
            pwd.focus();
            pwd.value = '';
            pwd.dispatchEvent(new Event('input', {{bubbles: true}}));
            document.execCommand('insertText', false, '{password}');
            pwd.dispatchEvent(new Event('change', {{bubbles: true}}));
            await wait(300);

            // Click login/submit button
            let btn = document.querySelector('button[type="submit"]') ||
                      document.querySelector('button.login') ||
                      document.querySelector('button');
            if (!btn) return 'ERROR: submit button not found';
            btn.click();

            return 'OK: login form submitted';
        }})()
        """

        print("[*] Filling in credentials and submitting login form...")
        result = await cdp_send(ws, "Runtime.evaluate", {
            "expression": js_login,
            "awaitPromise": True,
            "returnByValue": True
        }, 3)

        val = result.get("result", {}).get("value", "no result")
        print(f"[+] JS result: {val}")

        if "ERROR" in str(val):
            print("[!] Form fill failed. Trying keyboard input fallback...")
            # Fallback: use keyboard events
            await cdp_send(ws, "Input.dispatchKeyEvent", {"type": "char", "text": ""}, 10)

        print("[*] Waiting 5s for login to complete...")
        await asyncio.sleep(5)

        # Check current URL
        url_result = await cdp_send(ws, "Runtime.evaluate", {
            "expression": "window.location.href",
            "returnByValue": True
        }, 4)
        current_url = url_result.get("result", {}).get("value", "unknown")
        print(f"[+] Current URL: {current_url}")

        if "login" not in current_url:
            print("\n✅ LOGIN SUCCESSFUL! Maven Markets session is active.")
            print("   The backend can now connect to the trading interface.")
        else:
            print("\n⚠️  Still on login page. Check credentials and try again.")
            print("   Hint: The browser session is at http://127.0.0.1:6080/vnc.html for manual entry.")

if __name__ == "__main__":
    print("=" * 50)
    print("  Maven Markets Login Tool")
    print("=" * 50)
    print()

    try:
        email = input("Enter Maven Markets email: ").strip()
        password = getpass.getpass("Enter Maven Markets password: ")
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(0)

    if not email or not password:
        print("Error: email and password required.")
        sys.exit(1)

    asyncio.run(login(email, password))
