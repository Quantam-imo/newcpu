import math


class GannSpiralEngine:
    def coordinates(self, value):
        try:
            raw = max(0.0, float(value))
        except Exception:
            return {"x": None, "y": None, "theta": None, "radius": None}

        radius = math.sqrt(raw)
        theta = (radius % 1.0) * (2.0 * math.pi)
        x = radius * math.cos(theta)
        y = radius * math.sin(theta)
        return {
            "x": round(x, 6),
            "y": round(y, 6),
            "theta": round(theta, 6),
            "radius": round(radius, 6),
        }

    def next_turn_level(self, value, quarter_turns=1):
        try:
            raw = max(0.0, float(value))
            qt = float(quarter_turns)
        except Exception:
            return None

        root = math.sqrt(raw)
        projected = max(0.0, root + (0.5 * qt))
        return round(projected * projected, 6)
