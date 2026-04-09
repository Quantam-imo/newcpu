"""
Gann Astro Lesson 2 — Law of Vibration: Node Engine

Nodes = PRESSURE POINTS (not price levels)

Core Rules:
  TIME hits node → MOVE
  PRICE hits node without TIME → NOISE
  Cycle completes at node, not at distance
  Spiral governs expansion

A Node is the convergence of:
  1. Time cycle at a completion point (0%, 33%, 67%, 100% of Tₛ)
  2. Price at a Gann geometric angle (0°, 45°, 90°, 135°, 180°, 225°, 270°, 315°)
  3. (Optional) Planetary body at a key harmonic degree

Node Hierarchy:
  MAJOR  — Time + Price + Planet     (all three align)
  MEDIUM — Time + Price              (two align)
  MINOR  — Time only OR Price only   (context: watch, don't trade)
  NOISE  — Price only, no time       (ignore)

The Price Delivery Algorithm measures cycle completion, not candle count.
Time is the cause; price is the consequence.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Gann geometric key angles (360° wheel)
GANN_KEY_ANGLES: List[float] = [0, 45, 90, 135, 180, 225, 270, 315, 360]

# Time-cycle node fractions (completion points within one Tₛ)
# 0 = start / rebirth, 1/3 ≈ initiation complete, 2/3 ≈ expansion peak, 1 = full cycle
TIME_NODE_FRACTIONS: List[float] = [0.0, 1/3, 2/3, 1.0]

# Tolerances
PRICE_ANGLE_ORB = 5.0      # degrees — price must be within this of a key angle
TIME_NODE_WINDOW = 0.06    # fraction — time must be within 6% of a node fraction
PLANET_ANGLE_ORB = 4.0     # degrees — planet longitude vs key Gann angle

# Planetary governors by timeframe
SWING_PLANETS = ["saturn", "jupiter", "mars", "venus"]      # slow planets
INTRADAY_ASCENDANT_DEG_PER_MIN = 0.25   # ~1° per 4 minutes

# Key Gann angles used for planetary alignment check
PLANET_KEY_ANGLES: List[float] = [0, 45, 90, 135, 180, 225, 270, 315]


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class NodeSignal:
    node_type: str           # MAJOR / MEDIUM / MINOR_TIME / NOISE
    active: bool             # True = valid trading node
    time_aligned: bool
    price_aligned: bool
    planet_aligned: bool
    price: float
    price_degree: float      # Gann wheel degree for this price
    nearest_key_angle: float
    price_angle_orb: float   # distance from nearest key angle
    time_fraction: float     # 0–1 through current Tₛ
    nearest_time_node: float # nearest TIME_NODE_FRACTION
    time_node_orb: float     # distance from nearest time node (fraction)
    aligning_planets: List[Dict]
    planetary_governor: str  # dominant planetary ruler
    message: str
    rule: str                # Core rule that fires
    timestamp: str


@dataclass
class AscendantState:
    degree: float            # current Ascendant degree (0–360)
    degree_per_min: float    # ~0.25°/min
    minutes_to_next_90: float
    minutes_to_next_key: float
    next_key_angle: float


# ── Price → Gann wheel degree ─────────────────────────────────────────────────

def price_to_gann_degree(price: float) -> float:
    """Convert price to a Gann 360° wheel degree via square root method.
    Same as Gann360WheelEngine.price_to_degree but returns raw float.
    """
    if price <= 0:
        return 0.0
    root = math.sqrt(price)
    return (root % 1.0) * 360.0


def nearest_key_angle(degree: float) -> tuple[float, float]:
    """Return (nearest_key_angle, orb) for a given degree."""
    best = min(GANN_KEY_ANGLES, key=lambda k: min(abs(degree - k), 360 - abs(degree - k)))
    orb = min(abs(degree - best), 360 - abs(degree - best))
    return best % 360, round(orb, 2)


# ── Node computation ──────────────────────────────────────────────────────────

def _classify_node(time_aligned: bool, price_aligned: bool, planet_aligned: bool) -> tuple[str, bool]:
    """Return (node_type, active_flag)."""
    if time_aligned and price_aligned and planet_aligned:
        return "MAJOR", True
    if time_aligned and price_aligned:
        return "MEDIUM", True
    if time_aligned and not price_aligned:
        return "MINOR_TIME", False  # watch only
    if price_aligned and not time_aligned:
        return "NOISE", False       # price without time = noise
    return "NONE", False


def _rule_text(node_type: str, time_aligned: bool, price_aligned: bool) -> str:
    if node_type == "MAJOR":
        return "TIME + PRICE + PLANET aligned → HIGH PROBABILITY node. Execute when bar confirms."
    if node_type == "MEDIUM":
        return "TIME + PRICE aligned → MEDIUM node. Wait for planetary confirmation or bar close."
    if node_type == "MINOR_TIME":
        return "TIME at node, price not yet at angle. Watch for price to reach geometric level."
    if node_type == "NOISE":
        return "Price at Gann angle but TIME cycle not at node → NOISE. Do not trade."
    return "No alignment detected. Wait for convergence."


def compute_node(
    price: float,
    time_fraction: float,
    planetary_positions: Optional[Dict[str, float]] = None,
    timeframe: str = "swing",
) -> NodeSignal:
    """Compute node state for current price and time position.

    Args:
        price: current market price
        time_fraction: elapsed fraction of current Tₛ cycle (0.0–1.0)
        planetary_positions: dict of {planet_name: ecliptic_longitude} (degrees)
        timeframe: 'swing' or 'intraday' — selects planetary governor

    Returns:
        NodeSignal with full node classification
    """
    deg = price_to_gann_degree(price)
    key_ang, ang_orb = nearest_key_angle(deg)
    price_aligned = ang_orb <= PRICE_ANGLE_ORB

    # Time alignment
    nearest_tn = min(TIME_NODE_FRACTIONS, key=lambda n: abs(time_fraction - n))
    tn_orb = abs(time_fraction - nearest_tn)
    time_aligned = tn_orb <= TIME_NODE_WINDOW

    # Planetary alignment
    aligning_planets: List[Dict] = []
    gov_planets = SWING_PLANETS if timeframe == "swing" else ["moon", "mercury"]
    planetary_governor = "saturn/jupiter" if timeframe == "swing" else "ascendant"

    if planetary_positions:
        for planet, lon in planetary_positions.items():
            if planet not in gov_planets:
                continue
            for ka in PLANET_KEY_ANGLES:
                diff = min(abs(lon % 360 - ka), 360 - abs(lon % 360 - ka))
                if diff <= PLANET_ANGLE_ORB:
                    aligning_planets.append({
                        "planet": planet,
                        "longitude": round(lon, 2),
                        "key_angle": ka,
                        "orb": round(diff, 2),
                    })
                    break
    planet_aligned = len(aligning_planets) > 0

    node_type, active = _classify_node(time_aligned, price_aligned, planet_aligned)
    rule = _rule_text(node_type, time_aligned, price_aligned)

    msg_parts = []
    if time_aligned:
        msg_parts.append(f"Time at node {nearest_tn:.2f} (orb {tn_orb:.3f})")
    if price_aligned:
        msg_parts.append(f"Price {price:.2f} → {deg:.1f}° near key {key_ang}° (orb {ang_orb:.1f}°)")
    if planet_aligned:
        msg_parts.append(f"Planet(s) at key angle: {[p['planet'] for p in aligning_planets]}")
    if not msg_parts:
        msg_parts.append("No node alignment — stand aside")

    return NodeSignal(
        node_type=node_type,
        active=active,
        time_aligned=time_aligned,
        price_aligned=price_aligned,
        planet_aligned=planet_aligned,
        price=price,
        price_degree=round(deg, 2),
        nearest_key_angle=key_ang,
        price_angle_orb=ang_orb,
        time_fraction=round(time_fraction, 4),
        nearest_time_node=nearest_tn,
        time_node_orb=round(tn_orb, 4),
        aligning_planets=aligning_planets,
        planetary_governor=planetary_governor,
        message=" | ".join(msg_parts),
        rule=rule,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ── Ascendant intraday timing ─────────────────────────────────────────────────

def compute_ascendant_state(
    ref_degree: float = 0.0,
    ref_time: Optional[datetime] = None,
) -> AscendantState:
    """Track intraday Ascendant position and minutes to next key angle.

    The Ascendant moves ~0.25°/minute (1° per 4 minutes = 360° per 24 hours).
    Intraday Gann Astro rule: Ascendant governs intraday timing.

    Args:
        ref_degree: Ascendant degree at ref_time (default: compute from Swiss Ephemeris)
        ref_time: reference datetime (default: now UTC)
    """
    try:
        import swisseph as swe
        now = datetime.now(timezone.utc) if ref_time is None else ref_time
        jd = swe.julday(now.year, now.month, now.day,
                        now.hour + now.minute / 60.0 + now.second / 3600.0)
        # Ascendant at 0° geographic longitude (UTC reference)
        cusps, ascmc = swe.houses(jd, 0.0, 0.0, b"P")
        asc_deg = ascmc[0] % 360.0
    except Exception:
        # Fallback: use time-based approximation
        now = datetime.now(timezone.utc) if ref_time is None else ref_time
        minutes_since_midnight = now.hour * 60 + now.minute
        asc_deg = (minutes_since_midnight * INTRADAY_ASCENDANT_DEG_PER_MIN) % 360.0

    # Minutes to each key angle
    key_times = []
    for ka in PLANET_KEY_ANGLES:
        diff_deg = (ka - asc_deg) % 360.0
        mins = diff_deg / INTRADAY_ASCENDANT_DEG_PER_MIN
        key_times.append((ka, mins))
    key_times.sort(key=lambda x: x[1])
    next_key, mins_to_next = key_times[0]

    # Minutes to next 90° boundary
    next_90_deg = (math.ceil(asc_deg / 90) * 90) % 360
    diff_90 = (next_90_deg - asc_deg) % 360.0 or 360.0
    mins_to_90 = diff_90 / INTRADAY_ASCENDANT_DEG_PER_MIN

    return AscendantState(
        degree=round(asc_deg, 2),
        degree_per_min=INTRADAY_ASCENDANT_DEG_PER_MIN,
        minutes_to_next_90=round(mins_to_90, 1),
        minutes_to_next_key=round(mins_to_next, 1),
        next_key_angle=next_key,
    )


# ── Vibration frequency analysis ─────────────────────────────────────────────

def price_vibration_frequency(price: float) -> Dict:
    """Compute vibration properties of a price level.

    Law of Vibration: every price carries an intrinsic frequency.
    √price = vibration number.
    Harmonic resonance occurs when √price is near 3, 6, 9, 18, 36, 45, 90, 180.
    """
    if price <= 0:
        return {"price": price, "root": None, "resonance": None, "chakra_369": None}

    root = math.sqrt(price)
    root_mod9 = root % 9

    # Check 3-6-9 resonance
    chakra_369 = None
    for divisor in [3, 6, 9]:
        if abs(root % divisor) <= 0.15 or abs(root % divisor - divisor) <= 0.15:
            chakra_369 = divisor
            break

    # Harmonic resonance numbers
    RESONANCE_NUMS = [3, 6, 9, 12, 18, 24, 27, 36, 45, 72, 90, 144, 180, 360]
    resonance = None
    min_dist = float("inf")
    for n in RESONANCE_NUMS:
        d = abs(root - n)
        if d < min_dist:
            min_dist = d
            resonance = n
    resonance_orb = round(min_dist, 4)
    resonance_active = resonance_orb <= 0.5

    # Digital root (Pythagorean reduction)
    digits = [int(c) for c in str(int(round(price))) if c.isdigit()]
    digital_root = sum(digits)
    while digital_root > 9:
        digital_root = sum(int(c) for c in str(digital_root))

    return {
        "price": price,
        "root": round(root, 4),
        "root_mod9": round(root_mod9, 4),
        "chakra_369": chakra_369,
        "resonance_number": resonance,
        "resonance_orb": resonance_orb,
        "resonance_active": resonance_active,
        "digital_root": digital_root,
        "digital_root_369": digital_root in (3, 6, 9),
    }
