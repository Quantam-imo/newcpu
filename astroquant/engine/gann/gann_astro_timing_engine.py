"""
Gann Astro Mathematical Functions & Timing Formulas

Lesson 3 — The Five Mathematical Functions of Price-Time

Everything in the universe moves in geometric and cyclic patterns.
TIME is the foundation. PRICE is the consequence.

Functions:
  1. Linear        y = mx + b             → stable trend / Gann angles (1×1, 2×1)
  2. Quadratic     y = ax² + bx + c       → parabolic top/bottom, time² harmonic build-up
  3. Sine          y = A·sin(Bx+C) + D    → cyclical waves anchored to planetary periods
  4. Exponential   y = a·eᵇˣ             → panic / explosive Mars-transit moves
  5. Logarithmic   y = a·log_b(x)         → post-shock deceleration, eclipse fade

Planetary Vibration Formula:
  V = A × sin(θt + φ)
  P(t) = R × cos²[(360°/T) × t + φ] + √(|Z × sin(θ × t)|)

Gann Timing Equation:
  t = (360 / p) × d    → degrees moved since last aspect

Advanced Intraday Formula:
  p(t) = [(h × √(Δt)) + (a × sin(θt + φ))] / ln(v + 1)

Planetary Cycle:
  T = 360° / Δθ        → synodic cycle between two planets

Historical Repeat:
  T(n) = T₀ + n × C   → Gann echo timing
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Planetary orbital periods (sidereal, days) ────────────────────────────────
# Used for angular-speed calculations: ω = 360° / period_days

ORBITAL_PERIODS: Dict[str, float] = {
    "moon":    27.3217,
    "mercury": 87.969,
    "venus":   224.701,
    "mars":    686.971,
    "jupiter": 4332.59,
    "saturn":  10759.22,
    "uranus":  30688.5,
    "neptune": 60182.0,
    "pluto":   90560.0,
}

# Angular speed in degrees per day
ANGULAR_SPEED: Dict[str, float] = {
    name: round(360.0 / days, 6)
    for name, days in ORBITAL_PERIODS.items()
}

# Jupiter–Saturn base cycle (synodic ≈ 7253d ≈ 19.86 years)
# Used in T = 360 / Δθ examples
JUPITER_SATURN_SYNODIC = round(
    360.0 / abs(ANGULAR_SPEED["jupiter"] - ANGULAR_SPEED["saturn"]), 1
)

# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class AstroTimingResult:
    formula_name: str
    result: float
    inputs: Dict
    lesson_note: str


# ── 1. Linear Function ────────────────────────────────────────────────────────

def gann_linear(x: float, m: float, b: float) -> AstroTimingResult:
    """y = mx + b — Stable trend / Gann angle projection.

    Represents consistent price movement over uniform time intervals.
    m = Gann angle ratio (e.g. 1.0 for 1×1, 2.0 for 2×1, 0.5 for 1×2).
    b = anchor price.
    x = bars (or days) from anchor.
    """
    y = m * x + b
    return AstroTimingResult(
        formula_name="Linear (Gann Angle)",
        result=round(y, 4),
        inputs={"x": x, "m_angle_ratio": m, "b_anchor": b},
        lesson_note=(
            f"Gann {m}×1 angle: at bar {x:.0f} the projected price is {y:.2f}. "
            "When price = time × angle ratio, time and price are squared."
        ),
    )


# ── 2. Quadratic Function ─────────────────────────────────────────────────────

def gann_quadratic(x: float, a: float, b: float, c: float) -> AstroTimingResult:
    """y = ax² + bx + c — Parabolic top/bottom.

    x² mirrors Gann's idea that time cycles intensify with harmonic build-up.
    Parabolic rises (bull) and crashes follow this curve.
    Mars ingress or eclipse moments amplify the x² coefficient.
    """
    y = a * (x ** 2) + b * x + c
    vertex_x = -b / (2 * a) if a != 0 else float("nan")
    return AstroTimingResult(
        formula_name="Quadratic (Parabolic Cycle)",
        result=round(y, 4),
        inputs={"x": x, "a": a, "b": b, "c": c, "vertex_x": round(vertex_x, 2)},
        lesson_note=(
            f"Parabolic price at bar {x:.0f}: {y:.2f}. "
            f"Cycle apex at bar {vertex_x:.1f}. "
            "Time² builds harmonic pressure — explosive at apex."
        ),
    )


# ── 3. Sine Function ──────────────────────────────────────────────────────────

def gann_sine(x: float, A: float, B: float, C: float, D: float) -> AstroTimingResult:
    """y = A·sin(Bx + C) + D — Planetary wave / cyclical analysis.

    Foundation of cyclical analysis.
    A = amplitude (price range of wave)
    B = 2π / period → set B = 2π / T to model a T-day planetary cycle
    C = phase shift (retrograde, aspect)
    D = midline (centre price)
    """
    y = A * math.sin(B * x + C) + D
    period = (2 * math.pi / B) if B != 0 else float("inf")
    return AstroTimingResult(
        formula_name="Sine (Planetary Wave)",
        result=round(y, 4),
        inputs={"x": x, "A_amplitude": A, "B": B, "C_phase": C, "D_midline": D,
                "cycle_period_bars": round(period, 2)},
        lesson_note=(
            f"Planetary wave at bar {x:.0f}: {y:.2f}. "
            f"Cycle period: {period:.1f} bars. "
            "When sine derivative = 0, price is at turning point."
        ),
    )


def gann_sine_from_planet(
    days_elapsed: float, price_centre: float, amplitude: float, planet: str = "moon"
) -> AstroTimingResult:
    """Helper: build sine wave calibrated to a planet's orbital period."""
    T = ORBITAL_PERIODS.get(planet, 29.53)
    B = 2 * math.pi / T
    return gann_sine(days_elapsed, amplitude, B, 0.0, price_centre)


