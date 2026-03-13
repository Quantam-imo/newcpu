import math

from engine.gann.gann_spiral_engine import GannSpiralEngine


class GannSpiralVectorEngine:
    def __init__(self):
        self.spiral = GannSpiralEngine()

    def resonance(self, price, bars):
        p = self.spiral.coordinates(price)
        t = self.spiral.coordinates(bars)
        if p.get("x") is None or t.get("x") is None:
            return {"score": 0.0, "aligned": False}

        px, py = float(p["x"]), float(p["y"])
        tx, ty = float(t["x"]), float(t["y"])

        dot = (px * tx) + (py * ty)
        pm = math.sqrt((px * px) + (py * py))
        tm = math.sqrt((tx * tx) + (ty * ty))
        if pm <= 0 or tm <= 0:
            return {"score": 0.0, "aligned": False}

        cosine = max(-1.0, min(1.0, dot / (pm * tm)))
        score = (cosine + 1.0) / 2.0
        return {
            "score": round(score, 6),
            "aligned": bool(score >= 0.75),
        }
