"""
Cycle Wave Chart Generator
==========================
Creates a 3-panel chart showing:
  Panel 1 (main): XAU/USD daily price + cycle START/END markers on the bars
  Panel 2:        Moon cycle wave (phase 0→1 per 29.5d cycle, repeating)
  Panel 3:        Nakshatra wave (position 0→26 through the 27 nakshatras)
  Panel 4:        Gann degree wave (0°→360° from all gann pressure events)

Cycle start = green triangle  Cycle end = red triangle
Planetary hits = orange diamond

Usage:
    python scripts/generate_cycle_chart.py
    python scripts/generate_cycle_chart.py --start 2020-01-01 --end 2026-04-10
"""
from __future__ import annotations
import argparse
from pathlib import Path
import warnings
import sys

import matplotlib
matplotlib.use("Agg")                           # headless PNG
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parents[1]

# Add generate_master_cycles NAKSHATRA_ORDER for shared use
NAKSHATRA_ORDER = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira",
    "Ardra", "Punarvasu", "Pushya", "Ashlesha", "Magha",
    "Purva Phalguni", "Uttara Phalguni", "Hasta", "Chitra", "Swati",
    "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha",
    "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]


# ─── Load data ───────────────────────────────────────────────────────────────
def _load_price(start: str, end: str) -> pd.DataFrame:
    px = pd.read_csv(BASE / "data" / "XAU_1d_data.csv", sep=";")
    px.columns = [c.strip() for c in px.columns]
    px["date"] = pd.to_datetime(px["Date"], format="%Y.%m.%d %H:%M", errors="coerce")
    px["close"] = pd.to_numeric(px["Close"], errors="coerce")
    px["open"]  = pd.to_numeric(px["Open"], errors="coerce")
    px["high"]  = pd.to_numeric(px["High"], errors="coerce")
    px["low"]   = pd.to_numeric(px["Low"], errors="coerce")
    px = px.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    # remove anomalies
    px = px[(px["close"] >= 200) & (px["close"] <= 5000)].copy()
    px = px[(px["date"] >= pd.Timestamp(start)) & (px["date"] <= pd.Timestamp(end))].copy()
    return px.reset_index(drop=True)


def _load_cycles(start: str, end: str) -> pd.DataFrame:
    cyc = pd.read_csv(BASE / "data" / "reports" / "master_cycles_25y.csv")
    cyc["event_time"] = pd.to_datetime(cyc["event_time"], errors="coerce")
    cyc["start_time"] = pd.to_datetime(cyc["start_time"], errors="coerce")
    cyc["end_time"]   = pd.to_datetime(cyc["end_time"],   errors="coerce")
    cyc = cyc[(cyc["event_time"] >= pd.Timestamp(start)) & (cyc["event_time"] <= pd.Timestamp(end))].copy()
    return cyc.reset_index(drop=True)


# ─── Build continuous wave series aligned to price dates ─────────────────────
def _moon_wave(px_dates: pd.Series, moon_cycles: pd.DataFrame) -> np.ndarray:
    """Continuous moon phase wave: 0 (New) → 0.5 (Full) → 1 (next New)."""
    REF_NEW_MOON = pd.Timestamp("2000-01-06")
    CYCLE_DAYS   = 29.53059
    wave = np.zeros(len(px_dates))
    for i, d in enumerate(px_dates):
        days = (d - REF_NEW_MOON).days
        wave[i] = (days % CYCLE_DAYS) / CYCLE_DAYS
    return wave


def _nakshatra_wave(px_dates: pd.Series, nak_cycles: pd.DataFrame) -> np.ndarray:
    """Continuous nakshatra sequence wave: 0→26 as Moon moves through nakshatras."""
    nak_by_date = nak_cycles.sort_values("event_time").copy()
    nak_by_date["date"] = nak_by_date["event_time"].dt.normalize()
    
    # Map date → nakshatra sequence number
    last_seq = 0
    date_to_seq: dict = {}
    for _, row in nak_by_date.iterrows():
        if pd.notna(row.get("nak_sequence")):
            last_seq = int(row["nak_sequence"])
        date_to_seq[row["date"].date()] = last_seq

    wave = np.zeros(len(px_dates))
    current_seq = 0
    for i, d in enumerate(px_dates):
        key = d.date() if hasattr(d, "date") else d
        if key in date_to_seq:
            current_seq = date_to_seq[key]
        wave[i] = current_seq
    return wave