# ── 4. Exponential Function ───────────────────────────────────────────────────

def gann_exponential(x: float, a: float, b: float) -> AstroTimingResult:
    """y = a·eᵇˣ — Panic / explosive move.

    Describes panic buying or selling with compounding momentum.
    Triggered by Mars transits (conjunctions, squares, oppositions) or eclipses.
    b > 0 → explosive upside | b < 0 → panic selling collapse.
    """
    try:
        y = a * math.exp(b * x)
    except OverflowError:
        y = float("inf")
    return AstroTimingResult(
        formula_name="Exponential (Mars/Eclipse Move)",
        result=round(y, 4) if math.isfinite(y) else y,
        inputs={"x": x, "a_base": a, "b_velocity": b},
        lesson_note=(
            f"Explosive price at bar {x:.0f}: {y:.2f}. "
            f"{'Upside panic' if b > 0 else 'Crash/panic selling'}. "
            "Typical at Mars conjunction, eclipse, or high-energy transit window."
        ),
    )


# ── 5. Logarithmic Function ───────────────────────────────────────────────────

def gann_logarithmic(x: float, a: float, base: float = math.e) -> AstroTimingResult:
    """y = a·log_base(x) — Deceleration / post-shock fade.

    Early strong reaction that gradually slows. Models:
    - Post-eclipse consolidation
    - Soft landing after major transit
    - Compression phase before next cycle
    """
    if x <= 0:
        return AstroTimingResult("Logarithmic", float("nan"), {"x": x}, "x must be > 0")
    if base == math.e:
        y = a * math.log(x)
    else:
        y = a * math.log(x) / math.log(base)
    return AstroTimingResult(
        formula_name="Logarithmic (Post-shock Deceleration)",
        result=round(y, 4),
        inputs={"x": x, "a_coeff": a, "base": base},
        lesson_note=(
            f"Deceleration value at bar {x:.0f}: {y:.2f}. "
            "Initial planetary shock absorbed; market stabilising into consolidation."
        ),
    )


