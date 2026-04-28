"""
Master Cycle Generator — Full 25-Year Ordered Cycle Dataset
============================================================
Generates a COMPLETE, ORDERED cycle ledger from 2000-01-01 to today with:

  • Moon cycles    — New Moon → 1Q → Full Moon → 3Q → New Moon (29.5d each)
  • Nakshatra      — All 27 nakshatras in Vedic sequence order, Moon transit timing
  • Planetary      — Every planet's ingress through signs + retrograde stations
                     with exact degree at each event
  • Gann nodes     — Square-of-9, seasonal nodes, pressure points, synodic cycles
  • Cycle Arcs     — Each cycle has: start_time, end_time, duration_days,
                     cycle_type, sub_type, degree_start, degree_end,
                     phase_sequence (0..1), label

OUTPUT (in strict chronological order):
  data/reports/master_cycles_25y.csv
  data/reports/master_cycles_25y_chart.png   (wave+price chart)
"""
from __future__ import annotations
import math
from pathlib import Path
import pandas as pd
import numpy as np

# ─── Vedic 27-Nakshatra order (ecliptic start degrees 0°..360°) ──────────────
NAKSHATRA_ORDER = [
    "Ashwini",        #  0 —   0.00°
    "Bharani",        #  1 —  13.33°
    "Krittika",       #  2 —  26.67°
    "Rohini",         #  3 —  40.00°
    "Mrigashira",     #  4 —  53.33°
    "Ardra",          #  5 —  66.67°
    "Punarvasu",      #  6 —  80.00°
    "Pushya",         #  7 —  93.33°
    "Ashlesha",       #  8 — 106.67°
    "Magha",          #  9 — 120.00°
    "Purva Phalguni", # 10 — 133.33°
    "Uttara Phalguni",# 11 — 146.67°
    "Hasta",          # 12 — 160.00°
    "Chitra",         # 13 — 173.33°
    "Swati",          # 14 — 186.67°
    "Vishakha",       # 15 — 200.00°
    "Anuradha",       # 16 — 213.33°
    "Jyeshtha",       # 17 — 226.67°
    "Mula",           # 18 — 240.00°
    "Purva Ashadha",  # 19 — 253.33°
    "Uttara Ashadha", # 20 — 266.67°
    "Shravana",       # 21 — 280.00°
    "Dhanishta",      # 22 — 293.33°
    "Shatabhisha",    # 23 — 306.67°
    "Purva Bhadrapada",# 24 — 320.00°
    "Uttara Bhadrapada",# 25 — 333.33°
    "Revati",         # 26 — 346.67°
]
NAK_DEG_START = {n: i * (360.0 / 27) for i, n in enumerate(NAKSHATRA_ORDER)}
NAK_DEG_END   = {n: (i + 1) * (360.0 / 27) for i, n in enumerate(NAKSHATRA_ORDER)}

# Moon lunar phase sequence
MOON_PHASE_SEQ = {
    "New Moon":      0,
    "Solar Eclipse": 0,
    "First Quarter": 0.25,
    "Full Moon":     0.5,
    "Lunar Eclipse": 0.5,
    "Last Quarter":  0.75,
}

# Planet degree extraction helper
def _extract_degree(detail_str: str, planet: str = None) -> float | None:
    """Extract degree from detail string like 'Moon 220.1°, Sun 280.1°'"""
    import re
    if planet:
        m = re.search(rf"{planet}\s+([\d.]+)°", str(detail_str))
        if m:
            return float(m.group(1))
    # fallback: first number
    m = re.search(r"([\d.]+)°", str(detail_str))
    return float(m.group(1)) if m else None


def _extract_planet_from_event(event: str) -> str:
    planets = ["Sun", "Mercury", "Venus", "Mars", "Jupiter", "Saturn",
               "Uranus", "Neptune", "Pluto", "Moon", "Node"]
    for p in planets:
        if p in event:
            return p
    return "Unknown"


