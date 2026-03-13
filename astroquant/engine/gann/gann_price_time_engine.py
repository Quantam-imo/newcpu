class GannPriceTimeEngine:
    def evaluate(self, price_move, bars, tolerance=0.2):
        try:
            p = abs(float(price_move))
            t = max(1.0, float(bars))
            tol = max(0.0, float(tolerance))
        except Exception:
            return {"ratio": None, "aligned": False, "distance": None}

        ratio = p / t
        distance = abs(ratio - 1.0)
        return {
            "ratio": round(ratio, 6),
            "distance": round(distance, 6),
            "aligned": bool(distance <= tol),
        }

    def project_targets(self, bars_from_pivot):
        try:
            bars = max(1, int(bars_from_pivot))
        except Exception:
            return []
        factors = [1, 2, 3, 4]
        return [bars * f for f in factors]