# ── Planetary Vibration V = A × sin(θt + φ) ──────────────────────────────────

def vibrational_impact(
    t: float,
    A: float,
    planet: str = "moon",
    phi_deg: float = 0.0,
    retrograde: bool = False,
) -> float:
    """V = A × sin(θt + φ)

    V = vibrational impact on market psychology
    A = amplitude (planet's strength; outer planets get higher weight)
    θ = angular velocity (degrees/day) of the planet
    t = time in days from reference point
    φ = phase shift (retrograde: negate A, strong aspect: offset φ)

    Returns: vibrational force (positive = bullish pressure, negative = bearish)
    """
    theta = ANGULAR_SPEED.get(planet, ANGULAR_SPEED["moon"])  # °/day
    theta_rad = math.radians(theta)
    phi_rad = math.radians(phi_deg)
    sign = -1 if retrograde else 1
    return round(sign * A * math.sin(theta_rad * t + phi_rad), 6)


def vibrational_impact_multi(
    t: float,
    planet_params: List[Dict],  # [{"planet": "saturn", "A": 3.0, "phi": 0, "retro": False}]
) -> Dict:
    """Sum vibrational impacts from multiple planets.
    When multiple planetary cycles align, their combined peaks → market event.
    """
    total = 0.0
    breakdown = {}
    for p in planet_params:
        planet = p.get("planet", "moon")
        A = float(p.get("A", 1.0))
        phi = float(p.get("phi", 0.0))
        retro = bool(p.get("retro", False))
        v = vibrational_impact(t, A, planet, phi, retro)
        breakdown[planet] = round(v, 4)
        total += v

    signal = "EXPAND" if total > 0.5 else ("CONTRACT" if total < -0.5 else "NEUTRAL")
    return {
        "total_vibration": round(total, 4),
        "signal": signal,
        "breakdown": breakdown,
        "note": (
            "Planetary vibrations summated. "
            f"Total={total:.3f} → {signal}. "
            "Peaks indicate major turns; zero-crossings = inflection points."
        ),
    }


# ── Time-Vibration Mapping P(t) ───────────────────────────────────────────────

def price_time_vibration(
    t: float,
    R: float,
    T_days: float,
    phi_deg: float = 0.0,
    Z: float = 10.0,
    theta_deg_per_day: float = None,
    planet: str = "saturn",
) -> float:
    """P(t) = R × cos²[(360°/T) × t + φ] + √(|Z × sin(θ × t)|)

    P(t) = Projected price influence at time t
    R    = Planetary resonance coefficient (Jupiter/Saturn = higher weight)
    T    = Orbital period in days
    φ    = Aspect phase shift (conjunction=0°, opposition=180°)
    Z    = Previous volatility amplitude
    θ    = Angular motion velocity (degrees/day)
    t    = Days from anchor date

    Returns scalar representing harmonic pressure on price at time t.
    """
    if T_days <= 0:
        T_days = ORBITAL_PERIODS.get(planet, 365.0)
    theta = theta_deg_per_day if theta_deg_per_day is not None else ANGULAR_SPEED.get(planet, 1.0)

    cos_arg = math.radians((360.0 / T_days) * t + phi_deg)
    sin_arg = math.radians(theta * t)

    cos_term = R * (math.cos(cos_arg) ** 2)
    sqrt_term = math.sqrt(abs(Z * math.sin(sin_arg)))

    return round(cos_term + sqrt_term, 4)


