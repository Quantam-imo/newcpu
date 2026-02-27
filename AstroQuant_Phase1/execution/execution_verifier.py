import time
from execution.position_monitor import PositionMonitor

class ExecutionVerifier:

    def __init__(self, page):
        self.page = page
        self.monitor = PositionMonitor(page)

    def verify_trade_opened(self):

        for _ in range(10):  # wait up to 10 seconds
            if self.monitor.has_open_position():
                print("Trade verified as OPEN.")
                return True
            time.sleep(1)

        print("Trade not detected. Possible rejection.")
        return False

    def verify_sl_tp_attached(self):
        try:
            sl = self.page.query_selector("[data-testid='stop-loss-value']")
            tp = self.page.query_selector("[data-testid='take-profit-value']")

            if sl and tp:
                print("SL/TP verified.")
                return True

        except:
            pass

        print("SL/TP not confirmed.")
        return False
