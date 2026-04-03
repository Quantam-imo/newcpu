"""
AstroQuant Math Utilities
Shared numeric helpers used across core, advanced, and execution engines.
"""
import math


def safe_sqrt(value: float) -> float:
    """Return sqrt of value, clamped to 0 for negative inputs."""
    try:
        return math.sqrt(max(0.0, float(value)))
    except Exception:
        return 0.0


def safe_divide(numerator: float, denominator: float, fallback: float = 0.0) -> float:
    """Return numerator / denominator, or fallback when denominator is zero."""
    try:
        d = float(denominator)
        if d == 0.0:
            return float(fallback)
        return float(numerator) / d
    except Exception:
        return float(fallback)


def round_to_tick(price: float, tick_size: float) -> float:
    """Round price to the nearest tick_size increment."""
    t = max(1e-10, float(tick_size))
    return round(round(float(price) / t) * t, 10)


def pct_change(current: float, previous: float) -> float:
    """Return percentage change from previous to current."""
    if previous == 0.0:
        return 0.0
    return ((float(current) - float(previous)) / abs(float(previous))) * 100.0


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp value to the [lo, hi] range."""
    return max(float(lo), min(float(hi), float(value)))


def degree_distance(a: float, b: float) -> float:
    """
    Shortest angular distance between two degree values on a 360-degree circle.
    Result is always in [0, 180].
    """
    diff = abs(float(a) % 360.0 - float(b) % 360.0)
    return min(diff, 360.0 - diff)
