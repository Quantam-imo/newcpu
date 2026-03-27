class PositionDetector:
    def __init__(self, page, logger):
        self.page = page
        self.logger = logger

    def get_frame(self):
        for frame in self.page.frames:
            if "trade" in frame.url or "platform" in frame.url:
                return frame
        return self.page

    def detect_position(self):
        frame = self.get_frame()

        try:
            # Look for position table or text
            if frame.locator("text=Positions").count() > 0:

                # Check BUY
                if frame.locator("text=Buy").count() > 0:
                    return "BUY"

                # Check SELL
                if frame.locator("text=Sell").count() > 0:
                    return "SELL"

            return None

        except Exception as e:
            self.logger(f"Position detection error: {e}")
            return None
