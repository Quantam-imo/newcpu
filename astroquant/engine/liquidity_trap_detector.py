from __future__ import annotations


class LiquidityTrapDetector:
    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    def detect(self, candles, lookback=20):
        seq = list(candles or [])[-max(3, int(lookback or 20)):]
        if len(seq) < 3:
            return {"trap": False, "side": "NONE", "reason": "insufficient_data"}

        highs = [self._to_float(c.get("high"), 0.0) for c in seq[:-1]]
        lows = [self._to_float(c.get("low"), 0.0) for c in seq[:-1]]
        last = seq[-1]
        h = self._to_float(last.get("high"), 0.0)
        l = self._to_float(last.get("low"), 0.0)
        o = self._to_float(last.get("open"), 0.0)
        c = self._to_float(last.get("close"), 0.0)

        ref_high = max(highs) if highs else 0.0
        ref_low = min(lows) if lows else 0.0

        stop_hunt_up = h > ref_high and c < ref_high
        stop_hunt_down = l < ref_low and c > ref_low

        if stop_hunt_up and c < o:
            return {
                "trap": True,
                "side": "SELL",
                "reason": "failed_breakout_above_range",
                "range_high": ref_high,
                "range_low": ref_low,
            }

        if stop_hunt_down and c > o:
            return {
                "trap": True,
                "side": "BUY",
                "reason": "failed_breakdown_below_range",
                "range_high": ref_high,
                "range_low": ref_low,
            }

        return {
            "trap": False,
            "side": "NONE",
            "reason": "no_trap",
            "range_high": ref_high,
            "range_low": ref_low,
        }
