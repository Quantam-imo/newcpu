"""Math Engine — Fibonacci levels, golden ratio targets, and geometric price structure."""
from __future__ import annotations

PHI = 1.6180339887
INV_PHI = 0.6180339887
SQRT2 = 1.41421356
SQRT3 = 1.73205080

FIB_RETRACEMENTS = [0.0, 0.236, 0.382, 0.500, 0.618, 0.786, 1.0]
FIB_EXTENSIONS = [1.0, 1.272, 1.414, 1.618, 2.0, 2.618, 3.618]


def fib_levels(swing_high: float, swing_low: float) -> dict:
    """Fibonacci retracement and extension levels from a swing range."""
    rng = swing_high - swing_low
    retracements = {
        f"fib_{int(r * 100)}": round(swing_high - rng * r, 5)
        for r in FIB_RETRACEMENTS
    }
    extensions = {
        f"ext_{int(e * 100)}": round(swing_low + rng * e, 5)
        for e in FIB_EXTENSIONS
    }
    return {
        "swing_high": swing_high,
        "swing_low": swing_low,
        "range": round(rng, 5),
        "retracements": retracements,
        "extensions": extensions,
    }


def golden_ratio_targets(price: float, direction: str = "UP") -> dict:
    """Price projection targets using golden ratio from current price."""
    if direction.upper() == "UP":
        return {
            "phi_0618": round(price * INV_PHI, 5),
            "phi_1618": round(price * PHI, 5),
            "phi_2618": round(price * (PHI ** 2), 5),
            "phi_4236": round(price * (PHI ** 3), 5),
        }
    return {
        "phi_0618": round(price * INV_PHI, 5),
        "phi_0382": round(price * (1 - INV_PHI), 5),
        "phi_0236": round(price * (INV_PHI ** 2), 5),
        "phi_0146": round(price * (INV_PHI ** 3), 5),
    }


def geometric_mean(a: float, b: float) -> float:
    """Geometric mean of two values."""
    return round((abs(a) * abs(b)) ** 0.5, 5)


def squared_range(price: float) -> dict:
    """Gann-style square numbers bracketing price."""
    sqrt_p = price ** 0.5
    floor_root = int(sqrt_p)
    floor_sq = float(floor_root ** 2)
    ceil_sq = float((floor_root + 1) ** 2)
    return {
        "floor_square": floor_sq,
        "ceil_square": ceil_sq,
        "price_sqrt": round(sqrt_p, 5),
        "distance_to_floor": round(price - floor_sq, 5),
        "distance_to_ceil": round(ceil_sq - price, 5),
    }
