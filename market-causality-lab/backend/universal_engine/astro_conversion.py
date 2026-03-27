"""Astro Conversion Engine — planetary degree to time, Nakshatra mapping."""
from __future__ import annotations

# 27 Nakshatras, each span = 360 / 27 = 13.333... degrees
NAKSHATRA_SPAN = 360.0 / 27.0

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni",
    "Uttara Phalguni", "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha",
    "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana",
    "Dhanishtha", "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]

# Average speed in degrees per day
PLANET_SPEEDS_DEG_PER_DAY: dict[str, float] = {
    "moon": 13.1764,
    "sun": 0.9856,
    "mercury": 1.3833,
    "venus": 1.2,
    "mars": 0.5240,
    "jupiter": 0.0831,
    "saturn": 0.0335,
    "uranus": 0.0115,
    "neptune": 0.0060,
    "pluto": 0.0040,
}


def nakshatra_from_degree(degree: float) -> dict:
    """Map a zodiac/planetary degree (0–360) to its Nakshatra, pada, and position."""
    degree = float(degree) % 360.0
    idx = int(degree / NAKSHATRA_SPAN)
    position_pct = round((degree % NAKSHATRA_SPAN) / NAKSHATRA_SPAN * 100.0, 2)
    pada = min(4, int(position_pct // 25) + 1)  # 4 padas each 25% of nakshatra
    return {
        "nakshatra": NAKSHATRAS[idx],
        "index": idx + 1,
        "degree": round(degree, 4),
        "position_pct": position_pct,
        "pada": pada,
    }


def degree_to_time_days(degree_move: float, planet: str = "sun") -> float:
    """Convert degrees of planetary motion to equivalent calendar days."""
    speed = PLANET_SPEEDS_DEG_PER_DAY.get(planet.lower(), 0.9856)
    if speed == 0:
        return 0.0
    return round(abs(degree_move) / speed, 2)


def time_to_degree(days: float, planet: str = "sun") -> float:
    """Convert calendar days to degrees of planetary travel."""
    speed = PLANET_SPEEDS_DEG_PER_DAY.get(planet.lower(), 0.9856)
    return round(abs(days) * speed, 4)


def planetary_cycle_estimate(day_of_year: int, planet: str = "sun") -> dict:
    """
    Estimate planetary position within its annual cycle given the day of year.
    Returns degree estimate, Nakshatra, and pada.
    """
    speed = PLANET_SPEEDS_DEG_PER_DAY.get(planet.lower(), 0.9856)
    degree = round((day_of_year * speed) % 360.0, 2)
    nakshatra_info = nakshatra_from_degree(degree)
    return {
        "planet": planet,
        "estimated_degree": degree,
        "nakshatra": nakshatra_info["nakshatra"],
        "pada": nakshatra_info["pada"],
    }