def scan_vibration_peaks(
    anchor_days: float = 0.0,
    scan_days: int = 30,
    R: float = 3.0,
    T_days: float = None,
    phi_deg: float = 0.0,
    Z: float = 15.0,
    planet: str = "saturn",
    threshold_percentile: float = 0.85,
) -> List[Dict]:
    """Scan forward from anchor_days for P(t) peaks ≥ threshold.
    Returns list of probable harmonic pressure points (time nodes).
    """
    if T_days is None:
        T_days = ORBITAL_PERIODS.get(planet, 365.0)

    values = []
    for d in range(scan_days + 1):
        t = anchor_days + d
        v = price_time_vibration(t, R, T_days, phi_deg, Z, planet=planet)
        values.append((d, t, v))

    if not values:
        return []

    max_v = max(v for _, _, v in values)
    threshold = max_v * threshold_percentile

    peaks = []
    for i, (d, t, v) in enumerate(values):
        if v >= threshold:
            # Simple local-max filter
            prev_v = values[i - 1][2] if i > 0 else 0
            next_v = values[i + 1][2] if i < len(values) - 1 else 0
            if v >= prev_v and v >= next_v:
                peaks.append({"day_offset": d, "abs_day": round(t, 1), "P_value": v})

    return peaks


# ── Gann Timing Equation t = (360/p) × d ─────────────────────────────────────

def gann_timing_degrees(
    planet: str, days_since_aspect: float
) -> Dict:
    """t = (360 / p) × d

    Calculates angular degrees a planet has moved since its last exact aspect.
    When multiple planets arrive at key degrees simultaneously → Gann node.

    Returns degrees moved, modulo 360, and how far to next key angle.
    """
    p = ORBITAL_PERIODS.get(planet, 365.0)
    degrees_moved = (360.0 / p) * days_since_aspect
    degrees_mod360 = degrees_moved % 360.0

    KEY_ANGLES = [0, 45, 90, 135, 180, 225, 270, 315, 360]
    next_key = next(
        (k for k in KEY_ANGLES if k > degrees_mod360 % 360), KEY_ANGLES[0]
    )
    as_seen_next = (next_key - degrees_mod360 % 360) % 360
    days_to_next = as_seen_next / (360.0 / p) if p > 0 else float("inf")

    return {
        "planet": planet,
        "orbital_period_days": p,
        "angular_speed_dday": round(360.0 / p, 4),
        "days_since_aspect": days_since_aspect,
        "degrees_moved": round(degrees_moved, 2),
        "degrees_mod360": round(degrees_mod360, 2),
        "next_key_angle": next_key,
        "degrees_to_next_key": round(as_seen_next, 2),
        "days_to_next_key": round(days_to_next, 2),
    }


# ── Advanced Intraday Formula ──────────────────────────────────────────────────

def intraday_price_projection(
    h: float,          # prior session high or low (anchor)
    delta_t: float,    # elapsed time in bars/minutes from session open
    a: float,          # astro amplitude (planet influence strength)
    theta_deg: float,  # angular speed in degrees per bar
    phi_deg: float,    # phase shift (retrograde / aspect orb)
    v: float,          # current volume (relative)
) -> Dict:
    """p(t) = [(h × √(Δt)) + (a × sin(θt + φ))] / ln(v + 1)

    h = prior session high / low (real price anchor)
    √(Δt) = nonlinear time expansion (slow early, intensifies)
    a × sin(θt + φ) = planetary vibrational component
    ln(v+1) = logarithmic volume scaler (realistic normalization)

    Returns projected turning-point price level for intraday Gann Astro.
    """
    if delta_t < 0:
        delta_t = 0.0
    v = max(0.0, v)

    price_term = h * math.sqrt(delta_t)
    astro_term = a * math.sin(math.radians(theta_deg * delta_t + phi_deg))
    volume_denom = math.log(v + 1) if v > 0 else 1.0

    result = (price_term + astro_term) / volume_denom if volume_denom > 0 else 0.0

    return {
        "projected_price": round(result, 4),
        "price_term": round(price_term, 4),
        "astro_term": round(astro_term, 4),
        "volume_denom": round(volume_denom, 4),
        "delta_t": delta_t,
        "note": (
            f"Intraday projection at Δt={delta_t:.1f}: {result:.2f}. "
            f"Price term: {price_term:.2f}, Astro: {astro_term:.2f}, "
            f"Volume scale: {volume_denom:.3f}."
        ),
    }


