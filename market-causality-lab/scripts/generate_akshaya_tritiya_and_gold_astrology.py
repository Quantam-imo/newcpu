#!/usr/bin/env python3
"""Generate Akshaya Tritiya event rows and astrology/gold movement reports.

Outputs:
- market-causality-lab/data/akshaya_tritiya_events_2000_2026.csv
- market-causality-lab/data/reports/akshaya_tritiya_dates_2000_2026.csv
- market-causality-lab/data/reports/gold_moving_astrology_dates_2000_2026.csv
- market-causality-lab/data/reports/gold_moving_astrology_event_families_2000_2026.csv

Method:
- Anchor Akshaya Tritiya off the first Aries-season New Moon or Solar Eclipse in each year.
- Select the local IST date with the largest Tritiya overlap during Indian daytime.
- Rank astrology events against XAU daily absolute returns to identify recurring
  gold-moving event families and strongest individual dates.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd
import swisseph as swe


IST = timezone(timedelta(hours=5, minutes=30))
START_YEAR = 2000
END_YEAR = 2026
TRADING_DAY_START_HOUR = 6
TRADING_DAY_END_HOUR = 18
MAX_REASONABLE_DAILY_MOVE_PCT = 20.0

BASE_DIR = Path("market-causality-lab")
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"

MOON_PHASES_CSV = DATA_DIR / "gann_moon_aspects_2000_2026.csv"
ASTRO_EVENTS_CSV = DATA_DIR / "astro_nakshatra_events_2000_2026.csv"
GANN_CYCLES_CSV = DATA_DIR / "gann_cycles_nodes_2000_2026.csv"
XAU_DAILY_CSV = DATA_DIR / "XAU_1d_data.csv"

AKSHAYA_EVENTS_CSV = DATA_DIR / "akshaya_tritiya_events_2000_2026.csv"
AKSHAYA_REPORT_CSV = REPORTS_DIR / "akshaya_tritiya_dates_2000_2026.csv"
GOLD_MOVING_DATES_CSV = REPORTS_DIR / "gold_moving_astrology_dates_2000_2026.csv"
GOLD_MOVING_FAMILIES_CSV = REPORTS_DIR / "gold_moving_astrology_event_families_2000_2026.csv"


@dataclass
class AkshayaRow:
    year: int
    anchor_event: str
    anchor_time_utc: str
    anchor_time_ist: str
    tritiya_start_ist: str
    tritiya_end_ist: str
    selected_date_ist: str
    overlap_minutes_ist: int
    event_time_utc: str


def _ensure_dirs() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _jd(dt_utc: datetime) -> float:
    return swe.julday(
        dt_utc.year,
        dt_utc.month,
        dt_utc.day,
        dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0,
    )


def _sidereal_longitude(dt_local: datetime, body: int) -> float:
    dt_utc = dt_local.astimezone(timezone.utc)
    return swe.calc_ut(_jd(dt_utc), body, swe.FLG_SIDEREAL)[0][0] % 360.0


def _sun_sidereal_longitude(dt_local: datetime) -> float:
    return _sidereal_longitude(dt_local, swe.SUN)


def _moon_sun_elongation(dt_local: datetime) -> float:
    moon = _sidereal_longitude(dt_local, swe.MOON)
    sun = _sun_sidereal_longitude(dt_local)
    return (moon - sun) % 360.0


def _tithi_number(dt_local: datetime) -> int:
    return int(_moon_sun_elongation(dt_local) // 12.0) + 1


def _cross_elongation(start: datetime, end: datetime, target_deg: float) -> datetime | None:
    current = start
    prev = _moon_sun_elongation(current) - target_deg
    while current < end:
        nxt = current + timedelta(minutes=15)
        value = _moon_sun_elongation(nxt) - target_deg
        if prev == 0 or value == 0 or (prev < 0 <= value) or (prev > 0 >= value):
            return nxt
        current = nxt
        prev = value
    return None


def _load_aries_season_new_moons() -> list[tuple[str, datetime]]:
    rows: list[tuple[str, datetime]] = []
    with MOON_PHASES_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            event = str(row.get("event") or "")
            if event not in {"New Moon", "Solar Eclipse"}:
                continue
            dt_utc = datetime.fromisoformat(str(row["time"]))
            dt_local = dt_utc.astimezone(IST)
            sun_lon = _sun_sidereal_longitude(dt_local)
            if 0.0 <= sun_lon < 30.0:
                rows.append((event, dt_utc))
    return rows


def _select_akshaya_rows() -> list[AkshayaRow]:
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    anchors = _load_aries_season_new_moons()
    out: list[AkshayaRow] = []

    for year in range(START_YEAR, END_YEAR + 1):
        candidates = [
            (event, dt_utc)
            for event, dt_utc in anchors
            if dt_utc.astimezone(IST).year == year
        ]
        if not candidates:
            continue

        anchor_event, anchor_utc = candidates[0]
        anchor_ist = anchor_utc.astimezone(IST)
        t3_start = _cross_elongation(anchor_ist, anchor_ist + timedelta(days=5), 24.0)
        if t3_start is None:
            continue
        t3_end = _cross_elongation(t3_start, anchor_ist + timedelta(days=5), 36.0)
        if t3_end is None:
            continue

        scores: list[tuple[date, int]] = []
        day = t3_start.date()
        while day <= t3_end.date():
            overlap_minutes = 0
            current = datetime.combine(day, time(TRADING_DAY_START_HOUR, 0), tzinfo=IST)
            day_end = datetime.combine(day, time(TRADING_DAY_END_HOUR, 0), tzinfo=IST)
            while current < day_end:
                if _tithi_number(current) == 3:
                    overlap_minutes += 15
                current += timedelta(minutes=15)
            scores.append((day, overlap_minutes))
            day += timedelta(days=1)

        selected_day, overlap = max(scores, key=lambda item: (item[1], -item[0].toordinal()))
        selected_dt_ist = datetime.combine(selected_day, time(9, 15), tzinfo=IST)
        out.append(
            AkshayaRow(
                year=year,
                anchor_event=anchor_event,
                anchor_time_utc=anchor_utc.isoformat(),
                anchor_time_ist=anchor_ist.isoformat(),
                tritiya_start_ist=t3_start.isoformat(),
                tritiya_end_ist=t3_end.isoformat(),
                selected_date_ist=selected_day.isoformat(),
                overlap_minutes_ist=int(overlap),
                event_time_utc=selected_dt_ist.astimezone(timezone.utc).isoformat(),
            )
        )

    return out


def _write_akshaya_outputs(rows: list[AkshayaRow]) -> None:
    with AKSHAYA_EVENTS_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "event", "impact", "category", "source", "detail"])
        for row in rows:
            writer.writerow([
                row.event_time_utc,
                "Akshaya Tritiya",
                "high",
                "astrology",
                "swisseph_derived",
                f"Akshaya Tritiya {row.year} — anchor {row.anchor_event}, Tritiya window {row.tritiya_start_ist} -> {row.tritiya_end_ist}, selected IST date {row.selected_date_ist}",
            ])

    with AKSHAYA_REPORT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "year",
            "anchor_event",
            "anchor_time_utc",
            "anchor_time_ist",
            "tritiya_start_ist",
            "tritiya_end_ist",
            "selected_date_ist",
            "overlap_minutes_ist",
            "event_time_utc",
        ])
        for row in rows:
            writer.writerow([
                row.year,
                row.anchor_event,
                row.anchor_time_utc,
                row.anchor_time_ist,
                row.tritiya_start_ist,
                row.tritiya_end_ist,
                row.selected_date_ist,
                row.overlap_minutes_ist,
                row.event_time_utc,
            ])


def _normalize_event_family(event_name: str) -> str:
    event = str(event_name or "").strip()
    if event == "Akshaya Tritiya":
        return event
    if "ingress to" in event:
        return event.split(" ingress to ", 1)[0] + " ingress"
    if event.startswith("Moon nakshatra enters "):
        return event.replace("Moon nakshatra enters ", "Nakshatra: ")
    if event.startswith("Moon "):
        parts = event.split()
        return " ".join(parts[:2]) if len(parts) >= 2 else event
    if event.startswith("Gann "):
        return event.split(":", 1)[0]
    return event


def _load_xau_daily() -> pd.DataFrame:
    df = pd.read_csv(XAU_DAILY_CSV, sep=None, engine="python")
    df.columns = [str(col).strip().lower() for col in df.columns]
    time_col = "time" if "time" in df.columns else "date"
    close_col = "close"
    df[time_col] = pd.to_datetime(df[time_col], errors="coerce", utc=True)
    if time_col != "time":
        df["time"] = df[time_col]
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    close = pd.to_numeric(df[close_col], errors="coerce")
    df["close"] = close
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    df["event_date"] = df["time"].dt.date
    df["same_day_return_pct"] = close.pct_change() * 100.0
    df["next_day_return_pct"] = close.shift(-1).div(close).sub(1.0) * 100.0
    df.loc[df["same_day_return_pct"].abs() > MAX_REASONABLE_DAILY_MOVE_PCT, "same_day_return_pct"] = pd.NA
    df.loc[df["next_day_return_pct"].abs() > MAX_REASONABLE_DAILY_MOVE_PCT, "next_day_return_pct"] = pd.NA
    df["same_day_abs_return_pct"] = df["same_day_return_pct"].abs()
    df["next_day_abs_return_pct"] = df["next_day_return_pct"].abs()
    return df


def _load_all_astro_events() -> pd.DataFrame:
    frames = []
    for path in [ASTRO_EVENTS_CSV, MOON_PHASES_CSV, GANN_CYCLES_CSV, AKSHAYA_EVENTS_CSV]:
        frame = pd.read_csv(path)
        frame["time"] = pd.to_datetime(frame["time"], errors="coerce", utc=True)
        frame = frame.dropna(subset=["time"]).copy()
        frame["event_date"] = frame["time"].dt.date
        frame["event_family"] = frame["event"].map(_normalize_event_family)
        frames.append(frame)
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values("time").reset_index(drop=True)
    merged = merged.drop_duplicates(subset=["time", "event", "detail"], keep="first")
    return merged


def _write_gold_astrology_reports() -> tuple[pd.DataFrame, pd.DataFrame]:
    price_df = _load_xau_daily()
    events_df = _load_all_astro_events()

    merged = events_df.merge(
        price_df[[
            "event_date",
            "close",
            "same_day_return_pct",
            "next_day_return_pct",
            "same_day_abs_return_pct",
            "next_day_abs_return_pct",
        ]],
        on="event_date",
        how="left",
    )
    merged["gold_move_score"] = merged[["same_day_abs_return_pct", "next_day_abs_return_pct"]].fillna(0.0).sum(axis=1)

    dates_report = merged.sort_values(
        ["gold_move_score", "next_day_abs_return_pct", "same_day_abs_return_pct"],
        ascending=[False, False, False],
    )[[
        "event_date",
        "time",
        "event",
        "event_family",
        "impact",
        "category",
        "source",
        "same_day_return_pct",
        "next_day_return_pct",
        "same_day_abs_return_pct",
        "next_day_abs_return_pct",
        "gold_move_score",
        "detail",
    ]].head(200)

    families = merged.groupby("event_family", dropna=False).agg(
        occurrences=("event_family", "size"),
        avg_same_day_abs_return_pct=("same_day_abs_return_pct", "mean"),
        avg_next_day_abs_return_pct=("next_day_abs_return_pct", "mean"),
        avg_gold_move_score=("gold_move_score", "mean"),
        max_same_day_abs_return_pct=("same_day_abs_return_pct", "max"),
        max_next_day_abs_return_pct=("next_day_abs_return_pct", "max"),
    ).reset_index()
    families = families[families["occurrences"] >= 5].sort_values(
        ["avg_gold_move_score", "avg_next_day_abs_return_pct", "occurrences"],
        ascending=[False, False, False],
    )

    dates_report.to_csv(GOLD_MOVING_DATES_CSV, index=False)
    families.to_csv(GOLD_MOVING_FAMILIES_CSV, index=False)
    return dates_report, families


def main() -> None:
    _ensure_dirs()
    akshaya_rows = _select_akshaya_rows()
    _write_akshaya_outputs(akshaya_rows)
    dates_report, families = _write_gold_astrology_reports()

    print(f"Wrote {len(akshaya_rows)} Akshaya Tritiya rows -> {AKSHAYA_EVENTS_CSV}")
    if akshaya_rows:
        print(f"Akshaya coverage: {akshaya_rows[0].year} -> {akshaya_rows[-1].year}")
        for row in akshaya_rows[-5:]:
            print(f"  {row.year}: {row.selected_date_ist}")
    print(f"Wrote gold-moving date report -> {GOLD_MOVING_DATES_CSV} ({len(dates_report)} rows)")
    print(f"Wrote gold-moving family report -> {GOLD_MOVING_FAMILIES_CSV} ({len(families)} rows)")
    if not families.empty:
        top = families.head(5)[["event_family", "occurrences", "avg_gold_move_score"]]
        print(top.to_string(index=False))


if __name__ == "__main__":
    main()