#!/usr/bin/env python3
"""Generate astrology timing datasets (planetary ingresses + nakshatra transitions).

Outputs:
- market-causality-lab/data/astro_planetary_ingress_2000_2026.csv
- market-causality-lab/data/nakshatra_transitions_2000_2026.csv
- market-causality-lab/data/astro_nakshatra_events_2000_2026.csv

All files include a `time` column and are compatible with load_news_data.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import swisseph as swe


PLANETS = {
    "Sun": (swe.SUN, "high"),
    "Moon": (swe.MOON, "medium"),
    "Mercury": (swe.MERCURY, "low"),
    "Venus": (swe.VENUS, "low"),
    "Mars": (swe.MARS, "medium"),
    "Jupiter": (swe.JUPITER, "medium"),
    "Saturn": (swe.SATURN, "high"),
    "Uranus": (swe.URANUS, "medium"),
    "Neptune": (swe.NEPTUNE, "medium"),
    "Pluto": (swe.PLUTO, "high"),
}

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]

OUT_INGRESS = Path("market-causality-lab/data/astro_planetary_ingress_2000_2026.csv")
OUT_NAK = Path("market-causality-lab/data/nakshatra_transitions_2000_2026.csv")
OUT_COMBINED = Path("market-causality-lab/data/astro_nakshatra_events_2000_2026.csv")


@dataclass
class EventRow:
    time: str
    event: str
    impact: str
    category: str
    source: str
    detail: str


def dt_to_jd(dt_utc: datetime) -> float:
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0)


def jd_to_dt(jd: float) -> datetime:
    y, m, d, h = swe.revjul(jd)
    hour = int(h)
    minute_f = (h - hour) * 60.0
    minute = int(minute_f)
    second = int(round((minute_f - minute) * 60.0))
    if second >= 60:
        second = 59
    return datetime(y, m, d, hour, minute, second, tzinfo=timezone.utc)


def planet_longitude(jd: float, p_id: int) -> float:
    return swe.calc_ut(jd, p_id)[0][0] % 360.0


def sign_index(lon: float) -> int:
    return int(lon // 30.0)


def nak_index(lon: float) -> int:
    seg = 360.0 / 27.0
    return int((lon % 360.0) // seg)


def binary_search_transition(lo_jd: float, hi_jd: float, pred, iterations: int = 22) -> float:
    lo_val = pred(lo_jd)
    for _ in range(iterations):
        mid = (lo_jd + hi_jd) / 2.0
        mid_val = pred(mid)
        if mid_val == lo_val:
            lo_jd = mid
        else:
            hi_jd = mid
    return hi_jd


def generate_ingress_events(start_dt: datetime, end_dt: datetime) -> list[EventRow]:
    events: list[EventRow] = []

    for p_name, (p_id, impact) in PLANETS.items():
        step_hours = 6 if p_name == "Moon" else 24

        cur = start_dt
        prev_jd = dt_to_jd(cur)
        prev_sign = sign_index(planet_longitude(prev_jd, p_id))

        while cur < end_dt:
            nxt = min(cur + timedelta(hours=step_hours), end_dt)
            jd_nxt = dt_to_jd(nxt)
            sign_nxt = sign_index(planet_longitude(jd_nxt, p_id))

            if sign_nxt != prev_sign:
                pred = lambda x, pid=p_id: sign_index(planet_longitude(x, pid))
                t_jd = binary_search_transition(prev_jd, jd_nxt, pred)
                t_dt = jd_to_dt(t_jd)
                from_sign = SIGNS[prev_sign]
                to_sign = SIGNS[sign_nxt]
                events.append(
                    EventRow(
                        time=t_dt.isoformat(),
                        event=f"{p_name} ingress to {to_sign}",
                        impact=impact,
                        category="astrology",
                        source="swisseph",
                        detail=f"{p_name}: {from_sign} -> {to_sign}",
                    )
                )
                prev_sign = sign_nxt

            cur = nxt
            prev_jd = jd_nxt

    return sorted(events, key=lambda r: r.time)


def generate_nakshatra_events(start_dt: datetime, end_dt: datetime) -> list[EventRow]:
    events: list[EventRow] = []

    cur = start_dt
    prev_jd = dt_to_jd(cur)
    prev_nak = nak_index(planet_longitude(prev_jd, swe.MOON))

    while cur < end_dt:
        nxt = min(cur + timedelta(hours=1), end_dt)
        jd_nxt = dt_to_jd(nxt)
        nak_nxt = nak_index(planet_longitude(jd_nxt, swe.MOON))

        if nak_nxt != prev_nak:
            pred = lambda x: nak_index(planet_longitude(x, swe.MOON))
            t_jd = binary_search_transition(prev_jd, jd_nxt, pred)
            t_dt = jd_to_dt(t_jd)
            from_nak = NAKSHATRAS[prev_nak]
            to_nak = NAKSHATRAS[nak_nxt]
            events.append(
                EventRow(
                    time=t_dt.isoformat(),
                    event=f"Moon nakshatra enters {to_nak}",
                    impact="medium",
                    category="nakshatra",
                    source="swisseph",
                    detail=f"Moon nakshatra: {from_nak} -> {to_nak}",
                )
            )
            prev_nak = nak_nxt

        cur = nxt
        prev_jd = jd_nxt

    return sorted(events, key=lambda r: r.time)


def write_events(path: Path, rows: list[EventRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "event", "impact", "category", "source", "detail"])
        for r in rows:
            w.writerow([r.time, r.event, r.impact, r.category, r.source, r.detail])


def main() -> None:
    start_dt = datetime(2000, 1, 1, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)

    ingress = generate_ingress_events(start_dt, end_dt)
    nakshatra = generate_nakshatra_events(start_dt, end_dt)
    combined = sorted(ingress + nakshatra, key=lambda r: r.time)

    write_events(OUT_INGRESS, ingress)
    write_events(OUT_NAK, nakshatra)
    write_events(OUT_COMBINED, combined)

    print(f"Wrote {len(ingress)} rows -> {OUT_INGRESS}")
    print(f"Wrote {len(nakshatra)} rows -> {OUT_NAK}")
    print(f"Wrote {len(combined)} rows -> {OUT_COMBINED}")
    if combined:
        print(f"Coverage: {combined[0].time} -> {combined[-1].time}")


if __name__ == "__main__":
    main()
