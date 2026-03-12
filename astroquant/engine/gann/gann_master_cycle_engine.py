class GannMasterCycleEngine:
    cycles = [30, 45, 90, 120, 180, 360, 720]

    def check(self, bars):
        try:
            value = int(bars)
        except Exception:
            return False
        return value in self.cycles
