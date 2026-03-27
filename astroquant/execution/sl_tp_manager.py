class SLTPManager:
    def __init__(self, page, logger):
        self.page = page
        self.logger = logger

    def get_frame(self):
        for frame in self.page.frames:
            if "trade" in frame.url or "platform" in frame.url:
                return frame
        return self.page

    def set_sl_tp(self, sl, tp):
        frame = self.get_frame()

        try:
            # Find SL input
            sl_box = frame.locator("input[placeholder*='SL']").first
            sl_box.fill(str(sl))

            # Find TP input
            tp_box = frame.locator("input[placeholder*='TP']").first
            tp_box.fill(str(tp))

            # Confirm
            save_btn = frame.locator("text=Save").first
            save_btn.click()

            self.logger(f"SL/TP set: SL={sl}, TP={tp}")
            return "SUCCESS"

        except Exception as e:
            self.logger(f"SL/TP error: {e}")
            self.page.screenshot(path="sl_tp_error.png")
            return "FAILED"
