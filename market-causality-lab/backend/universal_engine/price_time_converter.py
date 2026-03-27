"""Price-Time Converter — Gann square root method for price↔degree conversion."""
from __future__ import annotations
import math

_PHI = 1.6180339887


def price_to_degree(price: float) -> float:
    """
    Convert price to Gann degree via square root formula:
        degree = (sqrt(price) * 180) mod 360
    """
    if price <= 0:
        return 0.0
    return round((math.sqrt(price) * 180.0) % 360.0, 4)


def degree_to_price(degree: float) -> float:
    """
    Inverse: convert a Gann degree back to a price level:
        price = (degree / 180) ^ 2
    """
    return round((degree / 180.0) ** 2, 5)


def price_time_equality(
    price_move: float,
    time_bars: int,
    price_scale: float = 1.0,
    time_scale: float = 1.0,
    tolerance: float = 0.05,
) -> dict:
    """
    Test Gann's universal law: price move == time move (scaled).
    Both sides can be scaled to match units (e.g. dollars vs hourly bars).
    """
    scaled_price = abs(price_move) * price_scale
    scaled_time = abs(time_bars) * time_scale
    if scaled_time == 0:
        return {"equal": False, "ratio": None, "status": "UNDEFINED", "price_deg": 0.0}

    ratio = round(scaled_price / scaled_time, 4)
    deviation = abs(ratio - 1.0)
    equal = deviation <= tolerance

    if equal:
        status = "BALANCED"
    elif ratio > 1.0 + tolerance:
        status = "PRICE_LEADS"
    else:
        status = "TIME_LEADS"

    return {
        "equal": equal,
        "ratio": ratio,
        "deviation_pct": round(deviation * 100.0, 2),
        "status": status,
        "price_deg": price_to_degree(abs(price_move) + 1.0),
    }


def square_of_nine(value: float, steps: int = 4) -> list[float]:
    """
    Gann Square of Nine: compute surrounding price levels stepping out from value.
    Each step moves 0.5 units along the square root spiral.
    Returns sorted list of nearby key levels.
    """
    sqrt_v = math.sqrt(max(value, 0.0001))
    levels = []
    for i in range(-steps, steps + 1):
        if i == 0:
            continue
        candidate = (sqrt_v + i * 0.5) ** 2
        if candidate > 0:
            levels.append(round(candidate, 2))
    return sorted(levels)
