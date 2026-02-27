import time

class PositionMonitor:

    def __init__(self, page):
        self.page = page

    def has_open_position(self):
        try:
            self.page.click("[data-testid='open-positions-tab']")
            time.sleep(1)

            rows = self.page.query_selector_all("[data-testid='position-row']")
            return len(rows) > 0
        except:
            return False

    def get_position_price(self):
        try:
            price = self.page.query_selector("[data-testid='position-open-price']")
            return price.inner_text()
        except:
            return None
