class GannHexagonEngine:
    numbers = [6, 12, 24, 36, 72, 144]

    def check(self, value, tolerance=0.0):
        try:
            raw = float(value)
        except Exception:
            return False
        tol = max(0.0, float(tolerance or 0.0))
        for number in self.numbers:
            if abs(raw - float(number)) <= tol:
                return True
        return False
