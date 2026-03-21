import math

from astroquant.engine.gann.gann_144_engine import Gann144Engine
from astroquant.engine.gann.gann_360_wheel_engine import Gann360WheelEngine
from astroquant.engine.gann.gann_angle_engine import GannAngleEngine
from astroquant.engine.gann.gann_cross_engine import GannCrossEngine
from astroquant.engine.gann.gann_hexagon_engine import GannHexagonEngine
from astroquant.engine.gann.gann_master_cycle_engine import GannMasterCycleEngine
from astroquant.engine.gann.gann_octave_engine import GannOctaveEngine
from astroquant.engine.gann.gann_planet_alignment_engine import GannPlanetAlignmentEngine
from astroquant.engine.gann.gann_price_time_engine import GannPriceTimeEngine
from astroquant.engine.gann.gann_spiral_engine import GannSpiralEngine
from astroquant.engine.gann.gann_spiral_vector_engine import GannSpiralVectorEngine
from astroquant.engine.gann.gann_square_engine import GannSquareEngine
from astroquant.engine.gann.gann_square_of_9_engine import GannSquareOf9Engine
from astroquant.engine.gann.gann_trendline_engine import GannTrendlineEngine
from astroquant.engine.gann.gann_vector_engine import GannVectorEngine
from astroquant.engine.gann.gann_vibration_engine import GannVibrationEngine


class GannMasterEngine:
    def __init__(self):
        self.cycle_144 = Gann144Engine()
        self.wheel = Gann360WheelEngine()
        self.angle = GannAngleEngine()
        self.cross = GannCrossEngine()
        self.hexagon = GannHexagonEngine()
        self.master_cycle = GannMasterCycleEngine()
        self.octave = GannOctaveEngine()
        self.planet = GannPlanetAlignmentEngine()
        self.price_time = GannPriceTimeEngine()
        self.spiral = GannSpiralEngine()
        self.spiral_vector = GannSpiralVectorEngine()
        self.square = GannSquareEngine()
        self.square9 = GannSquareOf9Engine()
        self.trendline = GannTrendlineEngine()
        self.vector = GannVectorEngine()
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
        timestamp = last.get("timestamp")

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
        square9 = self.square9.nearest(close)
        hex_hit = self.hexagon.check(vib if vib is not None else 0, tolerance=0.5)
        price_time_alignment = self.wheel.check_alignment(price_move, time_move, tolerance=8.0)
        price_time_eval = self.price_time.evaluate(price_move, bars, tolerance=0.25)
        vector_state = self.vector.summarize(seq, lookback=8)
        octave_state = self.octave.levels(close)
        planet_state = self.planet.evaluate(timestamp=timestamp, window_days=2)
        spiral_state = self.spiral.coordinates(close)
        spiral_vector_state = self.spiral_vector.resonance(close, bars)

        angle_step = max(0.01, abs(high - low))
        support = self.trendline.support(close, angle_step)
        resistance = self.trendline.resistance(close, angle_step)
        angle_lines = self.angle.fan_lines(low, bars, tick_size=angle_step)
        angle_state = self.angle.classify(close, angle_lines, tick_size=angle_step, tolerance_factor=1.0)

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
        if price_time_eval.get("aligned"):
            score += 2
        if angle_state.get("aligned"):
            score += 2
        if square9.get("distance") is not None and float(square9.get("distance") or 0.0) <= angle_step:
            score += 1
        if spiral_vector_state.get("aligned"):
            score += 1
        score += int(planet_state.get("score") or 0)

        confidence = min(92.0, 48.0 + (float(score) * 3.2))
        direction = "BUY" if close >= prev_close else "SELL"
        vector_direction = str(vector_state.get("direction") or "FLAT")
        if vector_direction == "UP":
            direction = "BUY"
        elif vector_direction == "DOWN":
            direction = "SELL"

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
                "square_of_9": square9,
                "hexagon": hex_hit,
                "price_time_alignment": price_time_alignment,
                "price_time": price_time_eval,
                "vector": vector_state,
                "octave": octave_state,
                "planet_alignment": planet_state,
                "spiral": spiral_state,
                "spiral_vector": spiral_vector_state,
                "angle": angle_state,
                "angle_lines": {k: round(float(v), 6) for k, v in angle_lines.items()},
                "support": round(float(support), 5) if support is not None else None,
                "resistance": round(float(resistance), 5) if resistance is not None else None,
            },
        }
