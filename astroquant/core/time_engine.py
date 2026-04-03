"""
AstroQuant Core Time Engine
Gann time-cycle detection and square-of-time utilities.
Integrates with the broader AstroQuant engine architecture.
"""
import numpy as np

GANN_CYCLES = [3, 6, 9, 45, 90, 180, 360]


def time_from_extreme(current_index: int, swing_index: int) -> int:
    """Return the number of bars elapsed since the last swing extreme."""
    return int(current_index) - int(swing_index)


def detect_time_cycle(time_count: int) -> list[int]:
    """
    Return all Gann cycle values that evenly divide into time_count.
    A non-empty result signals a potential cycle-based turning point.
    """
    t = int(time_count)
    return [c for c in GANN_CYCLES if t > 0 and t % c == 0]


def square_time(time_units: float) -> float:
    """Square-of-time value — mirrors the Gann square-of-price concept."""
    return float(time_units) ** 2


def time_window(event_time: int, tolerance: int = 2) -> range:
    """
    Return the inclusive index window around a projected time event.
    Used to check whether the current bar is 'close enough' to a cycle pivot.
    """
    t = int(event_time)
    tol = max(0, int(tolerance))
    return range(t - tol, t + tol + 1)