# ─── Load raw CSVs ─────────────────────────────────────────────────────────
def _load_all_raw(base: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    def _read(path):
        df = pd.read_csv(path)
        df.columns = [c.strip() for c in df.columns]
        df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
        return df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

    gm  = _read(base / "data" / "gann_moon_aspects_2000_2026.csv")
    gc  = _read(base / "data" / "gann_cycles_nodes_2000_2026.csv")
    nak = _read(base / "data" / "astro_nakshatra_events_2000_2026.csv")
    return gm, gc, nak


# ─── 1. MOON CYCLE ARCS ────────────────────────────────────────────────────
def _build_moon_cycles(gm: pd.DataFrame) -> pd.DataFrame:
    """Build complete New-Moon-to-New-Moon arcs (29.5d cycles) with sub-phases."""
    phases = gm[gm["category"] == "moon_phase"].copy()
    phases["phase_seq"] = phases["event"].map(MOON_PHASE_SEQ)
    phases["moon_deg"] = phases["detail"].apply(
        lambda d: _extract_degree(str(d), "Moon") or 0.0
    )
    phases = phases.sort_values("time").reset_index(drop=True)

    # Find New Moon rows as cycle start points
    new_moons = phases[phases["event"].isin(["New Moon", "Solar Eclipse"])].copy()

    rows = []
    for i, nm_row in new_moons.iterrows():
        # Find next New Moon
        next_nm = new_moons[new_moons["time"] > nm_row["time"]].head(1)
        end_time = next_nm.iloc[0]["time"] if len(next_nm) > 0 else nm_row["time"] + pd.Timedelta(days=29.53)

        cycle_start = nm_row["time"]
        cycle_num   = i + 1
        deg_start   = nm_row["moon_deg"] or 0.0

        # Sub-phase events within this cycle window
        sub = phases[(phases["time"] >= cycle_start) & (phases["time"] < end_time)].copy()

        for _, sp in sub.iterrows():
            deg = sp["moon_deg"] or deg_start
            rows.append({
                "cycle_id":       f"MOON_{cycle_num:04d}",
                "start_time":     cycle_start,
                "end_time":       end_time,
                "event_time":     sp["time"],
                "duration_days":  round((end_time - cycle_start).total_seconds() / 86400, 2),
                "cycle_type":     "moon",
                "sub_type":       sp["event"],
                "phase_sequence": sp["phase_seq"],
                "degree_at_event":deg,
                "nakshatra":      _deg_to_nakshatra(deg),
                "label":          f"Moon {sp['event']} (cycle {cycle_num})",
                "impact":         sp["impact"],
                "detail":         sp["detail"],
            })

    return pd.DataFrame(rows)


def _deg_to_nakshatra(deg) -> str:
    try:
        d = float(deg)
        if math.isnan(d):
            return "Unknown"
        idx = int((d % 360) / (360 / 27)) % 27
        return NAKSHATRA_ORDER[idx]
    except (TypeError, ValueError):
        return "Unknown"


# ─── 2. NAKSHATRA TRANSIT ARCS ─────────────────────────────────────────────
def _build_nakshatra_cycles(nak: pd.DataFrame) -> pd.DataFrame:
    """Build Moon-through-nakshatra transit arcs (~1 day each) in Vedic order."""
    nak_rows = nak[nak["category"] == "nakshatra"].copy()
    nak_rows["nakshatra_name"] = nak_rows["event"].str.extract(r"enters (.+)$")[0]
    nak_rows = nak_rows.dropna(subset=["nakshatra_name"]).sort_values("time").reset_index(drop=True)
    nak_rows["nak_order"] = nak_rows["nakshatra_name"].map(
        {n: i for i, n in enumerate(NAKSHATRA_ORDER)}
    )

    rows = []
    for i, row in nak_rows.iterrows():
        end_row = nak_rows[nak_rows["time"] > row["time"]].head(1)
        end_time = end_row.iloc[0]["time"] if len(end_row) > 0 else row["time"] + pd.Timedelta(days=1)

        nak_name = row["nakshatra_name"]
        nak_seq  = int(row["nak_order"]) if pd.notna(row["nak_order"]) else -1
        deg_start = NAK_DEG_START.get(nak_name, 0.0)
        deg_end   = NAK_DEG_END.get(nak_name, 13.33)

        rows.append({
            "cycle_id":        f"NAK_{i:05d}",
            "start_time":      row["time"],
            "end_time":        end_time,
            "event_time":      row["time"],
            "duration_days":   round((end_time - row["time"]).total_seconds() / 86400, 2),
            "cycle_type":      "nakshatra",
            "sub_type":        nak_name,
            "phase_sequence":  nak_seq / 27.0,
            "degree_at_event": deg_start,
            "degree_end":      deg_end,
            "nakshatra":       nak_name,
            "nak_sequence":    nak_seq,
            "label":           f"Nak {nak_seq+1}/27: {nak_name} ({deg_start:.1f}°–{deg_end:.1f}°)",
            "impact":          row["impact"],
            "detail":          row["detail"],
        })

    return pd.DataFrame(rows)


# ─── 3. PLANETARY INGRESS ARCS ─────────────────────────────────────────────
def _build_planetary_cycles(nak: pd.DataFrame, gm: pd.DataFrame) -> pd.DataFrame:
    """Build planet-through-sign arcs with degree + next ingress end boundary."""
    # Combine all "ingress" records
    ingress_nak = nak[nak["category"] == "astrology"].copy()
    ingress_gm  = gm[gm["event"].str.contains("ingress", case=False, na=False)].copy()
    all_ing = pd.concat([ingress_nak, ingress_gm], ignore_index=True)
    all_ing = all_ing.sort_values("time").reset_index(drop=True)

    # Also add retrograde stations
    stations = gm[gm["category"] == "moon_aspect"].copy()
    stations = stations[stations["event"].str.contains("Station|Retrograde|Direct", case=False, na=False)].copy()

    combined = pd.concat([all_ing, stations], ignore_index=True).sort_values("time").reset_index(drop=True)

    rows = []
    for i, row in combined.iterrows():
        event_str = str(row["event"])
        planet    = _extract_planet_from_event(event_str)
        if planet in ("Moon",):
            continue  # Moon ingress handled in moon_cycles
        deg = _extract_degree(str(row.get("detail", "")), planet) or 0.0

        # Next event for same planet
        same_planet = combined[
            (combined["time"] > row["time"]) &
            (combined["event"].str.contains(planet, na=False))
        ].head(1)
        end_time = same_planet.iloc[0]["time"] if len(same_planet) > 0 else row["time"] + pd.Timedelta(days=30)

        rows.append({
            "cycle_id":        f"PLN_{i:05d}",
            "start_time":      row["time"],
            "end_time":        end_time,
            "event_time":      row["time"],
            "duration_days":   round((end_time - row["time"]).total_seconds() / 86400, 2),
            "cycle_type":      "planetary",
            "sub_type":        event_str,
            "planet":          planet,
            "phase_sequence":  (deg % 360) / 360.0,
            "degree_at_event": deg,
            "nakshatra":       _deg_to_nakshatra(deg),
            "label":           f"{planet}: {event_str[:60]}",
            "impact":          row["impact"],
            "detail":          row.get("detail", ""),
        })

    return pd.DataFrame(rows)


# ─── 4. GANN NODE / PRESSURE CYCLES ─────────────────────────────────────────
def _build_gann_cycles(gc: pd.DataFrame, gm: pd.DataFrame) -> pd.DataFrame:
    """Build Gann nodes, Square-of-9 arcs, pressure points with degree."""
    important = gc[gc["category"].isin(["pressure_point", "planetary_station", "synodic_cycle"])].copy()
    sq9       = gc[gc["category"] == "time_cycle"].copy()
    gann_harm = gm[gm["category"] == "gann"].copy()

    all_gann = pd.concat([important, sq9, gann_harm], ignore_index=True).sort_values("time").reset_index(drop=True)

    # Gann geometric degree intervals
    GANN_KEY_ANGLES = [0, 45, 90, 135, 180, 225, 270, 315, 360]

    rows = []
    for i, row in all_gann.iterrows():
        deg = _extract_degree(str(row.get("detail", ""))) or 0.0

        # Nearest Gann key angle
        nearest_angle = min(GANN_KEY_ANGLES, key=lambda a: min(abs(deg - a), abs(deg - a - 360)))
        proximity     = min(abs(deg - nearest_angle), abs(deg - nearest_angle - 360))
        gann_quality  = "EXACT" if proximity < 3 else ("NEAR" if proximity < 10 else "WEAK")

        next_ev = all_gann[all_gann["time"] > row["time"]].head(1)
        end_time = next_ev.iloc[0]["time"] if len(next_ev) > 0 else row["time"] + pd.Timedelta(days=7)

        # Geometric cycle labeling (90/180/360 days)
        cat = row["category"]
        if cat == "pressure_point":
            sub = "Pressure Point"
        elif cat == "planetary_station":
            sub = "Planetary Station"
        elif cat == "synodic_cycle":
            sub = "Synodic Cycle"
        else:
            sub = "Time Cycle"

        rows.append({
            "cycle_id":        f"GNN_{i:05d}",
            "start_time":      row["time"],
            "end_time":        end_time,
            "event_time":      row["time"],
            "duration_days":   round((end_time - row["time"]).total_seconds() / 86400, 2),
            "cycle_type":      "gann",
            "sub_type":        sub,
            "phase_sequence":  (deg % 360) / 360.0,
            "degree_at_event": deg,
            "gann_key_angle":  nearest_angle,
            "gann_quality":    gann_quality,
            "nakshatra":       _deg_to_nakshatra(deg),
            "label":           f"Gann {sub}: {row['event'][:60]} @ {deg:.1f}° ({gann_quality})",
            "impact":          row["impact"],
            "detail":          row.get("detail", ""),
        })

    return pd.DataFrame(rows)


# ─── 5. COMBINE & ORDER ────────────────────────────────────────────────────
def build_master_cycles(base: Path) -> pd.DataFrame:
    gm, gc, nak = _load_all_raw(base)

    print("[1/4] Building Moon cycles...")
    moon_df   = _build_moon_cycles(gm)
    print(f"      → {len(moon_df)} moon phase arc records")

    print("[2/4] Building Nakshatra transit arcs...")
    nak_df    = _build_nakshatra_cycles(nak)
    print(f"      → {len(nak_df)} nakshatra transit records")

    print("[3/4] Building Planetary ingress arcs...")
    pln_df    = _build_planetary_cycles(nak, gm)
    print(f"      → {len(pln_df)} planetary arc records")

    print("[4/4] Building Gann node/pressure arcs...")
    gann_df   = _build_gann_cycles(gc, gm)
    print(f"      → {len(gann_df)} gann cycle records")

    # Merge into single ordered ledger
    all_dfs = []
    for df in [moon_df, nak_df, pln_df, gann_df]:
        if len(df) > 0:
            all_dfs.append(df)
    master = pd.concat(all_dfs, ignore_index=True)
    master = master.sort_values("event_time").reset_index(drop=True)

    # Unified key columns present in all rows
    for col in ["degree_end", "nak_sequence", "gann_key_angle", "gann_quality", "planet"]:
        if col not in master.columns:
            master[col] = np.nan

    master["degree_at_event"] = master["degree_at_event"].fillna(0.0)
    master["phase_sequence"]  = master["phase_sequence"].fillna(0.0)

    # Strip timezone for CSV
    for tc in ["start_time", "end_time", "event_time"]:
        master[tc] = pd.to_datetime(master[tc], utc=True).dt.tz_localize(None)

    # Add sequential row index
    master.insert(0, "row_num", range(1, len(master) + 1))

    return master[["row_num", "event_time", "start_time", "end_time", "duration_days",
                   "cycle_type", "sub_type", "planet", "degree_at_event", "degree_end",
                   "gann_key_angle", "gann_quality", "nakshatra", "nak_sequence",
                   "phase_sequence", "label", "impact", "detail"]]


def main():
    base = Path(__file__).resolve().parents[1]
    out_dir = base / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    master = build_master_cycles(base)

    out_csv = out_dir / "master_cycles_25y.csv"
    master.to_csv(out_csv, index=False)

    print(f"\n[✅] master_cycles_25y.csv: {len(master):,} rows")
    print(f"     Date range: {master['event_time'].min()} → {master['event_time'].max()}")
    print(f"\n  Cycle type breakdown:")
    for ct, cnt in master["cycle_type"].value_counts().items():
        print(f"    {ct:<15} {cnt:>6,} records")
    print(f"\n  Top 3 nakshatra in cycles:")
    print(master["nakshatra"].value_counts().head(3).to_string())
    print(f"\n  Degree range: {master['degree_at_event'].min():.1f}° → {master['degree_at_event'].max():.1f}°")
    print(f"\n  Saved → {out_csv}")


if __name__ == "__main__":
    main()
