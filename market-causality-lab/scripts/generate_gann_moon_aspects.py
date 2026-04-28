#!/usr/bin/env python3
"""Generate Gann time-cycle and Moon aspect/phase event datasets (2000-2026).

Output
------
market-causality-lab/data/gann_moon_aspects_2000_2026.csv

Events generated
----------------
Gann solar harmonics (Sun at every 45° of ecliptic — 8th harmonic):
  0°  = Spring Equinox (Aries ingress)  — annual cycle start
  45° = Gann 45° Turn (mid-Taurus)
  90° = Summer Solstice (Cancer ingress)
 135° = Gann 135° Turn (mid-Leo)
 180° = Autumn Equinox (Libra ingress)
 225° = Gann 225° Turn (mid-Scorpio)
 270° = Winter Solstice (Capricorn ingress)
 315° = Gann 315° Turn (mid-Aquarius)

Moon phase cycle (Moon–Sun elongation):
  New Moon (0°), First Quarter (90°), Full Moon (180°), Last Quarter (270°)
  Solar Eclipse — New Moon within 18° of True Lunar Node
  Lunar Eclipse — Full Moon within 11° of True Lunar Node

Moon aspects to planets (0° / 60° / 90° / 120° / 180°):
  Sun, Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune, Pluto

Moon geometry:
  Perigee (closest to Earth) / Apogee (farthest from Earth)
  Out-of-Bounds entry and exit (|declination| > 23°26')

Lunar node:
  North Node sign ingress (~every 18 months)

All rows use the same schema as astro_nakshatra_events_2000_2026.csv:
  time, event, impact, category, source, detail
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import swisseph as swe

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
OUT_FILE   = DATA_DIR / "gann_moon_aspects_2000_2026.csv"

START_DT = datetime(2000, 1, 1,  0,  0, tzinfo=timezone.utc)
END_DT   = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)

# ── Constants ─────────────────────────────────────────────────────────────────
SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

# Planets used for Moon aspect detection (inc. Sun for phase events)
ASPECT_PLANETS = {
    "Sun":     swe.SUN,
    "Mercury": swe.MERCURY,
    "Venus":   swe.VENUS,
    "Mars":    swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn":  swe.SATURN,
    "Uranus":  swe.URANUS,
    "Neptune": swe.NEPTUNE,
    "Pluto":   swe.PLUTO,
}

# Gann 8th-harmonic solar angles → (event name, impact, detail)
GANN_SUN_ANGLES: dict[int, tuple[str, str, str]] = {
    0:   ("Gann Spring Equinox",  "high",   "Sun 0° Aries — annual cycle begins, strongest seasonal turn"),
    45:  ("Gann 45-Day Turn",     "medium", "Sun 45° ecliptic — first intra-seasonal Gann pivot"),
    90:  ("Gann Summer Solstice", "high",   "Sun 0° Cancer — mid-year seasonal reversal zone"),
    135: ("Gann 135-Day Turn",    "medium", "Sun 135° ecliptic — second intra-seasonal Gann pivot"),
    180: ("Gann Autumn Equinox",  "high",   "Sun 0° Libra — annual cycle midpoint, balance turn"),
    225: ("Gann 225-Day Turn",    "medium", "Sun 225° ecliptic — third intra-seasonal Gann pivot"),
    270: ("Gann Winter Solstice", "high",   "Sun 0° Capricorn — year-end cycle low, cycle trough"),
    315: ("Gann 315-Day Turn",    "medium", "Sun 315° ecliptic — fourth intra-seasonal Gann pivot"),
}

# Moon phase angles → (event name, impact, detail)
MOON_PHASES: dict[int, tuple[str, str, str]] = {
    0:   ("New Moon",       "high",   "Gann: new cycle seed — accumulation zone, cycle beginning"),
    90:  ("First Quarter",  "medium", "Gann: waxing decision point — key resistance test"),
    180: ("Full Moon",      "high",   "Gann: cycle peak — distribution / reversal zone"),
    270: ("Last Quarter",   "medium", "Gann: waning decision point — key support test"),
}

# Aspect angles → (aspect name, impact)
ASPECT_DEFS: list[tuple[str, int, str]] = [
    ("conjunction", 0,   "high"),
    ("sextile",     60,  "low"),
    ("square",      90,  "medium"),
    ("trine",       120, "medium"),
    ("opposition",  180, "high"),
]

SOLAR_ECLIPSE_ORB = 18.0   # degrees: max node distance for solar eclipse
LUNAR_ECLIPSE_ORB = 11.0   # degrees: max node distance for lunar eclipse
OOB_THRESHOLD     = 23.0 + 26.0 / 60.0   # 23°26' obliquity threshold


@dataclass
class EventRow:
    time:     str
    event:    str
    impact:   str
    category: str
    source:   str
    detail:   str


# ── Swiss Ephemeris helpers ───────────────────────────────────────────────────

def dt_to_jd(dt: datetime) -> float:
    return swe.julday(
        dt.year, dt.month, dt.day,
        dt.hour + dt.minute / 60.0 + dt.second / 3600.0,
    )


def jd_to_dt(jd: float) -> datetime:
    y, m, d, h = swe.revjul(jd)
    hour   = int(h)
    min_f  = (h - hour) * 60.0
    minute = int(min_f)
    second = int(round((min_f - minute) * 60.0))
    if second >= 60:
        second, minute = 0, minute + 1
    if minute >= 60:
        minute, hour = 0, hour + 1
    return datetime(y, m, d, hour, minute, second, tzinfo=timezone.utc)


def planet_lon(jd: float, pid: int) -> float:
    """Ecliptic longitude (0–360°)."""
    return swe.calc_ut(jd, pid)[0][0] % 360.0


def planet_dist(jd: float, pid: int) -> float:
    """Distance in AU."""
    return swe.calc_ut(jd, pid)[0][2]


def moon_declination(jd: float) -> float:
    """Moon declination in degrees (equatorial coords)."""
    return swe.calc_ut(jd, swe.MOON, swe.FLG_EQUATORIAL)[0][1]


def true_node_lon(jd: float) -> float:
    """True Lunar North Node ecliptic longitude."""
    return swe.calc_ut(jd, swe.TRUE_NODE)[0][0] % 360.0


def moon_sun_elongation(jd: float) -> float:
    """(Moon_lon − Sun_lon) mod 360 — 0=New, 90=1Q, 180=Full, 270=3Q."""
    return (planet_lon(jd, swe.MOON) - planet_lon(jd, swe.SUN)) % 360.0


def moon_planet_sep(jd: float, pid: int) -> float:
    """(Moon_lon − Planet_lon) mod 360."""
    return (planet_lon(jd, swe.MOON) - planet_lon(jd, pid)) % 360.0


def cyclic_dist(a: float, b: float) -> float:
    """Minimum cyclic distance on [0, 360)."""
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def binary_search_crossing(lo_jd: float, hi_jd: float, pred, iters: int = 26) -> float:
    """Binary-search for JD where pred changes from False to True."""
    for _ in range(iters):
        mid = (lo_jd + hi_jd) / 2.0
        if not pred(mid):
            lo_jd = mid
        else:
            hi_jd = mid
    return hi_jd


# ── Detector: passage of a cyclic variable through a target angle ─────────────

def _crossing_check(prev_val: float, nxt_val: float, target: float) -> bool:
    """True when a prograde cyclic value crossed `target` between prev and nxt."""
    prev_off = (prev_val - target) % 360.0
    nxt_off  = (nxt_val  - target) % 360.0
    # A prograde crossing: prev_off was just below 360 (close to target from behind),
    # nxt_off is now just above 0 (just passed target).
    return prev_off > 350.0 and nxt_off < 10.0


# ── Event generators ──────────────────────────────────────────────────────────

def generate_gann_sun_turns(start_dt: datetime, end_dt: datetime) -> List[EventRow]:
    """Sun crosses each 45° Gann harmonic — ~8 events per year."""
    events: List[EventRow] = []
    step = timedelta(hours=12)   # Sun moves ~0.5°/hr → max 6° per step; safe for 45° sectors

    cur     = start_dt
    prev_jd = dt_to_jd(cur)
    prev_lon = planet_lon(prev_jd, swe.SUN)

    while cur < end_dt:
        nxt     = min(cur + step, end_dt)
        jd_nxt  = dt_to_jd(nxt)
        lon_nxt = planet_lon(jd_nxt, swe.SUN)

        for target_deg, (label, impact, detail) in GANN_SUN_ANGLES.items():
            if _crossing_check(prev_lon, lon_nxt, target_deg):
                td = target_deg
                t_jd = binary_search_crossing(
                    prev_jd, jd_nxt,
                    lambda x, t=td: ((planet_lon(x, swe.SUN) - t) % 360.0) < 180.0,
                )
                events.append(EventRow(
                    time=jd_to_dt(t_jd).isoformat(),
                    event=label,
                    impact=impact,
                    category="gann",
                    source="swisseph",
                    detail=detail,
                ))

        prev_lon = lon_nxt
        prev_jd  = jd_nxt
        cur      = nxt

    return events


def generate_moon_phases(start_dt: datetime, end_dt: datetime) -> List[EventRow]:
    """New/First Quarter/Full/Last Quarter Moon + solar and lunar eclipses."""
    events: List[EventRow] = []
    step = timedelta(hours=1)   # Moon elongation changes ~0.5°/hr

    cur        = start_dt
    prev_jd    = dt_to_jd(cur)
    prev_elong = moon_sun_elongation(prev_jd)

    while cur < end_dt:
        nxt       = min(cur + step, end_dt)
        jd_nxt    = dt_to_jd(nxt)
        elong_nxt = moon_sun_elongation(jd_nxt)

        for target_deg, (base_label, impact, base_detail) in MOON_PHASES.items():
            if _crossing_check(prev_elong, elong_nxt, target_deg):
                td = target_deg
                t_jd = binary_search_crossing(
                    prev_jd, jd_nxt,
                    lambda x, t=td: ((moon_sun_elongation(x) - t) % 360.0) < 180.0,
                )
                t_dt = jd_to_dt(t_jd)

                # Eclipse detection for New and Full Moon
                label  = base_label
                detail = base_detail
                evt_impact = impact

                if target_deg in (0, 180):
                    m_lon   = planet_lon(t_jd, swe.MOON)
                    n_lon   = true_node_lon(t_jd)
                    s_lon   = (n_lon + 180.0) % 360.0
                    node_d  = min(cyclic_dist(m_lon, n_lon), cyclic_dist(m_lon, s_lon))

                    if target_deg == 0 and node_d <= SOLAR_ECLIPSE_ORB:
                        label      = "Solar Eclipse"
                        evt_impact = "high"
                        detail     = (
                            f"Solar eclipse — Moon {m_lon:.1f}°, "
                            f"Node {n_lon:.1f}°, separation {node_d:.1f}°"
                        )
                    elif target_deg == 180 and node_d <= LUNAR_ECLIPSE_ORB:
                        label      = "Lunar Eclipse"
                        evt_impact = "high"
                        detail     = (
                            f"Lunar eclipse — Moon {m_lon:.1f}°, "
                            f"Node {n_lon:.1f}°, separation {node_d:.1f}°"
                        )

                events.append(EventRow(
                    time=t_dt.isoformat(),
                    event=label,
                    impact=evt_impact,
                    category="moon_phase",
                    source="swisseph",
                    detail=detail,
                ))

        prev_elong = elong_nxt
        prev_jd    = jd_nxt
        cur        = nxt

    return events


def generate_moon_aspects(start_dt: datetime, end_dt: datetime) -> List[EventRow]:
    """Moon aspects (0°/60°/90°/120°/180°) to all planets — ~800+ events/year."""
    events: List[EventRow] = []
    step = timedelta(hours=1)   # Moon moves ~0.5°/hr; sufficient resolution

    for p_name, p_id in ASPECT_PLANETS.items():
        cur      = start_dt
        prev_jd  = dt_to_jd(cur)
        prev_sep = moon_planet_sep(prev_jd, p_id)

        while cur < end_dt:
            nxt     = min(cur + step, end_dt)
            jd_nxt  = dt_to_jd(nxt)
            sep_nxt = moon_planet_sep(jd_nxt, p_id)

            for asp_name, asp_deg, asp_impact in ASPECT_DEFS:
                # Each aspect has up to 2 geometrically distinct crossing points:
                # e.g. sextile occurs at separation 60° AND 300°
                targets: list[int] = [asp_deg]
                if 0 < asp_deg < 180:
                    targets.append(360 - asp_deg)

                for t in targets:
                    if _crossing_check(prev_sep, sep_nxt, t):
                        tt = t
                        pid = p_id
                        t_jd = binary_search_crossing(
                            prev_jd, jd_nxt,
                            lambda x, td=tt, pid=pid: ((moon_planet_sep(x, pid) - td) % 360.0) < 180.0,
                        )
                        t_dt   = jd_to_dt(t_jd)
                        m_lon  = planet_lon(t_jd, swe.MOON)
                        pl_lon = planet_lon(t_jd, p_id)
                        events.append(EventRow(
                            time=t_dt.isoformat(),
                            event=f"Moon {asp_name} {p_name}",
                            impact=asp_impact,
                            category="moon_aspect",
                            source="swisseph",
                            detail=(
                                f"Moon {asp_name} {p_name} — "
                                f"Moon {m_lon:.1f}°, {p_name} {pl_lon:.1f}°"
                            ),
                        ))

            prev_sep = sep_nxt
            prev_jd  = jd_nxt
            cur      = nxt

    return events


def generate_moon_perigee_apogee(start_dt: datetime, end_dt: datetime) -> List[EventRow]:
    """Moon perigee (closest to Earth) and apogee (farthest), ~24 events/year."""
    events: List[EventRow] = []
    step = timedelta(hours=2)   # Anomalistic month ~27.55 days; 2h step is fine

    cur       = start_dt
    prev_jd   = dt_to_jd(cur)
    d_prev    = planet_dist(prev_jd, swe.MOON)

    # We need three consecutive distances to find a local min/max
    nxt       = min(cur + step, end_dt)
    jd_mid    = dt_to_jd(nxt)
    d_mid     = planet_dist(jd_mid, swe.MOON)
    cur       = nxt

    while cur < end_dt:
        nxt    = min(cur + step, end_dt)
        jd_nxt = dt_to_jd(nxt)
        d_nxt  = planet_dist(jd_nxt, swe.MOON)

        if d_prev > d_mid < d_nxt:
            # Local minimum → Perigee
            events.append(EventRow(
                time=jd_to_dt(jd_mid).isoformat(),
                event="Moon Perigee",
                impact="medium",
                category="moon_geometry",
                source="swisseph",
                detail=f"Moon perigee (closest to Earth) — distance {d_mid:.6f} AU",
            ))
        elif d_prev < d_mid > d_nxt:
            # Local maximum → Apogee
            events.append(EventRow(
                time=jd_to_dt(jd_mid).isoformat(),
                event="Moon Apogee",
                impact="low",
                category="moon_geometry",
                source="swisseph",
                detail=f"Moon apogee (farthest from Earth) — distance {d_mid:.6f} AU",
            ))

        d_prev = d_mid
        jd_mid = jd_nxt
        d_mid  = d_nxt
        prev_jd = jd_mid
        cur    = nxt

    return events


def generate_moon_oob(start_dt: datetime, end_dt: datetime) -> List[EventRow]:
    """Moon out-of-bounds entries and exits (|declination| > 23°26')."""
    events: List[EventRow] = []
    step      = timedelta(hours=2)
    threshold = OOB_THRESHOLD

    cur       = start_dt
    prev_jd   = dt_to_jd(cur)
    prev_decl = moon_declination(prev_jd)
    prev_oob  = abs(prev_decl) > threshold

    while cur < end_dt:
        nxt        = min(cur + step, end_dt)
        jd_nxt     = dt_to_jd(nxt)
        decl_nxt   = moon_declination(jd_nxt)
        oob_nxt    = abs(decl_nxt) > threshold

        if prev_oob != oob_nxt:
            th = threshold
            t_jd = binary_search_crossing(
                prev_jd, jd_nxt,
                lambda x, t=th: abs(moon_declination(x)) > t,
            )
            t_dt      = jd_to_dt(t_jd)
            decl_at   = moon_declination(t_jd)
            direction = "North" if decl_at > 0 else "South"
            going_oob = not prev_oob

            if going_oob:
                events.append(EventRow(
                    time=t_dt.isoformat(),
                    event=f"Moon Out-of-Bounds {direction}",
                    impact="medium",
                    category="moon_geometry",
                    source="swisseph",
                    detail=(
                        f"Moon declination exceeds ±{threshold:.2f}° — "
                        f"decl {decl_at:.2f}° ({direction}) OOB entry"
                    ),
                ))
            else:
                events.append(EventRow(
                    time=t_dt.isoformat(),
                    event=f"Moon Returns In-Bounds {direction}",
                    impact="low",
                    category="moon_geometry",
                    source="swisseph",
                    detail=(
                        f"Moon declination returns within ±{threshold:.2f}° — "
                        f"decl {decl_at:.2f}° ({direction}) OOB exit"
                    ),
                ))

        prev_oob  = oob_nxt
        prev_decl = decl_nxt
        prev_jd   = jd_nxt
        cur       = nxt

    return events


def generate_north_node_ingress(start_dt: datetime, end_dt: datetime) -> List[EventRow]:
    """Lunar North Node sign ingress — ~1 per 18 months, Gann 18-year axis."""
    events: List[EventRow] = []
    step = timedelta(hours=24)  # Node moves ~0.053°/day (retrograde)

    cur       = start_dt
    prev_jd   = dt_to_jd(cur)
    prev_sign = int(true_node_lon(prev_jd) // 30)

    while cur < end_dt:
        nxt      = min(cur + step, end_dt)
        jd_nxt   = dt_to_jd(nxt)
        sign_nxt = int(true_node_lon(jd_nxt) // 30)

        if sign_nxt != prev_sign:
            ps = prev_sign
            t_jd = binary_search_crossing(
                prev_jd, jd_nxt,
                lambda x, s=ps: int(true_node_lon(x) // 30) != s,
            )
            t_dt      = jd_to_dt(t_jd)
            new_sign  = int(true_node_lon(t_jd) // 30)
            from_sign = SIGNS[prev_sign % 12]
            to_sign   = SIGNS[new_sign % 12]
            events.append(EventRow(
                time=t_dt.isoformat(),
                event=f"North Node ingress {to_sign}",
                impact="high",
                category="gann",
                source="swisseph",
                detail=(
                    f"Lunar North Node: {from_sign} → {to_sign} "
                    f"(Gann: 18-yr nodal axis, karmic market shift)"
                ),
            ))
            prev_sign = sign_nxt

        prev_jd = jd_nxt
        cur     = nxt

    return events


# ── Writer ─────────────────────────────────────────────────────────────────────

def write_events(path: Path, rows: List[EventRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "event", "impact", "category", "source", "detail"])
        for r in rows:
            w.writerow([r.time, r.event, r.impact, r.category, r.source, r.detail])


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Generating Gann + Moon aspects dataset: {START_DT.date()} → {END_DT.date()}")
    print(f"Output: {OUT_FILE}")
    print()

    all_events: List[EventRow] = []

    print("[1/6] Gann solar harmonics (Sun at 45° intervals)...")
    ev = generate_gann_sun_turns(START_DT, END_DT)
    print(f"      {len(ev)} events")
    all_events.extend(ev)

    print("[2/6] Moon phases + eclipses...")
    ev = generate_moon_phases(START_DT, END_DT)
    print(f"      {len(ev)} events")
    all_events.extend(ev)

    print("[3/6] Moon aspects to planets (0°/60°/90°/120°/180°)...")
    ev = generate_moon_aspects(START_DT, END_DT)
    print(f"      {len(ev)} events")
    all_events.extend(ev)

    print("[4/6] Moon perigee / apogee...")
    ev = generate_moon_perigee_apogee(START_DT, END_DT)
    print(f"      {len(ev)} events")
    all_events.extend(ev)

    print("[5/6] Moon out-of-bounds (declination > 23°26')...")
    ev = generate_moon_oob(START_DT, END_DT)
    print(f"      {len(ev)} events")
    all_events.extend(ev)

    print("[6/6] Lunar North Node sign ingress (Gann 18-yr axis)...")
    ev = generate_north_node_ingress(START_DT, END_DT)
    print(f"      {len(ev)} events")
    all_events.extend(ev)

    # Sort all events by time
    all_events.sort(key=lambda r: r.time)

    write_events(OUT_FILE, all_events)
    print()
    print(f"✓ Wrote {len(all_events):,} total events → {OUT_FILE}")
    print()

    # Category breakdown
    from collections import Counter
    cats = Counter(r.category for r in all_events)
    for cat, n in sorted(cats.items()):
        print(f"  {cat:<20} {n:>6} events")


if __name__ == "__main__":
    main()
