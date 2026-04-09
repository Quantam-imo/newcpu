"""
Gann Astro Swing Trading — Lunar Expansion Engine
Lesson 1: Waxing Moon Cycle

Market does not move randomly.
It breathes with light.

From New Moon → Full Moon = accumulation → expansion phase
Waxing phase = increasing energy
  → price builds range
  → volatility compresses before release

Key insight: Time from New Moon = cycle seed

Phase Windows (days from New Moon):
  SEED:            0–2    — dead zone, no trade
  EARLY_EXPANSION: 3–5.5  — watch sweep + displacement
  MOMENTUM:        7–9.5  — trend confirmation, add positions
  EXHAUSTION:      11–13.5— climax, exit / reversal
  FULL_MOON_APEX:  13.5–15— full moon peak
  DRIFT:           15+    — waning noise, avoid

Expansion score = sin((cycle_day / 29.53) * π)
  peaks ~day 14.76 (Full Moon), ≥0.80 during Momentum window
  reflects how much "light energy" is pumping into the market

Gann angle = (360 / 29.53) * cycle_day
  cycles the price-time wheel once per lunar cycle
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import pi, sin, floor
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

LUNAR_CYCLE = 29.53058  # synodic month (days)

# Phase windows: inclusive lower bound, exclusive upper bound
_PHASE_WINDOWS: list[tuple[str, float, float]] = [
    ("SEED",            0.0,   2.0),
    ("EARLY_EXPANSION", 3.0,   5.5),
    ("MOMENTUM",        7.0,   9.5),
    ("EXHAUSTION",     11.0,  13.5),
    ("FULL_MOON_APEX", 13.5,  15.0),
    ("DRIFT",          15.0,  LUNAR_CYCLE),
]

_PHASE_DESCRIPTIONS: Dict[str, str] = {
    "SEED":            "New Moon seed — dead zone, no trade",
    "EARLY_EXPANSION": "Waxing Crescent — watch sweep + displacement",
    "MOMENTUM":        "First Quarter waxing — trend confirmation, add positions",
    "EXHAUSTION":      "Waxing Gibbous climax — take profit, watch reversal",
    "FULL_MOON_APEX":  "Full Moon apex — volatility peak, exit longs",
    "DRIFT":           "Waning Moon — noise zone, avoid new entries",
    "TRANSITION":      "Inter-phase transition — wait for confirmation",
}

_PHASE_TRADE_BIAS: Dict[str, str] = {
    "SEED":            "AVOID",
    "EARLY_EXPANSION": "WATCH_SETUP",
    "MOMENTUM":        "LONG_BIAS",
    "EXHAUSTION":      "EXIT_PARTIAL",
    "FULL_MOON_APEX":  "EXIT_FULL",
    "DRIFT":           "AVOID",
    "TRANSITION":      "WAIT",
}

# ICT-compatible phases (liquidity sweep + displacement required)
_ICT_ACTIVE_PHASES = {"EARLY_EXPANSION", "MOMENTUM"}

# Gann key angles (degrees) — harmonic vibration nodes on the lunar wheel
GANN_LUNAR_KEY_ANGLES = [0, 45, 90, 135, 180, 225, 270, 315, 360]

# Momentum phase Gann angle range (~84°–114°)
_MOMENTUM_ANGLE_MIN = (7.0 / LUNAR_CYCLE) * 360   # ≈84°
_MOMENTUM_ANGLE_MAX = (9.5 / LUNAR_CYCLE) * 360   # ≈115°


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class LunarPhaseState:
    date: str                       # ISO date (UTC)
    cycle_day: float                # days since New Moon (0–29.53)
    phase: str                      # SEED / EARLY_EXPANSION / MOMENTUM / ...
    phase_description: str
    waxing: bool                    # True = New→Full, False = Full→New
    expansion_score: float          # 0.0–1.0, peaks at Full Moon
    gann_angle: float               # degrees on the 360° lunar Gann wheel
    nearest_gann_key: float         # nearest harmonic Gann key angle
    gann_key_orb: float             # orb from nearest key angle (degrees)
    trade_bias: str
    ict_filter_pass: bool           # phase qualifies for ICT entry setup
    moon_phase_name: str            # human-readable (Waxing Crescent, etc.)
    moon_phase_angle: float         # Sun–Moon separation in ecliptic degrees
    lesson_note: str                # lesson context for the current phase
    telegram_alert_due: bool        # True when phase just entered MOMENTUM
    next_momentum_day: Optional[float] = None  # days until next Momentum window
    extra: Dict = field(default_factory=dict)


# ── Core engine ───────────────────────────────────────────────────────────────

def _classify_phase(cycle_day: float) -> str:
    """Return the phase name for a given cycle_day."""
    for name, lo, hi in _PHASE_WINDOWS:
        if lo <= cycle_day < hi:
            return name
    return "TRANSITION"


def _expansion_score(cycle_day: float) -> float:
    """sin-wave expansion score (0→1→0 over one lunar cycle).
    Peaks at Full Moon (day ~14.76), ≥0.80 during Momentum window.
    Lesson: waxing phase compresses volatility → releases near momentum peak.
    """
    return round(max(0.0, sin((cycle_day / LUNAR_CYCLE) * pi)), 4)


def _gann_angle(cycle_day: float) -> float:
    """Map cycle day to degrees on the 360° Gann lunar wheel.
    One full revolution = one synodic month. Day 0 = 0°.
    """
    return round((cycle_day / LUNAR_CYCLE) * 360.0 % 360.0, 2)


def _nearest_gann_key(angle: float) -> tuple[float, float]:
    """Return (nearest_key_angle, orb_degrees)."""
    best_key = min(GANN_LUNAR_KEY_ANGLES, key=lambda k: min(abs(angle - k), 360 - abs(angle - k)))
    orb = min(abs(angle - best_key), 360 - abs(angle - best_key))
    return best_key % 360, round(orb, 2)


def _moon_phase_name(phase_angle: float) -> str:
    """Convert Sun–Moon ecliptic separation to a named phase."""
    a = phase_angle % 360
    if a < 22.5:     return "New Moon"
    if a < 67.5:     return "Waxing Crescent"
    if a < 112.5:    return "First Quarter"
    if a < 157.5:    return "Waxing Gibbous"
    if a < 202.5:    return "Full Moon"
    if a < 247.5:    return "Waning Gibbous"
    if a < 292.5:    return "Last Quarter"
    if a < 337.5:    return "Waning Crescent"
    return "New Moon"


def _lesson_note(phase: str, cycle_day: float, waxing: bool) -> str:
    """Generate Gann Lesson 1 context note for current phase."""
    if phase == "SEED":
        return (
            "Lesson 1: New Moon = cycle seed. Market accumulates quietly. "
            "Price range compresses. Wait — do not trade the seed phase."
        )
    if phase == "EARLY_EXPANSION":
        return (
            "Lesson 1: Waxing energy enters the market. Watch for liquidity sweep "
            "below structure (displacement signal). Light is increasing. Energy builds."
        )
    if phase == "MOMENTUM":
        return (
            f"Lesson 1: Day {cycle_day:.1f} — MOMENTUM window. Peak waxing expansion. "
            "Price breathes with light. Trend confirmation required. "
            "ICT: wait for displacement + BOS before entry."
        )
    if phase == "EXHAUSTION":
        return (
            "Lesson 1: Waxing Gibbous climax. Energy approaching Full Moon. "
            "Buyers exhausted — watch for reversal candles. Reduce / exit positions."
        )
    if phase == "FULL_MOON_APEX":
        return (
            "Lesson 1: Full Moon apex — maximum light, maximum volatility. "
            "Gann: this is the emotional peak. Exit longs, wait for reversal confirmation."
        )
    if not waxing:
        return (
            "Lesson 1: Waning Moon = decreasing energy. Market loses directional clarity. "
            "Price drifts in noise. Avoid new swing entries until next New Moon seed."
        )
    return "Lesson 1: Transition zone — wait for next clean phase window."


def _days_until_next_momentum(cycle_day: float) -> Optional[float]:
    """Return how many days until the Momentum window opens (day 7)."""
    next_open = 7.0 if cycle_day < 7.0 else 7.0 + LUNAR_CYCLE - cycle_day
    return round(next_open, 1)


def _telegram_alert_due(phase: str, prev_phase: Optional[str]) -> bool:
    """True when we just transitioned INTO the Momentum phase."""
    return phase == "MOMENTUM" and prev_phase is not None and prev_phase != "MOMENTUM"


# ── Public API ────────────────────────────────────────────────────────────────

def compute_lunar_phase(prev_phase: Optional[str] = None) -> LunarPhaseState:
    """Compute the current lunar expansion state using Swiss Ephemeris.

    Args:
        prev_phase: the phase string from the previous call — used to trigger
                    Telegram alerts when the phase transitions into MOMENTUM.

    Returns:
        LunarPhaseState with all fields populated.
    """
    try:
        import swisseph as swe

        now = datetime.now(timezone.utc)
        jd = swe.julday(
            now.year, now.month, now.day,
            now.hour + now.minute / 60.0 + now.second / 3600.0,
        )

        sun_lon  = swe.calc_ut(jd, swe.SUN)[0][0]
        moon_lon = swe.calc_ut(jd, swe.MOON)[0][0]

        phase_angle = (moon_lon - sun_lon) % 360.0
        cycle_day   = (phase_angle / 360.0) * LUNAR_CYCLE
        waxing      = cycle_day < (LUNAR_CYCLE / 2.0)

        phase       = _classify_phase(cycle_day)
        exp_score   = _expansion_score(cycle_day)
        gann_deg    = _gann_angle(cycle_day)
        key_angle, orb = _nearest_gann_key(gann_deg)
        phase_name  = _moon_phase_name(phase_angle)
        ict_pass    = phase in _ICT_ACTIVE_PHASES
        alert_due   = _telegram_alert_due(phase, prev_phase)

        next_mom = (
            _days_until_next_momentum(cycle_day)
            if phase not in ("MOMENTUM",)
            else None
        )

        return LunarPhaseState(
            date=now.strftime("%Y-%m-%d"),
            cycle_day=round(cycle_day, 3),
            phase=phase,
            phase_description=_PHASE_DESCRIPTIONS.get(phase, phase),
            waxing=waxing,
            expansion_score=exp_score,
            gann_angle=gann_deg,
            nearest_gann_key=key_angle,
            gann_key_orb=orb,
            trade_bias=_PHASE_TRADE_BIAS.get(phase, "WAIT"),
            ict_filter_pass=ict_pass,
            moon_phase_name=phase_name,
            moon_phase_angle=round(phase_angle, 2),
            lesson_note=_lesson_note(phase, cycle_day, waxing),
            telegram_alert_due=alert_due,
            next_momentum_day=next_mom,
        )

    except ImportError:
        logger.error("swisseph not installed — falling back to date-estimate mode")
        return _fallback_estimate(prev_phase)
    except Exception as exc:
        logger.error(f"lunar_expansion_engine error: {exc}")
        return _fallback_estimate(prev_phase)


def _fallback_estimate(prev_phase: Optional[str]) -> LunarPhaseState:
    """Rough estimate without Swiss Ephemeris (uses known New Moon reference date)."""
    # Known New Moon: 2026-03-29 (approximate; good enough for fallback)
    KNOWN_NEW_MOON = datetime(2026, 3, 29, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    days_since = (now - KNOWN_NEW_MOON).total_seconds() / 86400.0
    cycle_day = days_since % LUNAR_CYCLE
    phase_angle = (cycle_day / LUNAR_CYCLE) * 360.0
    waxing = cycle_day < (LUNAR_CYCLE / 2.0)
    phase = _classify_phase(cycle_day)
    return LunarPhaseState(
        date=now.strftime("%Y-%m-%d"),
        cycle_day=round(cycle_day, 3),
        phase=phase,
        phase_description=_PHASE_DESCRIPTIONS.get(phase, phase),
        waxing=waxing,
        expansion_score=_expansion_score(cycle_day),
        gann_angle=_gann_angle(cycle_day),
        nearest_gann_key=_nearest_gann_key(_gann_angle(cycle_day))[0],
        gann_key_orb=_nearest_gann_key(_gann_angle(cycle_day))[1],
        trade_bias=_PHASE_TRADE_BIAS.get(phase, "WAIT"),
        ict_filter_pass=phase in _ICT_ACTIVE_PHASES,
        moon_phase_name=_moon_phase_name(phase_angle),
        moon_phase_angle=round(phase_angle, 2),
        lesson_note=_lesson_note(phase, cycle_day, waxing),
        telegram_alert_due=_telegram_alert_due(phase, prev_phase),
        next_momentum_day=(_days_until_next_momentum(cycle_day) if phase != "MOMENTUM" else None),
        extra={"source": "fallback_estimate"},
    )
