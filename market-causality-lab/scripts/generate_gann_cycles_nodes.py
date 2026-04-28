#!/usr/bin/env python3
"""Generate Gann time-cycle nodes, pressure points, and cycle completion dataset (2000-2026).

Gann Rules Encoded
------------------
Rule 1: "Time hits node = MOVE"
    → encoded as `pressure_point` events (2+ independent cycles converge on same date).
      The ML model learns: high event-count windows = high-probability move zone.

Rule 2: "Price hits without time = NOISE"
    → encoded inversely: price bars with ZERO nearby events = noise; model learns to
      discount those bars. Nothing extra written for Rule 2 — its signal is the absence
      of cycle events in the feature window.

Rule 3: "Nodes = pressure points"
    → every cycle completion is its own `cycle_node` or `time_cycle` event with impact
      annotation. They create support/resistance pressure fields in the feature space.

Rule 4: "Cycle within cycle"
    → confluence detection: when 2+ independent cycles (seasonal Gann counts, planetary
      stations, synodic completions, square-of-9) fire within a 3-day window, a
      `pressure_point` event is emitted naming ALL contributing cycles.

Rule 5: "Square of time"
    → Gann squared-number day counts from Jan 1 each year (1²,2²,...20²) plus
      from each seasonal node, mark potential reversal zones.

Events Generated
----------------
1. Gann seasonal cycle nodes
   - Find exact Spring Equinox, Summer Solstice, Autumn Equinox, Winter Solstice via swe
   - Add Gann key-number day offsets from each seasonal node:
     30, 45, 60, 90, 120, 144, 180, 252, 270, 312, 360 days
   - category: `time_cycle`

2. Gann Square-of-9 day cycles
   - 1,4,9,16,25,36,49,64,81,100,121,144,169,196,225,256,289,324,361 days from Jan 1
   - category: `time_cycle`

3. Planetary retrograde/direct stations (velocity sign change)
   - Mercury, Venus, Mars, Jupiter, Saturn
   - Retrograde station = "cycle inversion node" (high impact)
   - Direct station = "cycle resumption node"
   - category: `planetary_station`

4. Synodic cycle completions (conjunctions & oppositions between planet pairs)
   - Jupiter–Saturn, Jupiter–Mars, Saturn–Mars, Venus–Jupiter, Mars–Venus
   - category: `synodic_cycle`

5. Pressure point confluences (post-processing)
   - 3-day window with 3+ events from 2+ independent categories
   - Rule 1 text embedded in detail field
   - category: `pressure_point`, impact: `high`

Output
------
market-causality-lab/data/gann_cycles_nodes_2000_2026.csv
(same schema as astro_nakshatra_events_2000_2026.csv — plug-and-play with train_ai_models.py)
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple

import swisseph as swe

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
OUT_FILE   = DATA_DIR / "gann_cycles_nodes_2000_2026.csv"

START_DT = datetime(2000, 1, 1,  0,  0, tzinfo=timezone.utc)
END_DT   = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)

# ── Gann key numbers ──────────────────────────────────────────────────────────
# These are Gann's "master time cycle" day-counts from any major cycle node.
# Based on W.D. Gann's The Tunnel Thru the Air + 45 Years in Wall Street.
GANN_DAY_COUNTS = [
    (7,   "Gann 7-Day Cycle",    "low",    "Weekly rhythm node"),
    (14,  "Gann 14-Day Cycle",   "low",    "2-week minor node"),
    (21,  "Gann 21-Day Cycle",   "low",    "3-week minor node"),
    (30,  "Gann 30-Day Cycle",   "medium", "Monthly node — 1/12 annual cycle"),
    (45,  "Gann 45-Day Cycle",   "medium", "1/8 annual cycle — first seasonal octave"),
    (60,  "Gann 60-Day Cycle",   "medium", "2-month node — 1/6 annual cycle"),
    (90,  "Gann 90-Day Cycle",   "high",   "Quarter-year node — seasonal turn zone"),
    (120, "Gann 120-Day Cycle",  "medium", "1/3 annual cycle node"),
    (144, "Gann 144-Day Cycle",  "high",   "Gann sacred number — inner 144° cycle"),
    (180, "Gann 180-Day Cycle",  "high",   "Half-year reversal node — cycle midpoint"),
    (210, "Gann 210-Day Cycle",  "low",    "7-month node"),
    (270, "Gann 270-Day Cycle",  "high",   "3/4 annual node — final seasonal turn"),
    (315, "Gann 315-Day Cycle",  "medium", "7/8 annual node"),
    (360, "Gann 360-Day Cycle",  "high",   "Annual cycle completion — full revolution"),
]

# Gann square-of-9 day counts (N² days from Jan 1 and seasonal nodes)
GANN_SQUARES = [n * n for n in range(1, 21)]  # 1,4,9,...,361,400

# Seasonal target Sun longitudes → (angle, season name)
SEASONAL_NODES: List[Tuple[float, str]] = [
    (0.0,   "Spring Equinox"),
    (90.0,  "Summer Solstice"),
    (180.0, "Autumn Equinox"),
    (270.0, "Winter Solstice"),
]

# Planets for station detection and their sweep step (hours)
STATION_PLANETS = {
    "Mercury": (swe.MERCURY, 4),
    "Venus":   (swe.VENUS,   8),
    "Mars":    (swe.MARS,    12),
    "Jupiter": (swe.JUPITER, 24),
    "Saturn":  (swe.SATURN,  24),
}

# Planet pairs for synodic event detection (conjunction=0°, opposition=180°)
SYNODIC_PAIRS: List[Tuple[str, int, str, int, int, str]] = [
    # (p1_name, p1_id, p2_name, p2_id, step_hours, impact)
    ("Jupiter", swe.JUPITER, "Saturn",  swe.SATURN,  24, "high"),
    ("Jupiter", swe.JUPITER, "Mars",    swe.MARS,    12, "medium"),
    ("Saturn",  swe.SATURN,  "Mars",    swe.MARS,    12, "medium"),
    ("Venus",   swe.VENUS,   "Jupiter", swe.JUPITER, 8,  "medium"),
    ("Mars",    swe.MARS,    "Venus",   swe.VENUS,   8,  "low"),
    ("Jupiter", swe.JUPITER, "Uranus",  swe.URANUS,  24, "high"),
    ("Saturn",  swe.SATURN,  "Pluto",   swe.PLUTO,   24, "high"),
]

SYNODIC_TARGETS = [0.0, 180.0]   # conjunction, opposition

# Pressure point detection parameters
PP_WINDOW_DAYS  = 2    # ±2 days around center date
PP_MIN_EVENTS   = 3    # at least 3 events in window
PP_MIN_CATS     = 2    # from at least 2 different categories
PP_GAP_DAYS     = 4    # min separation between pressure points (NMS)


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
    return swe.calc_ut(jd, pid)[0][0] % 360.0


def planet_speed(jd: float, pid: int) -> float:
    """Longitudinal speed deg/day. Negative = retrograde."""
    return swe.calc_ut(jd, pid)[0][3]


def cyclic_dist(a: float, b: float) -> float:
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def _crossing_check(prev_val: float, nxt_val: float, target: float) -> bool:
    """True when a prograde cyclic value crossed `target` between prev and nxt."""
    prev_off = (prev_val - target) % 360.0
    nxt_off  = (nxt_val  - target) % 360.0
    return prev_off > 350.0 and nxt_off < 10.0


def binary_search_crossing(lo_jd: float, hi_jd: float, pred, iters: int = 26) -> float:
    for _ in range(iters):
        mid = (lo_jd + hi_jd) / 2.0
        if not pred(mid):
            lo_jd = mid
        else:
            hi_jd = mid
    return hi_jd


# ── Step 1: Find seasonal node JDs ────────────────────────────────────────────

def find_seasonal_nodes(start_dt: datetime, end_dt: datetime) -> List[Tuple[float, str]]:
    """Return list of (jd, season_name) for all equinoxes and solstices in range."""
    nodes: List[Tuple[float, str]] = []
    step  = timedelta(hours=12)

    cur      = start_dt
    prev_jd  = dt_to_jd(cur)
    prev_lon = planet_lon(prev_jd, swe.SUN)

    while cur < end_dt:
        nxt    = min(cur + step, end_dt)
        jd_nxt = dt_to_jd(nxt)
        lon_nxt = planet_lon(jd_nxt, swe.SUN)

        for target, season_name in SEASONAL_NODES:
            if _crossing_check(prev_lon, lon_nxt, target):
                td = target
                t_jd = binary_search_crossing(
                    prev_jd, jd_nxt,
                    lambda x, t=td: ((planet_lon(x, swe.SUN) - t) % 360.0) < 180.0,
                )
                nodes.append((t_jd, season_name))

        prev_lon = lon_nxt
        prev_jd  = jd_nxt
        cur      = nxt

    return sorted(nodes, key=lambda x: x[0])


# ── Step 2: Gann day-count cycles from seasonal nodes ────────────────────────

def generate_gann_day_cycles(
    seasonal_nodes: List[Tuple[float, str]],
    end_dt: datetime,
) -> List[EventRow]:
    events: List[EventRow] = []
    end_jd = dt_to_jd(end_dt)

    for node_jd, season_name in seasonal_nodes:
        node_dt = jd_to_dt(node_jd)
        for days, label, impact, desc in GANN_DAY_COUNTS:
            target_dt = node_dt + timedelta(days=days)
            target_jd = dt_to_jd(target_dt)
            if target_jd > end_jd:
                continue
            events.append(EventRow(
                time=target_dt.replace(tzinfo=timezone.utc).isoformat()
                     if target_dt.tzinfo is None
                     else target_dt.isoformat(),
                event=f"{label} from {season_name}",
                impact=impact,
                category="time_cycle",
                source="gann_rules",
                detail=(
                    f"Rule3: 'Nodes=pressure points' — {days}-day cycle completes "
                    f"from {season_name} ({node_dt.strftime('%Y-%m-%d')}); {desc}"
                ),
            ))

    return events


# ── Step 3: Gann square-of-9 cycles from Jan 1 each year ─────────────────────

def generate_gann_squares(start_dt: datetime, end_dt: datetime) -> List[EventRow]:
    events: List[EventRow] = []
    end_jd = dt_to_jd(end_dt)

    year = start_dt.year
    while year <= end_dt.year:
        origin = datetime(year, 1, 1, 0, 0, tzinfo=timezone.utc)
        for n_sq in GANN_SQUARES:
            n = int(n_sq ** 0.5)
            target_dt = origin + timedelta(days=n_sq)
            if dt_to_jd(target_dt) > end_jd:
                break
            impact = "high" if n_sq in (144, 225, 289, 361) else "medium" if n_sq in (81, 100, 121, 196) else "low"
            events.append(EventRow(
                time=target_dt.isoformat(),
                event=f"Gann Square-of-9 ({n}²={n_sq} days from Jan 1)",
                impact=impact,
                category="time_cycle",
                source="gann_rules",
                detail=(
                    f"Rule5: 'Square of time' — {n}²={n_sq} calendar days from "
                    f"{year}-01-01; reversal zone in Gann Square-of-9 methodology"
                ),
            ))
        year += 1

    return events


# ── Step 4: Planetary retrograde/direct stations ──────────────────────────────

def generate_planetary_stations(start_dt: datetime, end_dt: datetime) -> List[EventRow]:
    """Detect speed sign changes (direct↔retrograde) for inner and outer planets."""
    events: List[EventRow] = []

    for p_name, (p_id, step_h) in STATION_PLANETS.items():
        step   = timedelta(hours=step_h)
        cur    = start_dt
        prev_jd = dt_to_jd(cur)
        prev_spd = planet_speed(prev_jd, p_id)

        while cur < end_dt:
            nxt    = min(cur + step, end_dt)
            jd_nxt = dt_to_jd(nxt)
            spd_nxt = planet_speed(jd_nxt, p_id)

            # Sign change detected
            if (prev_spd > 0 and spd_nxt < 0) or (prev_spd < 0 and spd_nxt > 0):
                going_retro = prev_spd > 0 and spd_nxt < 0
                # Binary search precise crossing
                ps = prev_spd
                t_jd = binary_search_crossing(
                    prev_jd, jd_nxt,
                    lambda x, pid=p_id, ps=ps: (
                        planet_speed(x, pid) < 0 if ps > 0 else planet_speed(x, pid) >= 0
                    ),
                )
                t_dt    = jd_to_dt(t_jd)
                lon_at  = planet_lon(t_jd, p_id)
                sign_at = int(lon_at // 30)
                signs   = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo",
                           "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]

                if going_retro:
                    label  = f"{p_name} Station Retrograde"
                    impact = "high"
                    detail = (
                        f"Rule1: 'Time hits node=MOVE' — {p_name} turns retrograde at "
                        f"{lon_at:.2f}° ({signs[sign_at]}); cycle inversion node"
                    )
                else:
                    label  = f"{p_name} Station Direct"
                    impact = "medium"
                    detail = (
                        f"Rule3: 'Nodes=pressure points' — {p_name} turns direct at "
                        f"{lon_at:.2f}° ({signs[sign_at]}); cycle resumption node"
                    )

                events.append(EventRow(
                    time=t_dt.isoformat(),
                    event=label,
                    impact=impact,
                    category="planetary_station",
                    source="swisseph",
                    detail=detail,
                ))

            prev_spd = spd_nxt
            prev_jd  = jd_nxt
            cur      = nxt

    return events


# ── Step 5: Synodic cycle events (conjunctions & oppositions) ─────────────────

def _sep_between(jd: float, pid1: int, pid2: int) -> float:
    """(lon1 - lon2) mod 360."""
    return (planet_lon(jd, pid1) - planet_lon(jd, pid2)) % 360.0


def generate_synodic_events(start_dt: datetime, end_dt: datetime) -> List[EventRow]:
    events: List[EventRow] = []

    for p1_name, p1_id, p2_name, p2_id, step_h, impact in SYNODIC_PAIRS:
        step    = timedelta(hours=step_h)
        cur     = start_dt
        prev_jd = dt_to_jd(cur)
        prev_sep = _sep_between(prev_jd, p1_id, p2_id)

        while cur < end_dt:
            nxt     = min(cur + step, end_dt)
            jd_nxt  = dt_to_jd(nxt)
            sep_nxt = _sep_between(jd_nxt, p1_id, p2_id)

            for target in SYNODIC_TARGETS:
                targets: List[float] = [target]
                if 0 < target < 180:
                    targets.append(360.0 - target)

                for t in targets:
                    if _crossing_check(prev_sep, sep_nxt, t):
                        tt = t
                        t_jd = binary_search_crossing(
                            prev_jd, jd_nxt,
                            lambda x, tt=tt, pid1=p1_id, pid2=p2_id:
                                ((_sep_between(x, pid1, pid2) - tt) % 360.0) < 180.0,
                        )
                        t_dt  = jd_to_dt(t_jd)
                        aspect_name = "conjunction" if abs(t) < 1 else "opposition"
                        lon1  = planet_lon(t_jd, p1_id)
                        lon2  = planet_lon(t_jd, p2_id)
                        events.append(EventRow(
                            time=t_dt.isoformat(),
                            event=f"{p1_name}–{p2_name} {aspect_name}",
                            impact=impact,
                            category="synodic_cycle",
                            source="swisseph",
                            detail=(
                                f"Rule4: 'Cycle within cycle' — {p1_name} {aspect_name} "
                                f"{p2_name}: {p1_name} {lon1:.1f}°, {p2_name} {lon2:.1f}°; "
                                f"synodic cycle completion node"
                            ),
                        ))

            prev_sep = sep_nxt
            prev_jd  = jd_nxt
            cur      = nxt

    return events


# ── Step 6: Pressure point confluence detection ───────────────────────────────

def detect_pressure_points(all_events: List[EventRow]) -> List[EventRow]:
    """
    Find dates where multiple independent cycle events cluster (Rule 1: Time hits node = MOVE).
    Uses greedy non-maximum suppression to avoid overlapping pressure points.
    """
    # Group by date string YYYY-MM-DD
    date_events: dict = defaultdict(list)
    for ev in all_events:
        day = ev.time[:10]
        date_events[day].append(ev)

    sorted_dates = sorted(date_events.keys())

    # For each date, compute density in ±PP_WINDOW_DAYS window
    densities: dict = {}
    for center in sorted_dates:
        dt_c = datetime.fromisoformat(center)
        nearby: List[EventRow] = []
        for d in sorted_dates:
            diff = abs((datetime.fromisoformat(d) - dt_c).days)
            if diff <= PP_WINDOW_DAYS:
                nearby.extend(date_events[d])
        cats = {e.category for e in nearby}
        if len(nearby) >= PP_MIN_EVENTS and len(cats) >= PP_MIN_CATS:
            densities[center] = (len(nearby), cats, nearby)

    if not densities:
        return []

    # Greedy NMS: pick highest-density date first, suppress neighbors within PP_GAP_DAYS
    ranked = sorted(densities.keys(), key=lambda d: -densities[d][0])
    used: List[datetime] = []
    pressure_points: List[EventRow] = []

    for date_str in ranked:
        dt = datetime.fromisoformat(date_str)
        if any(abs((dt - u).days) < PP_GAP_DAYS for u in used):
            continue
        used.append(dt)

        count, cats, nearby = densities[date_str]
        cat_list = ", ".join(sorted(cats))

        # Summarize contributing events
        contrib_labels = list({e.event for e in nearby})[:6]
        contrib_str    = "; ".join(contrib_labels)

        impact = "high" if count >= 5 or "synodic_cycle" in cats else "medium"

        pressure_points.append(EventRow(
            time=dt.replace(hour=12, minute=0, second=0, tzinfo=timezone.utc).isoformat(),
            event=f"Gann Pressure Point ({count} cycles align)",
            impact=impact,
            category="pressure_point",
            source="gann_rules",
            detail=(
                f"Rule1:'Time hits node=MOVE' | Rule3:'Nodes=pressure points' | "
                f"Rule4:'Cycle within cycle' | "
                f"{count} confluences from [{cat_list}] | "
                f"cycles: {contrib_str}"
            ),
        ))

    return sorted(pressure_points, key=lambda r: r.time)


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
    print(f"Generating Gann cycles + nodes + pressure points: {START_DT.date()} → {END_DT.date()}")
    print(f"Output: {OUT_FILE}")
    print()

    all_events: List[EventRow] = []

    print("[1/6] Finding seasonal cycle nodes (equinoxes/solstices)...")
    seasonal_nodes = find_seasonal_nodes(START_DT, END_DT)
    print(f"      {len(seasonal_nodes)} seasonal nodes found")

    print("[2/6] Gann key-number day cycles from seasonal nodes...")
    ev = generate_gann_day_cycles(seasonal_nodes, END_DT)
    print(f"      {len(ev)} events")
    all_events.extend(ev)

    print("[3/6] Gann Square-of-9 time cycles from Jan 1 each year...")
    ev = generate_gann_squares(START_DT, END_DT)
    print(f"      {len(ev)} events")
    all_events.extend(ev)

    print("[4/6] Planetary retrograde/direct stations...")
    ev = generate_planetary_stations(START_DT, END_DT)
    print(f"      {len(ev)} events")
    all_events.extend(ev)

    print("[5/6] Synodic cycle completions (conjunctions & oppositions)...")
    ev = generate_synodic_events(START_DT, END_DT)
    print(f"      {len(ev)} events  (Jupiter-Saturn, Jupiter-Mars, Saturn-Mars, Venus-Jupiter, Mars-Venus, Jupiter-Uranus, Saturn-Pluto)")
    all_events.extend(ev)

    # Sort before pressure-point detection
    all_events.sort(key=lambda r: r.time)

    print("[6/6] Detecting Gann pressure points (cycle confluences)...")
    pressure_pts = detect_pressure_points(all_events)
    print(f"      {len(pressure_pts)} pressure points (Rule 1: Time hits node = MOVE)")
    all_events.extend(pressure_pts)

    # Final sort
    all_events.sort(key=lambda r: r.time)

    write_events(OUT_FILE, all_events)
    print()
    print(f"✓ Wrote {len(all_events):,} total events → {OUT_FILE}")
    print()

    # Category breakdown
    from collections import Counter
    cats = Counter(r.category for r in all_events)
    for cat, n in sorted(cats.items()):
        rule = {
            "time_cycle":        "Rule2(absence=noise)/Rule3/Rule5",
            "planetary_station": "Rule1/Rule3  (retrograde=cycle inversion)",
            "synodic_cycle":     "Rule4        (cycle within cycle)",
            "pressure_point":    "Rule1        (time hits node = MOVE)",
        }.get(cat, "")
        print(f"  {cat:<22} {n:>5} events   {rule}")

    print()
    # Impact breakdown
    impacts = Counter(r.impact for r in all_events)
    print("  Impact breakdown:")
    for imp, n in sorted(impacts.items()):
        print(f"    {imp:<8} {n:>5}")


if __name__ == "__main__":
    main()
