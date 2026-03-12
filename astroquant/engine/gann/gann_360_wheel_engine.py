import math


class Gann360WheelEngine:
    key_levels = [45, 90, 135, 180, 225, 270, 315, 360]

    def price_to_degree(self, price):
        try:
            value = float(price)
        except Exception:
            return None
        if value <= 0:
            return None
        root = math.sqrt(value)
        return (root % 1.0) * 360.0

    def check_alignment(self, price_move, time_move, tolerance=5.0):
        try:
            p = float(price_move)
            t = float(time_move)
        except Exception:
            return False
        return abs(p - t) <= max(0.0, float(tolerance or 5.0))

    def key_degree(self, degree, tolerance=5.0):
        if degree is None:
            return None
        try:
            value = float(degree) % 360.0
        except Exception:
            return None
        tol = max(0.0, float(tolerance or 5.0))
        for level in self.key_levels:
            if abs(value - float(level % 360)) <= tol:
                return level
        return None
