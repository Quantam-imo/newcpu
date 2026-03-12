class Gann144Engine:
    def check_cycle(self, bars):
        try:
            count = int(bars)
        except Exception:
            return False
        return count > 0 and (count % 144 == 0)
