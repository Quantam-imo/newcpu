"""
AstroQuant Core Geometry Engine
Gann fan angles, fan levels, and Square-of-9 proximity levels.
Provides lightweight scalar helpers; for full fan-line tracking use
GannAngleEngine and GannSquareOf9Engine in astroquant/engine/gann/.
"""
import numpy as np


def gann_angles(price: float, time: float) -> float:
    """
    Compute the raw price/time ratio (the 1x1 angle gradient).
    Returns 0 when time is zero to avoid division by zero.
    """
    t = float(time)
    if t == 0.0:
        return 0.0
    return float(price) / t


def generate_fan_levels(base_price: float) -> dict[str, float]:
    """
    Generate the three primary Gann fan price levels from a base price.
    Returns 1x1 (at price), 2x1 (double), and 1x2 (half) levels.
    """
    p = float(base_price)
    return {
        "1x1": p,
        "2x1": p * 2.0,
        "1x2": p / 2.0,
    }


def square_of_9_levels(price: float) -> list[float]:
    """
    Return seven Square-of-9 price levels around the given price.
    Offsets applied to sqrt(price) in steps of ±1, then re-squared.
    Matches the core logic used inside GannSquareOf9Engine.
    """
    root = np.sqrt(float(price))
    return [round((root + i) ** 2, 4) for i in range(-3, 4)]
