import math


class GannSquareEngine:
    def is_square(self, number):
        try:
            value = float(number)
        except Exception:
            return False
        if value < 0:
            return False
        root = int(math.isqrt(int(round(value))))
        return root * root == int(round(value))