# ── Planetary Cycle T = 360° / Δθ ────────────────────────────────────────────

def planetary_cycle_period(planet1: str, planet2: str) -> Dict:
    """T = 360° / Δθ — Synodic cycle between two planets.

    Δθ = │ω₁ - ω₂│ (difference in angular speeds)
    T = full synodic period in days.

    Example: Jupiter–Saturn ≈ 7253 days ≈ 19.86 years.
    Gann used harmonic divisions (T/2, T/4, T/8) for swing timing.
    """
    w1 = ANGULAR_SPEED.get(planet1, 0.0)
    w2 = ANGULAR_SPEED.get(planet2, 0.0)
    delta_w = abs(w1 - w2)
    if delta_w == 0:
        return {"error": f"Same planet or identical speeds: {planet1}, {planet2}"}

    T = 360.0 / delta_w
    T_years = T / 365.25

    harmonics = {
        "T/2":  round(T / 2, 1),
        "T/4":  round(T / 4, 1),
        "T/8":  round(T / 8, 1),
        "T/3":  round(T / 3, 1),
        "T/6":  round(T / 6, 1),
        "T/9":  round(T / 9, 1),
    }

    return {
        "planet1": planet1,
        "planet2": planet2,
        "w1_deg_per_day": round(w1, 6),
        "w2_deg_per_day": round(w2, 6),
        "delta_w": round(delta_w, 6),
        "synodic_period_days": round(T, 1),
        "synodic_period_years": round(T_years, 2),
        "harmonics_days": harmonics,
        "note": (
            f"{planet1.title()}–{planet2.title()} synodic cycle: {T:.0f} days "
            f"({T_years:.2f} yrs). "
            "Break into harmonics for medium/short-term swing turns."
        ),
    }


# ── Historical Cycle Echo T(n) = T₀ + n × C ──────────────────────────────────

def historical_echo(
    T0: datetime,
    C_days: float,
    lookforward_n: int = 5,
    planet_pair: Optional[Tuple[str, str]] = None,
) -> List[Dict]:
    """T(n) = T₀ + n × C

    Projects future echo dates from an original market event.
    C = planetary cycle constant (e.g. Saturn–Uranus ≈ 84 years = 30,681 days).
    n = cycle count (1, 2, 3 ...).

    Example: 1929 crash + 1 × 30,681 days ≈ 2008 crash.
    """
    if planet_pair:
        cycle_info = planetary_cycle_period(*planet_pair)
        C_days = cycle_info.get("synodic_period_days", C_days)

    echoes = []
    for n in range(1, lookforward_n + 1):
        echo_date = T0.timestamp() + n * C_days * 86400
        echo_dt = datetime.fromtimestamp(echo_date, tz=timezone.utc)
        echoes.append({
            "n": n,
            "date": echo_dt.strftime("%Y-%m-%d"),
            "days_from_now": round(
                (echo_dt - datetime.now(timezone.utc)).total_seconds() / 86400, 1
            ),
            "C_applied_days": round(n * C_days, 1),
        })

    return echoes


# ── Live planetary state for all formulas ─────────────────────────────────────

def get_planetary_amplitudes() -> Dict[str, float]:
    """Returns approximate amplitude weights per planet for V = A·sin(θt + φ).
    Outer/slow planets carry higher market impact (Gann).
    """
    return {
        "moon":    1.0,
        "mercury": 1.2,
        "venus":   1.5,
        "mars":    2.5,   # aggression, panic moves
        "jupiter": 3.5,   # expansion
        "saturn":  3.0,   # restriction, major highs/lows
        "uranus":  2.0,
        "neptune": 1.5,
        "pluto":   2.0,
    }
