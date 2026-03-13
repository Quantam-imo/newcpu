import math


class GannVectorEngine:
    def summarize(self, candles, lookback=8):
        seq = list(candles or [])
        n = max(2, int(lookback))
        if len(seq) < n:
            return {
                "price_delta": 0.0,
                "time_delta": 0,
                "slope": 0.0,
                "angle_deg": 0.0,
                "direction": "FLAT",
            }

        window = seq[-n:]
        first = window[0]
        last = window[-1]
        try:
            start = float(first.get("close") or 0.0)
            end = float(last.get("close") or 0.0)
        except Exception:
            start = 0.0
            end = 0.0

        price_delta = end - start
        time_delta = max(1, len(window) - 1)
        slope = price_delta / float(time_delta)
        angle_deg = math.degrees(math.atan2(price_delta, float(time_delta)))

        direction = "FLAT"
        if price_delta > 0:
            direction = "UP"
        elif price_delta < 0:
            direction = "DOWN"

        return {
            "price_delta": round(price_delta, 6),
            "time_delta": int(time_delta),
            "slope": round(slope, 6),
            "angle_deg": round(angle_deg, 4),
            "direction": direction,
        }
