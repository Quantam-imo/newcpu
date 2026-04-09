"""
Gann Astro – Law of Vibration: 3-6-9 Time Harmonic Engine

Formula (GannAstroTrader):
  Tₛ = T₀ × (3 + 6 + 9) / 9
     = T₀ × 18 / 9
     = T₀ × 2

Where:
  T₀  = base time cycle (bars or calendar days)
  Tₛ  = full swing duration (double the base cycle)
  3   = Initiation  — price sparks, nerve impulse, first move
  6   = Expansion   — absorption, momentum, emotional response
  9   = Completion  — transmission, coherence, trend exhaustion → reversal

Phase proportions within Tₛ:
  INITIATION  : elapsed 0   → Tₛ × 3/18 = Tₛ/6    (0–16.7%)
  EXPANSION   : elapsed Tₛ/6 → Tₛ × 9/18 = Tₛ/2   (16.7–50%)
  COMPLETION  : elapsed Tₛ/2 → Tₛ                  (50–100%)

Chakra Frequency Code (369):
  3 = Creation  | Root + Sacral  | decision, risk-taking, initiation
  6 = Reception | Solar Plexus + Third Eye | absorption, information
  9 = Transmission | Heart + Crown | intuition, coherence, completion

Rise  = Time Expansion Phase (3→6)
Sideways = Time Balance Phase (approaching 6)
Fall / Reversal = Time Release Phase (9 → 0)

Nine is the hidden seal: all paths return to it.
Digital root of 9 × n always reduces back to 9.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from math import pi, sin, floor
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Known stable base cycles (Gann natural time units, days)
BASE_CYCLES_DAYS = {
    "lunar_phase":   14.765,   # half synodic month (New Moon → Full Moon)
    "lunar_full":    29.53,    # full synodic month
    "weekly":         7.0,    # Gann 7-day cycle
    "quarterly":     90.0,    # 90-day / 90° cycle
    "semi_annual":  182.5,    # 6-month cycle
    "annual":       365.25,   # solar year
    "28_day":        28.0,    # 28-day biologic/lunar cycle (turtle shell)
}

# Phase fractions within one Tₛ (= 2 × T₀)
INITIATION_UPPER: float = 3 / 18    # 0.1667 (16.7%)
EXPANSION_UPPER:  float = 9 / 18    # 0.5000 (50%)
COMPLETION_UPPER: float = 1.0       # 100%

# 3-6-9 chakra labels
PHASE_LABELS = {3: "INITIATION", 6: "EXPANSION", 9: "COMPLETION"}
PHASE_CHAKRA = {
    3: "Root/Sacral — decision, risk-taking, first move",
    6: "Solar Plexus/Third Eye — absorption, momentum, information",
    9: "Heart/Crown — intuition, coherence, cycle completion → reversal",
}
PHASE_MARKET_STATE = {
    3: "RISE",       # Time Expansion Phase
    6: "BALANCE",    # Time Balance Phase (approaching peak)
    9: "RELEASE",    # Time Release Phase → reversal imminent
}

# Digital root check — digital_root = 9 means cycle completion frequency
def digital_root(n: int) -> int:
    n = abs(n)
    while n >= 10:
        n = sum(int(d) for d in str(n))
    return n


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class CycleState369:
    base_cycle_name: str      # e.g. "lunar_phase"
    T0: float                 # base cycle days
    Ts: float                 # full swing duration (T0 × 2)
    elapsed_days: float       # days elapsed in current Tₛ
    progress: float           # 0.0–1.0 through current Tₛ
    phase_369: int            # 3, 6, or 9
    phase_label: str          # INITIATION / EXPANSION / COMPLETION
    phase_chakra: str
    market_state: str         # RISE / BALANCE / RELEASE
    bars_to_completion: float # days remaining to Tₛ boundary
    completion_score: float   # 0→1, 1 = full cycle complete (9 resonance)
    vibration_harmonic: float # sin(progress × π), like expansion_score
    nine_resonance: bool      # True when progress ≈ n/9 boundary
    digital_root: int         # digital root of elapsed_days int
    is_nine_dr: bool          # True when digital_root ∈ {9}
    reversal_imminent: bool   # True when phase=9 (COMPLETION)
    lesson_note: str
    timestamp: str


# ── Core computation ──────────────────────────────────────────────────────────

def _classify_phase(progress: float) -> int:
    """Return 3, 6, or 9 based on progress through Tₛ."""
    if progress < INITIATION_UPPER:
        return 3
    if progress < EXPANSION_UPPER:
        return 6
    return 9


def _nine_resonance(progress: float, tol: float = 0.025) -> bool:
    """True when progress is near any n/9 boundary (0/9, 1/9, ..., 9/9)."""
    for i in range(10):
        if abs(progress - i / 9) <= tol:
            return True
    return False


def _bars_to_completion(progress: float, Ts: float) -> float:
    """Days remaining to the end of current Tₛ."""
    return round(Ts * (1.0 - progress), 2)


def _lesson_note(phase: int, progress: float, market_state: str) -> str:
    p_pct = round(progress * 100, 1)
    if phase == 3:
        return (
            f"Lesson 2: INITIATION ({p_pct}% through swing). "
            "3 = nerve impulse — the cycle seed fires. Price starts its first move. "
            "Do not enter yet — wait for expansion confirmation."
        )
    if phase == 6:
        return (
            f"Lesson 2: EXPANSION ({p_pct}% through swing). "
            "6 = absorption phase — momentum builds, market absorbs liquidity. "
            "TIME is in expansion. Trend confirmation valid. Add on pullbacks."
        )
    # phase == 9
    return (
        f"Lesson 2: COMPLETION ({p_pct}% through swing). "
        "9 = transmission — the cycle reaches its highest coherence then exhausts. "
        "Nine is the hidden seal: all paths return to it. "
        f"Market state: {market_state}. Reversal imminent — reduce positions."
    )


# ── Public API ────────────────────────────────────────────────────────────────

def compute_369(
    elapsed_days: float,
    base_cycle: str = "lunar_phase",
    custom_T0: Optional[float] = None,
) -> CycleState369:
    """Compute 3-6-9 cycle state.

    Args:
        elapsed_days: days since the last known cycle anchor
                      (e.g. days since last New Moon)
        base_cycle: key in BASE_CYCLES_DAYS (or 'custom' to use custom_T0)
        custom_T0: override T₀ if base_cycle='custom'

    Returns:
        CycleState369 with full Gann 3-6-9 phase state
    """
    T0 = custom_T0 if custom_T0 is not None else BASE_CYCLES_DAYS.get(base_cycle, 14.765)
    Ts = T0 * 2.0  # Tₛ = T₀ × (3+6+9)/9 = T₀ × 2
    cycle_elapsed = elapsed_days % Ts
    progress = cycle_elapsed / Ts  # 0.0 – 1.0

    phase = _classify_phase(progress)
    nine_res = _nine_resonance(progress)
    dr = digital_root(max(1, int(round(elapsed_days))))
    market_state = PHASE_MARKET_STATE[phase]
    rev_imminent = phase == 9
    bars_left = _bars_to_completion(progress, Ts)
    vib_harmonic = round(sin(progress * pi), 4)  # 0→1→0 over Tₛ
    completion_score = round(progress, 4)

    return CycleState369(
        base_cycle_name=base_cycle if custom_T0 is None else "custom",
        T0=round(T0, 3),
        Ts=round(Ts, 3),
        elapsed_days=round(elapsed_days, 3),
        progress=round(progress, 4),
        phase_369=phase,
        phase_label=PHASE_LABELS[phase],
        phase_chakra=PHASE_CHAKRA[phase],
        market_state=market_state,
        bars_to_completion=bars_left,
        completion_score=completion_score,
        vibration_harmonic=vib_harmonic,
        nine_resonance=nine_res,
        digital_root=dr,
        is_nine_dr=(dr == 9),
        reversal_imminent=rev_imminent,
        lesson_note=_lesson_note(phase, progress, market_state),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def compute_369_from_newmoon(
    base_cycle: str = "lunar_phase",
    custom_T0: Optional[float] = None,
) -> CycleState369:
    """Convenience: compute 3-6-9 state using Swiss Ephemeris to derive elapsed days
    since the last New Moon (same anchor as Lesson 1 Lunar Expansion Engine).
    """
    try:
        import swisseph as swe

        now = datetime.now(timezone.utc)
        jd = swe.julday(now.year, now.month, now.day,
                        now.hour + now.minute / 60.0 + now.second / 3600.0)
        sun_lon = swe.calc_ut(jd, swe.SUN)[0][0]
        moon_lon = swe.calc_ut(jd, swe.MOON)[0][0]
        phase_angle = (moon_lon - sun_lon) % 360.0
        LUNAR_CYCLE = 29.53058
        elapsed = (phase_angle / 360.0) * LUNAR_CYCLE
    except Exception:
        # Fallback: known New Moon 2026-03-29
        from datetime import timedelta
        KNOWN_NM = datetime(2026, 3, 29, 12, 0, 0, tzinfo=timezone.utc)
        elapsed = ((datetime.now(timezone.utc) - KNOWN_NM).total_seconds() / 86400.0) % 29.53058

    return compute_369(elapsed, base_cycle=base_cycle, custom_T0=custom_T0)


def build_369_summary(states: Dict[str, CycleState369]) -> Dict:
    """Given multiple cycle states (different T₀s), produce a confluence summary."""
    phase_counts = {3: 0, 6: 0, 9: 0}
    reversal_count = 0
    expansion_count = 0
    for s in states.values():
        phase_counts[s.phase_369] += 1
        if s.reversal_imminent:
            reversal_count += 1
        if s.phase_369 == 6:
            expansion_count += 1

    dominant_phase = max(phase_counts, key=lambda k: phase_counts[k])
    confluence_score = phase_counts[dominant_phase] / max(1, len(states))

    return {
        "dominant_phase": dominant_phase,
        "dominant_label": PHASE_LABELS[dominant_phase],
        "market_state": PHASE_MARKET_STATE[dominant_phase],
        "confluence_score": round(confluence_score, 3),
        "reversal_cycles": reversal_count,
        "expansion_cycles": expansion_count,
        "total_cycles": len(states),
        "signal": (
            "REVERSAL_IMMINENT" if reversal_count >= 2
            else "MOMENTUM_ACTIVE" if expansion_count >= 2
            else "WATCH"
        ),
    }
