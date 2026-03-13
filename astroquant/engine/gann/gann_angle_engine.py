class GannAngleEngine:
    FAN_RATIOS = {
        "1x8": 1.0 / 8.0,
        "1x4": 1.0 / 4.0,
        "1x3": 1.0 / 3.0,
        "1x2": 1.0 / 2.0,
        "1x1": 1.0,
        "2x1": 2.0,
        "3x1": 3.0,
        "4x1": 4.0,
        "8x1": 8.0,
    }

    def fan_lines(self, anchor_price, bars_from_anchor, tick_size=1.0):
        try:
            anchor = float(anchor_price)
            bars = max(0.0, float(bars_from_anchor))
            step = max(0.00001, float(tick_size))
        except Exception:
            return {}

        lines = {}
        for label, ratio in self.FAN_RATIOS.items():
            slope = step * float(ratio)
            lines[label] = anchor + (slope * bars)
        return lines

    def classify(self, price, lines, tick_size=1.0, tolerance_factor=1.5):
        try:
            value = float(price)
        except Exception:
            return {"angle": None, "distance": None, "aligned": False}

        if not lines:
            return {"angle": None, "distance": None, "aligned": False}

        nearest_angle = None
        nearest_distance = None
        for label, line_price in lines.items():
            try:
                distance = abs(value - float(line_price))
            except Exception:
                continue
            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance
                nearest_angle = label

        if nearest_distance is None:
            return {"angle": None, "distance": None, "aligned": False}

        tol = max(0.00001, float(tick_size) * max(0.1, float(tolerance_factor)))
        return {
            "angle": nearest_angle,
            "distance": round(float(nearest_distance), 6),
            "aligned": bool(nearest_distance <= tol),
        }