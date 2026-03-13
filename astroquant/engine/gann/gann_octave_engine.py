import math


class GannOctaveEngine:
    def levels(self, price):
        try:
            value = float(price)
        except Exception:
            return {"levels": [], "step": None, "index": None}

        if value <= 0:
            return {"levels": [], "step": None, "index": None}

        magnitude = 10 ** int(math.floor(math.log10(value)))
        step = max(magnitude / 8.0, 0.00001)
        center = round(value / step) * step
        base = center - (4.0 * step)
        levels = [base + (i * step) for i in range(9)]

        index = 0
        for i in range(8):
            if levels[i] <= value <= levels[i + 1]:
                index = i
                break

        return {
            "levels": [round(v, 6) for v in levels],
            "step": round(step, 6),
            "index": int(index),
            "zone": "upper" if index >= 4 else "lower",
        }