def _gann_degree_wave(px_dates: pd.Series, gann_cycles: pd.DataFrame) -> np.ndarray:
    """Gann geometric degree wave: interpolated degree at each price date."""
    gann = gann_cycles.sort_values("event_time").copy()
    gann["date"] = gann["event_time"].dt.normalize()
    gann["deg"]  = pd.to_numeric(gann["degree_at_event"], errors="coerce").fillna(0)

    # Forward-fill degree to every price date
    deg_map: dict = {}
    last_deg = 0.0
    for _, row in gann.iterrows():
        key = row["date"].date()
        last_deg = row["deg"]
        deg_map[key] = last_deg

    wave = np.zeros(len(px_dates))
    current_deg = 0.0
    for i, d in enumerate(px_dates):
        key = d.date() if hasattr(d, "date") else d
        if key in deg_map:
            current_deg = deg_map[key]
        wave[i] = current_deg
    return wave


# ─── Mark cycle start + end points on price chart ────────────────────────────
def _build_marker_series(px: pd.DataFrame, cycles: pd.DataFrame):
    """For each cycle START and END, find the closest price date."""
    px_dates = set(px["date"].dt.normalize())

    moon_starts  = []
    moon_ends    = []
    nak_starts   = []
    planet_hits  = []
    gann_hits    = []

    # Moon cycle starts / ends
    moon = cycles[cycles["cycle_type"] == "moon"].copy()
    for t in moon[moon["sub_type"].isin(["New Moon", "Solar Eclipse"])]["event_time"]:
        dt = pd.Timestamp(t).normalize()
        row = px[px["date"].dt.normalize() == dt]
        if len(row) > 0:
            moon_starts.append((dt, row.iloc[0]["high"]))

    for t in moon[moon["sub_type"].isin(["Full Moon", "Lunar Eclipse"])]["event_time"]:
        dt = pd.Timestamp(t).normalize()
        row = px[px["date"].dt.normalize() == dt]
        if len(row) > 0:
            moon_ends.append((dt, row.iloc[0]["high"]))

    # Nakshatra transitions (every ~13d = new cycle start)
    nak = cycles[cycles["cycle_type"] == "nakshatra"].copy()
    for t in nak["event_time"][::3]:          # every 3rd nak transition to avoid clutter
        dt = pd.Timestamp(t).normalize()
        row = px[px["date"].dt.normalize() == dt]
        if len(row) > 0:
            nak_starts.append((dt, row.iloc[0]["low"]))

    # Planetary ingress / station hits
    pln = cycles[cycles["cycle_type"] == "planetary"].copy()
    for _, pr in pln[pln["impact"].isin(["high", "medium"])].iterrows():
        dt = pd.Timestamp(pr["event_time"]).normalize()
        row = px[px["date"].dt.normalize() == dt]
        if len(row) > 0:
            planet_hits.append((dt, row.iloc[0]["high"] * 1.005))

    # Gann pressure / node hits
    gnn = cycles[cycles["cycle_type"] == "gann"].copy()
    for _, gr in gnn[gnn["sub_type"].isin(["Pressure Point", "Planetary Station", "Synodic Cycle"])].iterrows():
        dt = pd.Timestamp(gr["event_time"]).normalize()
        row = px[px["date"].dt.normalize() == dt]
        if len(row) > 0:
            gann_hits.append((dt, row.iloc[0]["low"] * 0.994))

    return moon_starts, moon_ends, nak_starts, planet_hits, gann_hits


