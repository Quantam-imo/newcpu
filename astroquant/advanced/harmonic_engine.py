"""
AstroQuant Advanced Harmonic Engine
Square-root-of-2 and octave (powers-of-2) price level generators,
plus a confluence deduplication helper.

These harmonic ratios underpin Gann's musical / vibration concepts
where price subdivides and expands by sqrt(2) ≈ 1.4142 and 2x octaves.
"""
import math


def sqrt2_levels(price: float) -> list[float]:
    """
    Generate five price levels by scaling price by sqrt(2)^i for i in [-2, 2].

    Levels (approx multipliers):  0.5x, 0.707x, 1x, 1.414x, 2x
    """
    p = float(price)
    return [round(p * (math.sqrt(2) ** i), 6) for i in range(-2, 3)]


def octave_levels(price: float) -> list[float]:
    """
    Generate five price levels by scaling price by 2^i for i in [-2, 2].

    Levels: 0.25x, 0.5x, 1x, 2x, 4x
    """
    p = float(price)
    return [round(p * (2.0 ** i), 6) for i in range(-2, 3)]


def harmonic_confluence(levels: list[float]) -> list[float]:
    """
    Deduplicate and sort a combined list of harmonic levels.
    Use to identify price zones where multiple harmonic ratios converge.
    """
    return sorted(set(round(float(x), 4) for x in levels))
