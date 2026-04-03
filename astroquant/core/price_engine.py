"""
AstroQuant Core Price Engine
Fundamental price-level and degree-conversion utilities.
Works alongside the richer GannSquareOf9Engine and Gann360WheelEngine
for quick scalar checks without instantiating full engine objects.
"""
import numpy as np


def price_to_degree(price: float) -> float:
    """
    Map a price value into its Gann 360-degree wheel position.
    Uses modulus-360 for a simple linear mapping (distinct from the
    sqrt-based mapping in Gann360WheelEngine — both are valid contexts).
    """
    return float(price) % 360.0


def degree_to_price(degree: float, base: float = 360.0) -> float:
    """Convert a degree back to a price offset from base."""
    return float(base) + float(degree)


def measured_move(prev_move: float) -> float:
    """
    Return a measured-move projection equal to the prior swing.
    Classic Gann/TA equal-swing assumption.
    """
    return float(prev_move)


def price_range(high: float, low: float) -> float:
    """Return the raw price range of a bar or swing."""
    return float(high) - float(low)


def square_price(price: float) -> float:
    """Square-of-price value — mirrors the Gann square-of-time concept."""
    return float(price) ** 2
