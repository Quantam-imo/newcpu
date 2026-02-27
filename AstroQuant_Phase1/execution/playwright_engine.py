from playwright.sync_api import sync_playwright
import time
from execution.config import SYMBOL, LOT_SIZE
from execution.execution_verifier import ExecutionVerifier
from execution.broker_feed_engine import BrokerFeedEngine

class PlaywrightEngine:

    def __init__(self):
        self.browser = None
        self.page = None
        self.broker_feed = BrokerFeedEngine()

    def start(self):
        playwright = sync_playwright().start()
        self.browser = playwright.chromium.launch_persistent_context(
            user_data_dir="browser_session",
            headless=False
        )
        self.page = self.browser.new_page()

        print("Browser started. Login manually.")

    def wait_for_login(self):
        print("Waiting for manual login...")
        self.page.wait_for_selector("[data-testid='instrument-symbol-name-wrapper']", timeout=0)
        print("Login detected.")


    def execute_market_order(self, direction):

        print(f"Executing {direction} order")

        # Select symbol if needed
        try:
            self.page.click("[data-testid='instrument-symbol-name-wrapper']")
        except:
            pass

        # Set lot size
        self.page.click("[data-testid='input-stepper-input']")
        self.page.keyboard.press("Control+A")
        self.page.keyboard.type(LOT_SIZE)

        time.sleep(1)

        if direction == "BUY":
            self.page.click("[data-testid='order-panel-buy-button']")
        else:
            self.page.click("[data-testid='order-panel-sell-button']")

        verifier = ExecutionVerifier(self.page)

        if not verifier.verify_trade_opened():
            print("Execution failed.")
            return False

        if not verifier.verify_sl_tp_attached():
            print("SL/TP not attached!")
            return False

        print("Execution confirmed.")
        return True

    def update_broker_feed(self, symbol="XAUUSD"):
        return self.broker_feed.update(self.page, symbol=symbol)

    def get_broker_feed_state(self):
        return self.broker_feed.get_state()

    def close(self):
        self.browser.close()
