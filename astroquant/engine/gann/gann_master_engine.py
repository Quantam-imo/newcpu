import math

from engine.gann.gann_144_engine import Gann144Engine
from engine.gann.gann_360_wheel_engine import Gann360WheelEngine
from engine.gann.gann_cross_engine import GannCrossEngine
from engine.gann.gann_hexagon_engine import GannHexagonEngine
from engine.gann.gann_master_cycle_engine import GannMasterCycleEngine
from engine.gann.gann_square_engine import GannSquareEngine
from engine.gann.gann_trendline_engine import GannTrendlineEngine
from engine.gann.gann_vibration_engine import GannVibrationEngine


class GannMasterEngine:
    def __init__(self):
        self.cycle_144 = Gann144Engine()
        self.wheel = Gann360WheelEngine()
        self.cross = GannCrossEngine()
        self.hexagon = GannHexagonEngine()
        self.master_cycle = GannMasterCycleEngine()
        self.square = GannSquareEngine()
        self.trendline = GannTrendlineEngine()
        self.vibration = GannVibrationEngine()

    def _to_float(self, value, default=None):
        try:
            return float(value)
        except Exception:
            return default

    def analyze(self, candles):
        seq = list(candles or [])
        if len(seq) < 8:
            return {
                "score": 0,
                "confidence": 0.0,
                "signals": {},
                "reason": "insufficient_data",
            }

        last = seq[-1]
        prev = seq[-2]

        close = self._to_float(last.get("close"), 0.0) or 0.0
        prev_close = self._to_float(prev.get("close"), close) or close
        low = self._to_float(last.get("low"), close) or close
        high = self._to_float(last.get("high"), close) or close
        bars = len(seq)

        price_move = abs(close - self._to_float(seq[0].get("close"), close))
        time_move = float(bars)
        degree = self.wheel.price_to_degree(close)
        key_degree = self.wheel.key_degree(degree)
        cross_type = self.cross.classify(degree)
        vib = self.vibration.check_vibration(close)
        vib_time = self.vibration.time_vibration(bars)
        cycle_144 = self.cycle_144.check_cycle(bars)
        cycle_master = self.master_cycle.check(bars)
        is_square = self.square.is_square(int(round(close)))
        hex_hit = self.hexagon.check(vib if vib is not None else 0, tolerance=0.5)
        price_time_alignment = self.wheel.check_alignment(price_move, time_move, tolerance=8.0)

        angle_step = max(0.01, abs(high - low))
        support = self.trendline.support(close, angle_step)
        resistance = self.trendline.resistance(close, angle_step)

        score = 0
        if key_degree is not None:
            score += 2
        if cross_type == "CARDINAL":
            score += 2
        elif cross_type == "ORDINAL":
            score += 1
        if vib is not None:
            score += 2
        if vib_time is not None:
            score += 1
        if cycle_144:
            score += 2
        if cycle_master:
            score += 1
        if is_square:
            score += 1
        if hex_hit:
            score += 1
        if price_time_alignment:
            score += 2

        confidence = min(92.0, 48.0 + (float(score) * 3.2))
        direction = "BUY" if close >= prev_close else "SELL"

        return {
            "score": int(score),
            "confidence": round(confidence, 2),
            "direction": direction,
            "signals": {
                "degree": round(float(degree), 2) if degree is not None else None,
                "key_degree": key_degree,
                "cross": cross_type,
                "vibration": vib,
                "time_vibration": vib_time,
                "cycle_144": cycle_144,
                "master_cycle": cycle_master,
                "square_level": is_square,
                "hexagon": hex_hit,
                "price_time_alignment": price_time_alignment,
                "support": round(float(support), 5) if support is not None else None,
                "resistance": round(float(resistance), 5) if resistance is not None else None,
            },
        }
