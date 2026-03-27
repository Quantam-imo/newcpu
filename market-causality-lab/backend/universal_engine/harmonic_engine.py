"""Harmonic Engine — wave ratio patterns, AB=CD, Fibonacci harmonic projections."""
from __future__ import annotations

PHI = 1.6180339887
INV_PHI = 0.6180339887

# Named harmonic price levels with tolerance matching
_HARMONIC_LEVELS: dict[str, float] = {
    "0.236": 0.236,
    "0.382": 0.382,
    "0.500": 0.500,
    "0.618": INV_PHI,
    "0.707": 0.7071,
    "0.786": 0.786,
    "0.886": 0.886,
    "1.000": 1.000,
    "1.272": 1.272,
    "1.414": 1.4142,
    "1.618 (PHI)": PHI,
    "2.000": 2.000,
    "2.618": 2.618,
    "3.618": 3.618,
}

# Harmonic pattern ratios (XA retracement for AB leg)
_PATTERN_RATIOS: dict[str, dict[str, float]] = {
    "gartley": {"xa_ab": 0.618, "ab_bc": 0.382, "cd_target": 0.786},
    "bat": {"xa_ab": 0.886, "ab_bc": 0.500, "cd_target": 0.886},
    "butterfly": {"xa_ab": 0.786, "ab_bc": 0.382, "cd_target": 1.618},
    "crab": {"xa_ab": 0.618, "ab_bc": 0.382, "cd_target": 3.618},
    "cypher": {"xa_ab": 0.382, "ab_bc": 0.618, "cd_target": 0.786},
}


def harmonic_ratio(move1: float, move2: float) -> dict:
    """
    Compute ratio between two consecutive price moves and identify nearest
    named harmonic level (Fibonacci/golden ratio relationship).
    """
    if move1 == 0:
        return {"ratio": None, "nearest_level": "N/A", "deviation_pct": 0.0, "pattern": "UNDEFINED"}

    ratio = round(abs(move2 / move1), 4)
    nearest_label = min(_HARMONIC_LEVELS, key=lambda k: abs(_HARMONIC_LEVELS[k] - ratio))
    nearest_val = _HARMONIC_LEVELS[nearest_label]
    deviation = round(abs(ratio - nearest_val) / nearest_val * 100.0, 2) if nearest_val else 0.0
    pattern = "HARMONIC" if deviation < 5.0 else "NON_HARMONIC"

    return {
        "ratio": ratio,
        "nearest_level": nearest_label,
        "deviation_pct": deviation,
        "pattern": pattern,
    }


def detect_abcd(leg_ab: float, leg_cd: float, tolerance: float = 0.05) -> dict:
    """
    AB=CD harmonic pattern detector.
    Legs AB and CD should be equal or phi-related for a valid pattern.
    """
    if leg_ab == 0:
        return {"ab_cd": False, "ratio": None, "type": "UNDEFINED"}

    ratio = round(abs(leg_cd / leg_ab), 4)
    equal = abs(ratio - 1.0) <= tolerance
    phi_ext = abs(ratio - PHI) <= tolerance
    inv_phi = abs(ratio - INV_PHI) <= tolerance

    if equal:
        pattern_type = "AB=CD"
    elif phi_ext:
        pattern_type = "AB=CD_PHI_EXT"
    elif inv_phi:
        pattern_type = "AB=CD_INV_PHI"
    else:
        pattern_type = "NONE"

    return {
        "ab_cd": equal or phi_ext,
        "ratio": ratio,
        "type": pattern_type,
    }


def _simple_pivots(closes, window: int = 2) -> list[tuple[str, float]]:
    """Extract local swing highs and lows from a numpy-like array."""
    pivots = []
    n = len(closes)
    for i in range(window, n - window):
        if all(closes[i] >= closes[i - j] for j in range(1, window + 1)) and \
           all(closes[i] >= closes[i + j] for j in range(1, window + 1)):
            pivots.append(("H", float(closes[i])))
        elif all(closes[i] <= closes[i - j] for j in range(1, window + 1)) and \
             all(closes[i] <= closes[i + j] for j in range(1, window + 1)):
            pivots.append(("L", float(closes[i])))
    return pivots


def harmonic_analysis(df) -> dict:
    """
    Full harmonic analysis using recent OHLCV data.
    Detects swing structure, computes XA/AB/BC legs, checks AB=CD and extensions.
    """
    closes = df["close"].tail(60).to_numpy(dtype=float)
    n = len(closes)

    if n < 12:
        return {"status": "INSUFFICIENT_DATA", "pivots_found": n}

    pivots = _simple_pivots(closes, window=2)

    if len(pivots) < 4:
        return {"status": "FEW_PIVOTS", "pivots_found": len(pivots)}

    x_val = pivots[-4][1]
    a_val = pivots[-3][1]
    b_val = pivots[-2][1]
    c_val = pivots[-1][1]

    xa = abs(a_val - x_val)
    ab = abs(b_val - a_val)
    bc = abs(c_val - b_val)

    ab_xa = harmonic_ratio(xa, ab)
    bc_ab = harmonic_ratio(ab, bc)
    abcd = detect_abcd(ab, bc)

    # D-point extension projections
    d_up = round(c_val + bc * PHI, 2)
    d_down = round(c_val - bc * PHI, 2)

    return {
        "status": "OK",
        "pivots_found": len(pivots),
        "xa_move": round(xa, 4),
        "ab_move": round(ab, 4),
        "bc_move": round(bc, 4),
        "ab_xa_ratio": ab_xa,
        "bc_ab_ratio": bc_ab,
        "abcd_pattern": abcd,
        "d_extension_up": d_up,
        "d_extension_down": d_down,
    }
