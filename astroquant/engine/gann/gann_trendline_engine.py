class GannTrendlineEngine:
    def support(self, price, angle_step):
        try:
            return float(price) - float(angle_step)
        except Exception:
            return None

    def resistance(self, price, angle_step):
        try:
            return float(price) + float(angle_step)
        except Exception:
            return None
