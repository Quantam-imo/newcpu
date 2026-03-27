from playwright.sync_api import sync_playwright

def place_trade_ui():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        page.goto("YOUR_BROKER_URL")

        # Add login + click buy/sell logic

        browser.close()
