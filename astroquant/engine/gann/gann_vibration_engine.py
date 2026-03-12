import math


class GannVibrationEngine:
    vibration_numbers = [3, 6, 9, 12, 18, 24, 27, 36, 45, 72, 90, 144, 180, 360]

    def price_vibration(self, price):
        try:
            value = float(price)
        except Exception:
            return None
        if value <= 0:
            return None
        return round(math.sqrt(value), 2)

    def check_vibration(self, price, tolerance=1.0):
        root = self.price_vibration(price)
        if root is None:
            return None
        tol = max(0.0, float(tolerance or 1.0))
        for number in self.vibration_numbers:
            if abs(root - float(number)) <= tol:
                return number
        return None

    def time_vibration(self, bars):
        try:
            value = int(bars)
        except Exception:
            return None
        return value if value in self.vibration_numbers else None