# ─── Main chart builder ───────────────────────────────────────────────────────
def generate_chart(start: str, end: str, out_path: Path, title_suffix: str = "") -> None:
    print(f"[chart] Loading price data {start} → {end}...")
    px = _load_price(start, end)
    if len(px) == 0:
        print("[chart] No price data in range.")
        return

    print(f"[chart] Loading cycle data {start} → {end}...")
    cycles = _load_cycles(start, end)

    print(f"[chart] Building wave series from {len(px)} price bars and {len(cycles)} cycle records...")

    moon_wave   = _moon_wave(px["date"], cycles[cycles["cycle_type"] == "moon"])
    nak_wave    = _nakshatra_wave(px["date"], cycles[cycles["cycle_type"] == "nakshatra"])
    gann_wave   = _gann_degree_wave(px["date"], cycles[cycles["cycle_type"] == "gann"])

    moon_starts, moon_ends, nak_starts, planet_hits, gann_hits = _build_marker_series(px, cycles)

    # ─── Figure layout ──────────────────────────────────────────────────────
    fig = plt.figure(figsize=(28, 22), facecolor="#0a0a14")
    gs  = gridspec.GridSpec(4, 1, hspace=0.06,
                            height_ratios=[4, 1.3, 1.3, 1.3])

    axes = [fig.add_subplot(gs[i]) for i in range(4)]
    for ax in axes:
        ax.set_facecolor("#0d0d1e")
        ax.tick_params(colors="#aaaacc", labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#2a2a4a")

    dates = px["date"].values
    close = px["close"].values
    high  = px["high"].values
    low   = px["low"].values

    # ─── Panel 1: Price + Cycle Markers ─────────────────────────────────────
    ax0 = axes[0]
    ax0.plot(dates, close, color="#4db8ff", linewidth=0.9, label="XAU/USD Close", zorder=3)
    ax0.fill_between(dates, close, close.min() * 0.98,
                     alpha=0.08, color="#4db8ff")

    # Moon start (green triangle up)
    if moon_starts:
        ms_x, ms_y = zip(*moon_starts)
        ax0.scatter(ms_x, ms_y, marker="^", s=55, color="#00ff88",
                    zorder=5, label=f"New Moon / Cycle Start ({len(moon_starts)})")

    # Moon end / Full Moon (red triangle down)
    if moon_ends:
        me_x, me_y = zip(*moon_ends)
        ax0.scatter(me_x, me_y, marker="v", s=55, color="#ff4466",
                    zorder=5, label=f"Full Moon / Cycle Midpoint ({len(moon_ends)})")

    # Nakshatra transitions (small cyan diamond)
    if nak_starts:
        ns_x, ns_y = zip(*nak_starts)
        ax0.scatter(ns_x, ns_y, marker="D", s=22, color="#00ccff",
                    zorder=4, alpha=0.7, label=f"Nakshatra Entry (every 3rd, {len(nak_starts)})")

    # Planetary hits (orange X)
    if planet_hits:
        ph_x, ph_y = zip(*planet_hits)
        ax0.scatter(ph_x, ph_y, marker="x", s=55, linewidths=1.5,
                    color="#ffaa00", zorder=6, label=f"Planetary Hit ({len(planet_hits)})")

    # Gann pressure points (yellow star)
    if gann_hits:
        gh_x, gh_y = zip(*gann_hits)
        ax0.scatter(gh_x, gh_y, marker="*", s=120, color="#ffff44",
                    zorder=7, alpha=0.85, label=f"Gann Pressure Point ({len(gann_hits)})")

    # Price annotations: recent high/low
    idx_high = np.argmax(close)
    idx_low  = np.argmin(close)
    ax0.annotate(f"  ${close[idx_high]:,.0f}", xy=(dates[idx_high], close[idx_high]),
                 color="#88ffaa", fontsize=8, va="bottom")
    ax0.annotate(f"  ${close[idx_low]:,.0f}", xy=(dates[idx_low], close[idx_low]),
                 color="#ff8888", fontsize=8, va="top")

    ax0.set_ylabel("Price (USD)", color="#aaaacc", fontsize=9)
    ax0.legend(loc="upper left", fontsize=8, facecolor="#1a1a2e",
               labelcolor="#ccccdd", edgecolor="#444466", ncol=3)
    ax0.set_title(
        f"XAU/USD — 25-Year Cycle Wave Chart{title_suffix}\n"
        f"Moon ▲▼  ·  Nakshatra ◆  ·  Planetary ✕  ·  Gann ★",
        color="#ddddff", fontsize=13, pad=10,
    )

    # ─── Panel 2: Moon Phase Wave ────────────────────────────────────────────
    ax1 = axes[1]
    ax1.fill_between(dates, moon_wave, 0, color="#5588ff", alpha=0.4)
    ax1.plot(dates, moon_wave, color="#99aaff", linewidth=0.9)
    ax1.axhline(0.5, color="#ff4466", linewidth=0.6, linestyle="--", alpha=0.7, label="Full Moon")
    ax1.axhline(0.0, color="#00ff88", linewidth=0.6, linestyle="--", alpha=0.7, label="New Moon")
    ax1.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax1.set_yticklabels(["New", "1Q", "Full", "3Q", "New"], fontsize=7, color="#aaaacc")
    ax1.set_ylabel("Moon Phase", color="#aaaacc", fontsize=8)
    ax1.legend(loc="upper left", fontsize=7, facecolor="#1a1a2e",
               labelcolor="#ccccdd", edgecolor="#444466")

    # ─── Panel 3: Nakshatra Wave ─────────────────────────────────────────────
    ax2 = axes[2]
    ax2.fill_between(dates, nak_wave, 0, color="#00ccff", alpha=0.3)
    ax2.plot(dates, nak_wave, color="#66ddff", linewidth=0.8)

    # Mark major nakshatra transitions
    MAJOR_NAK = [0, 6, 9, 13, 18, 23]          # Ashwini, Punarvasu, Magha, Chitra, Mula, Shatabhisha
    for seq_num in MAJOR_NAK:
        ax2.axhline(seq_num, color="#7788aa", linewidth=0.4, linestyle=":", alpha=0.5)
        ax2.text(dates[0], seq_num + 0.3,
                 f" {NAKSHATRA_ORDER[seq_num] if seq_num < 27 else ''}", fontsize=6, color="#7788aa")

    ax2.set_yticks(range(0, 27, 3))
    ax2.set_yticklabels([NAKSHATRA_ORDER[i] for i in range(0, 27, 3)],
                        fontsize=6.5, color="#aaaacc")
    ax2.set_ylabel("Nakshatra", color="#aaaacc", fontsize=8)

    # ─── Panel 4: Gann Degree Wave ────────────────────────────────────────────
    ax3 = axes[3]
    ax3.fill_between(dates, gann_wave, 0, color="#ffcc00", alpha=0.25)
    ax3.plot(dates, gann_wave, color="#ffdd44", linewidth=0.8)

    # Gann key degree lines
    for deg in [90, 180, 270, 360]:
        ax3.axhline(deg, color="#ff8844", linewidth=0.5, linestyle="--", alpha=0.6)
        ax3.text(dates[-1], deg + 3, f" {deg}°", fontsize=7, color="#ff8844")

    ax3.set_yticks([0, 90, 180, 270, 360])
    ax3.set_yticklabels(["0°", "90°", "180°", "270°", "360°"], fontsize=7, color="#aaaacc")
    ax3.set_ylabel("Gann Degree", color="#aaaacc", fontsize=8)
    ax3.set_xlabel("Date", color="#aaaacc", fontsize=9)

    # ─── X-axis formatting ───────────────────────────────────────────────────
    for ax in axes:
        years_span = (px["date"].iloc[-1] - px["date"].iloc[0]).days / 365.25
        if years_span > 10:
            ax.xaxis.set_major_locator(mdates.YearLocator(2))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        elif years_span > 3:
            ax.xaxis.set_major_locator(mdates.YearLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        else:
            ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%b"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

    # Hide x-tick labels on upper 3 panels for cleanliness
    for ax in axes[:3]:
        plt.setp(ax.get_xticklabels(), visible=False)

    print(f"[chart] Saving to {out_path}...")
    plt.savefig(out_path, dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[✅] Chart saved: {out_path}  ({out_path.stat().st_size // 1024} KB)")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2000-01-01")
    p.add_argument("--end",   default="2026-04-12")
    p.add_argument("--out",   default=None)
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    out = Path(args.out) if args.out else BASE / "data" / "reports" / "master_cycles_chart_25y.png"
    generate_chart(args.start, args.end, out)
