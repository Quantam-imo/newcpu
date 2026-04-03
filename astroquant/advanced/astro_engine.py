"""
AstroQuant Advanced Astro Engine
===================================
Integrated planetary engine for the Market Causality Lab.

Provides:
  - Real-time planetary positions via Swiss Ephemeris (Moshier fallback)
  - Full aspect map (conjunction → opposition, orb=3°)
  - Retrograde status for all tracked planets
  - Intraday astro trigger detection (tightest active aspect per bar)
  - Planetary timing projector (next N degree events forward in time)
  - Composite astro score for use in generate_signal()

All public functions accept an optional `jd` (Julian Day float) so the
engine can be driven from historical bar timestamps as well as live data.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

import swisseph as swe

from astroquant.engine.astro_aspects_pro import get_aspects, ASPECTS, ORB
from astroquant.engine.astro_360_panel import calculate_cycle

# ---------------------------------------------------------------------------
# Planet registry
# ---------------------------------------------------------------------------
PLANETS: dict[str, int] = {
    "sun":     swe.SUN,
    "moon":    swe.MOON,
    "mercury": swe.MERCURY,
    "venus":   swe.VENUS,
    "mars":    swe.MARS,
    "jupiter": swe.JUPITER,
    "saturn":  swe.SATURN,
}

# Aspect scores: positive = bullish, negative = bearish
_ASPECT_SCORE: dict[str, int] = {
    "CONJUNCTION": 1,
    "SEXTILE":     2,
    "TRINE":       2,
    "SQUARE":      -2,
    "OPPOSITION":  -1,
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_jd() -> float:
    """Return the Julian Day for the current UTC moment."""
    now = datetime.now(timezone.utc)
    return swe.julday(now.year, now.month, now.day,
                      now.hour + now.minute / 60.0 + now.second / 3600.0)


def _jd_from_dt(dt: datetime) -> float:
    """Convert a timezone-aware (or naive UTC) datetime to Julian Day."""
    utc = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    return swe.julday(utc.year, utc.month, utc.day,
                      utc.hour + utc.minute / 60.0 + utc.second / 3600.0)


def _calc_planet(jd: float, planet_id: int) -> tuple[float, float]:
    """Return (longitude_deg, speed_deg_per_day) for a planet at jd."""
    result = swe.calc_ut(jd, planet_id)
    lon: float = result[0][0]
    speed: float = result[0][3]
    return lon, speed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_positions(jd: Optional[float] = None) -> dict[str, float]:
    """
    Return geocentric ecliptic longitudes (degrees) for all tracked planets.

    Args:
        jd: Julian Day. Uses current UTC if None.

    Returns:
        Dict of planet_name → longitude (0–360°).
    """
    if jd is None:
        jd = _now_jd()
    return {name: _calc_planet(jd, pid)[0] for name, pid in PLANETS.items()}


def get_speeds(jd: Optional[float] = None) -> dict[str, float]:
    """
    Return daily motion speeds (degrees/day) for all tracked planets.
    Negative speed indicates retrograde motion.
    """
    if jd is None:
        jd = _now_jd()
    return {name: _calc_planet(jd, pid)[1] for name, pid in PLANETS.items()}


def get_retrogrades(jd: Optional[float] = None) -> dict[str, bool]:
    """
    Return a dict of planet → True/False indicating retrograde status.
    """
    return {name: speed < 0.0 for name, speed in get_speeds(jd).items()}


def get_aspect_map(jd: Optional[float] = None) -> list[tuple[str, str, str, float]]:
    """
    Return all active aspects as (planet1, planet2, aspect_name, exact_orb).

    The exact_orb is the angular separation remaining to the exact aspect angle —
    smaller = tighter = more powerful.
    """
    if jd is None:
        jd = _now_jd()
    positions = get_positions(jd)

    result: list[tuple[str, str, str, float]] = []
    keys = list(positions.keys())
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            p1, p2 = keys[i], keys[j]
            diff = abs(positions[p1] - positions[p2])
            diff = min(diff, 360.0 - diff)          # take shorter arc
            for aspect_name, exact_angle in ASPECTS.items():
                orb = abs(diff - float(exact_angle))
                if orb <= float(ORB):
                    result.append((p1, p2, aspect_name, round(orb, 4)))

    return sorted(result, key=lambda x: x[3])       # tightest first


def intraday_trigger(jd: Optional[float] = None) -> dict:
    """
    Return the single tightest active aspect as an intraday trigger signal.

    Use at each bar close to check whether a planetary configuration is
    firing *right now*. Returns an empty dict when no aspect is active.

    Returns:
        {
            "planet1": str,
            "planet2": str,
            "aspect":  str,
            "orb":     float,   # degrees from exact
            "bias":    str,     # "BULLISH" | "BEARISH" | "NEUTRAL"
        }
    """
    aspects = get_aspect_map(jd)
    if not aspects:
        return {}

    p1, p2, aspect, orb = aspects[0]
    score = _ASPECT_SCORE.get(aspect, 0)
    bias = "BULLISH" if score > 0 else ("BEARISH" if score < 0 else "NEUTRAL")

    return {
        "planet1": p1,
        "planet2": p2,
        "aspect": aspect,
        "orb": orb,
        "bias": bias,
    }


def planetary_timing(
    planet: str = "mars",
    target_degree: float = 0.0,
    days_forward: int = 30,
    step_hours: float = 1.0,
    jd: Optional[float] = None,
) -> Optional[dict]:
    """
    Project forward in time to find when *planet* next reaches *target_degree*.

    Useful for bar-level timing: convert the returned `jd_trigger` to a
    bar index using your candle duration.

    Args:
        planet:         Planet name (must be in PLANETS).
        target_degree:  Target ecliptic longitude (0–360).
        days_forward:   Search window in calendar days.
        step_hours:     Time resolution in hours.
        jd:             Start Julian Day (current UTC if None).

    Returns:
        {"planet": str, "target_degree": float, "jd_trigger": float,
         "dt_utc": str, "days_from_now": float}
        or None if not found inside the window.
    """
    pid = PLANETS.get(planet)
    if pid is None:
        return None

    start_jd = jd if jd is not None else _now_jd()
    step_jd = step_hours / 24.0
    target = float(target_degree) % 360.0
    steps = int(days_forward * 24 / step_hours)

    for i in range(steps):
        test_jd = start_jd + i * step_jd
        lon, _ = _calc_planet(test_jd, pid)
        if abs(lon - target) <= (step_jd * 1.5 * 360):   # rough sweep check
            # Refine: check if crossing
            prev_lon, _ = _calc_planet(test_jd - step_jd, pid)
            if min(abs(lon - target), abs(prev_lon - target)) < 2.0:
                days_diff = test_jd - start_jd
                # Convert JD back to datetime
                y, mo, d, h = swe.revjul(test_jd)
                minutes = (h % 1) * 60
                dt_str = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}T{int(h):02d}:{int(minutes):02d}Z"
                return {
                    "planet": planet,
                    "target_degree": target,
                    "jd_trigger": round(test_jd, 6),
                    "dt_utc": dt_str,
                    "days_from_now": round(days_diff, 3),
                }
    return None


def astro_score(jd: Optional[float] = None) -> dict:
    """
    Produce a composite astro score for use in generate_signal().

    Score > 0 → bullish astro bias
    Score < 0 → bearish astro bias
    Score = 0 → neutral

    Returns:
        {
            "score":      int,
            "bias":       "BULLISH" | "BEARISH" | "NEUTRAL",
            "aspects":    int,           # number of active aspects
            "retrogrades": list[str],    # planets currently retrograde
            "trigger":    dict,          # tightest intraday trigger
        }
    """
    if jd is None:
        jd = _now_jd()

    aspects = get_aspect_map(jd)
    retro = get_retrogrades(jd)

    score = 0
    for p1, p2, aspect_name, orb in aspects:
        score += _ASPECT_SCORE.get(aspect_name, 0)

    # Mercury retrograde: bearish bias
    if retro.get("mercury"):
        score -= 1

    retro_list = [p for p, is_retro in retro.items() if is_retro]
    trigger = intraday_trigger(jd)
    bias = "BULLISH" if score > 0 else ("BEARISH" if score < 0 else "NEUTRAL")

    return {
        "score": score,
        "bias": bias,
        "aspects": len(aspects),
        "retrogrades": retro_list,
        "trigger": trigger,
    }
