import math


class GannSquareOf9Engine:
    def _root(self, value):
        try:
            raw = max(0.0, float(value))
        except Exception:
            return None
        return math.sqrt(raw)

    def level(self, value, root_offset):
        base = self._root(value)
        if base is None:
            return None
        try:
            offset = float(root_offset)
        except Exception:
            offset = 0.0
        projected = max(0.0, base + offset)
        return round(projected * projected, 6)

    def nearest(self, price):
        try:
            value = float(price)
        except Exception:
            return {"level": None, "distance": None, "bias": "NEUTRAL"}

        offsets = [-0.5, -0.25, -0.125, 0.0, 0.125, 0.25, 0.5]
        levels = []
        for offset in offsets:
            level = self.level(value, offset)
            if level is None:
                continue
            levels.append((level, abs(value - level)))

        if not levels:
            return {"level": None, "distance": None, "bias": "NEUTRAL"}

        nearest_level, nearest_distance = min(levels, key=lambda item: item[1])
        if value > nearest_level:
            bias = "ABOVE"
        elif value < nearest_level:
            bias = "BELOW"
        else:
            bias = "AT_LEVEL"

        return {
            "level": nearest_level,
            "distance": round(float(nearest_distance), 6),
            "bias": bias,
        }
