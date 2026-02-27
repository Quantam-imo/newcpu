import time
import os
import requests

class TradeGuardian:

    def __init__(self, page):
        self.page = page

    # ----------------------------
    # SPREAD CHECK
    # ----------------------------
    def current_spread(self):
        try:
            spread_element = self.page.query_selector("[data-testid='pips-spread-component']")
            text = spread_element.inner_text()
            spread = float(text.strip().split()[-1])
            return spread
        except:
            return None

    def spread_allowed(self, max_spread):
        spread = self.current_spread()
        if spread is None:
            print("Spread unknown. Blocking trade.")
            return False

        print(f"Current Spread: {spread}")
        return spread <= max_spread

    # ----------------------------
    # SLIPPAGE CHECK
    # ----------------------------
    def calculate_slippage(self, expected_price):
        try:
            open_price = self.page.query_selector("[data-testid='position-open-price']")
            executed = float(open_price.inner_text())
            slippage = abs(executed - expected_price)
            print(f"Slippage: {slippage}")
            return slippage
        except:
            return None

    # ----------------------------
    # NEWS LOCK (Simple Version)
    # ----------------------------
    def news_lock(self):
        try:
            backend_base = str(os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000")).strip().rstrip("/")
            response = requests.get(f"{backend_base}/news/status", timeout=1.5)
            data = response.json()

            trade_halt = bool(data.get("trade_halt", False))
            high_impact = data.get("high_impact", False)

            if isinstance(high_impact, bool):
                high_impact_flag = high_impact
            else:
                high_impact_flag = str(high_impact).strip().lower() not in ["", "false", "none", "no"]

            if trade_halt or high_impact_flag:
                print("High impact news active. Trade blocked.")
                return False

            return True
        except Exception:
            return True

    # ----------------------------
    # VOLATILITY HALT
    # ----------------------------
    def volatility_halt(self, threshold=0.5):
        try:
            price = self.page.query_selector("[data-testid='quotation']")
            current = float(price.inner_text())
            time.sleep(1)
            new = float(price.inner_text())

            move = abs(new - current)

            if move > threshold:
                print("Extreme volatility detected. Blocking trade.")
                return False

            return True
        except:
            return True

    # ----------------------------
    # SENTIMENT LOCK
    # ----------------------------
    def sentiment_lock(self, sentiment_score, min_abs_strength=10):
        try:
            score = float(sentiment_score)
        except Exception:
            return True

        if abs(score) < float(min_abs_strength):
            print("Sentiment lock active. Weak directional sentiment.")
            return False

        return True
