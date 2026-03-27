"""Advanced Gann Engine — price-time equality, degree cycle analysis, key angles."""
from __future__ import annotations
import math

GANN_ANGLES = {
    "1x8": 82.5,
    "1x4": 75.0,
    "1x3": 71.25,
    "1x2": 63.75,
    "1x1": 45.0,
    "2x1": 26.25,
    "3x1": 18.75,
    "4x1": 15.0,
    "8x1": 7.5,
}

CYCLE_QUADRANT_LABELS = {
    1: "ACCUMULATION",
    2: "MARKUP",
    3: "DISTRIBUTION",
    4: "MARKDOWN",
}


def price_to_degrees(price: float) -> float:
    """Convert price to Gann degrees via square root: (√price × 180) mod 360."""
    if price <= 0:
        return 0.0
    return round((math.sqrt(price) * 180) % 360, 4)


def degrees_to_price(degrees: float) -> float:
    """Inverse: convert Gann degrees back to a price level."""
    return round((degrees / 180) ** 2, 5)


def price_time_equality(
    price_move: float,
    time_move: float,
    tolerance: float = 0.05,
) -> dict:
    """
    Gann's core law: price move should equal time move.
    Returns equality status, ratio, and balance description.
    """
    if time_move == 0:
        return {"equal": False, "ratio": None, "status": "UNDEFINED"}
    ratio = round(price_move / time_move, 4)
    deviation = abs(ratio - 1.0)
    equal = deviation <= tolerance
    if equal:
        status = "BALANCED"
    elif ratio > 1.0:
        status = "PRICE_LEADS"
    else:
        status = "TIME_LEADS"
    return {"equal": equal, "ratio": ratio, "status": status}


def gann_cycle_position(price: float, high: float, low: float) -> dict:
    """Position within a Gann 360-degree price cycle (1 = accumulation, 4 = markdown)."""
    rng = high - low if high != low else 1.0
    pct = max(0.0, min(1.0, (price - low) / rng))
    degree = round(pct * 360, 2)
    quadrant = min(4, int(degree // 90) + 1)
    return {
        "cycle_degree": degree,
        "quadrant": quadrant,
        "description": CYCLE_QUADRANT_LABELS[quadrant],
    }


def nearest_gann_angles(degree: float) -> list[str]:
    """Find Gann angles within 10° of current degree position."""
    local_deg = degree % 90
    return [name for name, ang in GANN_ANGLES.items() if abs(ang - local_deg) < 10] or ["1x1"]


def gann_advanced_analysis(state: dict, df) -> dict:
    """Full advanced Gann analysis: degrees, cycle position, price-time equality, key levels."""
    price = float(state["price"])
    high = float(df["high"].tail(50).max())
    low = float(df["low"].tail(50).min())
    recent_high = float(df["high"].tail(20).max())
    recent_low = float(df["low"].tail(20).min())

    degrees = price_to_degrees(price)
    cycle = gann_cycle_position(price, high, low)
    pte = price_time_equality(recent_high - recent_low, 20)
    angles = nearest_gann_angles(degrees)

    # Key support/resistance at next 90-degree boundary
    floor_90 = (int(degrees) // 90) * 90
    ceil_90 = floor_90 + 90

    return {
        "degrees": degrees,
        "cycle": cycle,
        "price_time_equality": pte,
        "nearest_angles": angles,
        "support_90": round(degrees_to_price(float(floor_90)), 2),
        "resist_90": round(degrees_to_price(float(ceil_90)), 2),
        "swing_range": round(recent_high - recent_low, 4),
    }
