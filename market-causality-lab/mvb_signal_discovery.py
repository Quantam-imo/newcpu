"""
mvb_signal_discovery.py
=======================
Discover and validate a new 5-minute-grade signal from first principles.

Approach:
  - ECS looks for LOW velocity + coiled energy → swing breakout ahead (8-20h horizon)
  - We need the OPPOSITE: catch momentum that has ALREADY started → 5-15m continuation

Signal candidate: MVB — Momentum Velocity Burst
-----------------------------------------------
Logic:
  - High velocity (market is already moving hard)
  - Strong trend alignment (structural direction is clear)
  - Clean BOS (structural break just confirmed)
  - Low conflict (no opposing pressure)
  - Force > threshold (move is sustained, not a spike)

This is a BURST CONTINUATION signal: enter during the thrust, exit quickly.
Horizon: 1-4 bars (15m-1h in our 15m proxy data)

We also test a second candidate: SVA — Structure-Velocity Alignment
  - Moderate velocity (not extreme — avoids overextended entries)
  - BOS in trend direction
  - high trend_strength
  - hh_hl alignment (bullish structure) OR ll_lh (bearish)

Steps:
  1. Scan all 649k bars using scanner (sample)
  2. Collect MVB events from scanner records
  3. Forward return distributions at 1b(15m), 2b(30m), 4b(1h), 8b(2h)
  4. Compare vs random baseline
  5. Regime split
  6. Print honest results
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from backend.memory.scanner import scan_market

# ──────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────
DATA_PATH   = "data/XAU_15m_data.csv"
WINDOW      = 600       # bars per scan window
MAX_WINDOWS = 30        # ~18,000 bars scanned — fast enough
STEP        = 600       # non-overlapping windows

# Forward horizons (in 15m bars)
HORIZONS = {
    "1b_15m":  1,
    "2b_30m":  2,
    "4b_1h":   4,
    "8b_2h":   8,
    "16b_4h":  16,
    "32b_8h":  32,
}

# ──────────────────────────────────────────────────────────────
# Load data
# ──────────────────────────────────────────────────────────────
print("Loading data…")
df = pd.read_csv(DATA_PATH, sep=";")
df.columns = [c.lower() for c in df.columns]
df["date"] = pd.to_datetime(df["date"], errors="coerce")
df = df.dropna(subset=["close", "date"]).reset_index(drop=True)
print(f"  {len(df):,} bars  {df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}")

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def _f(d, key, default=0.0):
    try:
        return float(d.get(key, default) or default)
    except:
        return default

def _b(d, key):
    return bool(d.get(key, False))

def is_mvb(rec: dict) -> tuple[bool, str]:
    """
    MVB — Momentum Velocity Burst
    Catches momentum continuation on a confirmed structural break.
    Returns (active, direction)
    """
    phys = rec.get("physics") or {}
    rel  = rec.get("reliability") or {}
    comp = rec.get("compression") or {}
    stru = rec.get("structure") or {}

    velocity  = abs(_f(phys, "velocity"))
    force     = abs(_f(phys, "force"))
    conflict  = _f(rel,  "conflict_score")
    tstr      = _f(stru, "trend_strength")
    bos_up    = _b(stru, "bos_up")
    bos_dn    = _b(stru, "bos_down")
    hh_hl     = _b(stru, "hh_hl")
    ll_lh     = _b(stru, "ll_lh")

    # MVB conditions
    c1 = velocity > 2.5        # elevated velocity (market moving hard)
    c2 = force > 1.5           # sustained force (not a spike)
    c3 = tstr > 8.0            # strong trend alignment
    c4 = conflict < 0.25       # low opposition
    c5 = (bos_up or bos_dn)    # structural break confirmed

    active = c1 and c2 and c3 and c4 and c5

    if not active:
        return False, "NEUTRAL"

    # Direction from BOS
    if bos_up and not bos_dn:
        direction = "BUY"
    elif bos_dn and not bos_up:
        direction = "SELL"
    elif hh_hl:
        direction = "BUY"
    elif ll_lh:
        direction = "SELL"
    else:
        return False, "NEUTRAL"  # conflicting BOS — skip

    return True, direction


def is_sva(rec: dict) -> tuple[bool, str]:
    """
    SVA — Structure-Velocity Alignment (alternative candidate)
    Moderate velocity in trend direction after structural alignment.
    Designed to avoid overextended entries.
    """
    phys = rec.get("physics") or {}
    rel  = rec.get("reliability") or {}
    stru = rec.get("structure") or {}

    velocity = abs(_f(phys, "velocity"))
    force    = abs(_f(phys, "force"))
    conflict = _f(rel,  "conflict_score")
    tstr     = _f(stru, "trend_strength")
    bos_up   = _b(stru, "bos_up")
    bos_dn   = _b(stru, "bos_down")
    hh_hl    = _b(stru, "hh_hl")
    ll_lh    = _b(stru, "ll_lh")

    # SVA: moderate velocity (not overextended), clear structure
    c1 = 1.5 < velocity < 4.0   # moderate velocity window
    c2 = force > 1.0
    c3 = tstr > 12.0            # very strong trend alignment
    c4 = conflict < 0.15        # very low conflict
    c5 = (hh_hl or ll_lh)       # swing structure confirmed

    active = c1 and c2 and c3 and c4 and c5

    if not active:
        return False, "NEUTRAL"

    direction = "BUY" if hh_hl else "SELL"
    return True, direction


# ──────────────────────────────────────────────────────────────
# Scan for events
# ──────────────────────────────────────────────────────────────
def collect_events(df_full, signal_fn, name, max_windows=MAX_WINDOWS, start_offset=0):
    """Scan windows and collect events where signal fires."""
    events = []
    total_bars = len(df_full)
    windows_done = 0

    for start in range(start_offset, total_bars - WINDOW, STEP):
        if windows_done >= max_windows:
            break

        chunk = df_full.iloc[start : start + WINDOW]
        rows  = chunk[["date", "open", "high", "low", "close", "volume"]].copy()
        rows.columns = ["date", "open", "high", "low", "close", "volume"]

        try:
            records = scan_market(rows.to_dict("records"))
        except Exception as e:
            windows_done += 1
            continue

        for r in records:
            active, direction = signal_fn(r)
            if active:
                # Find bar index in df_full
                bar_date = None
                for col in ["timestamp", "date", "time"]:
                    if col in r:
                        bar_date = r[col]
                        break
                # Get closing price for this event
                close_val = r.get("close") or r.get("physics", {}).get("close")
                events.append({
                    "direction": direction,
                    "close":     close_val,
                    "global_idx": start + len(events),  # approximate
                    "date_approx": chunk["date"].iloc[0],
                })

        windows_done += 1
        if windows_done % 5 == 0:
            print(f"  [{name}] {windows_done}/{max_windows} windows, {len(events)} events so far…")

    return events


# ──────────────────────────────────────────────────────────────
# Better: use close prices from df directly with scanner records
# ──────────────────────────────────────────────────────────────
def collect_events_v2(df_full, signal_fn, name, max_windows=MAX_WINDOWS, start_year=None, end_year=None):
    """Scan windows and record global bar index for forward return calc."""
    events = []
    total_bars = len(df_full)
    windows_done = 0

    # Filter by year range
    if start_year:
        start_offset = df_full[df_full["date"].dt.year >= start_year].index[0]
    else:
        start_offset = 0

    if end_year:
        end_mask = df_full["date"].dt.year <= end_year
        if end_mask.any():
            end_offset = df_full[end_mask].index[-1]
        else:
            end_offset = total_bars
    else:
        end_offset = total_bars

    for win_start in range(start_offset, end_offset - WINDOW, STEP):
        if windows_done >= max_windows:
            break

        chunk   = df_full.iloc[win_start : win_start + WINDOW].reset_index(drop=True)
        rows    = chunk[["date", "open", "high", "low", "close", "volume"]].to_dict("records")

        try:
            records = scan_market(rows)
        except Exception:
            windows_done += 1
            continue

        # Map scanner records back to chunk positions by order
        for i, r in enumerate(records):
            active, direction = signal_fn(r)
            if not active:
                continue

            # Global index of this record in df_full
            global_idx = win_start + i
            if global_idx >= len(df_full) - max(HORIZONS.values()):
                continue

            events.append({
                "direction":  direction,
                "global_idx": global_idx,
                "date":       df_full.iloc[global_idx]["date"],
                "close":      df_full.iloc[global_idx]["close"],
            })

        windows_done += 1
        if windows_done % 5 == 0:
            print(f"  [{name}] {windows_done}/{max_windows} windows done, {len(events)} events…")

    return events


def forward_returns(events, df_full):
    """Compute forward returns for each horizon."""
    results = {h: [] for h in HORIZONS}

    for ev in events:
        idx   = ev["global_idx"]
        close = df_full.iloc[idx]["close"]
        d     = ev["direction"]

        for h_name, h_bars in HORIZONS.items():
            fwd_idx = idx + h_bars
            if fwd_idx >= len(df_full):
                continue
            fwd_close = df_full.iloc[fwd_idx]["close"]
            pct = (fwd_close - close) / close * 100
            if d == "SELL":
                pct = -pct
            results[h_name].append(pct)

    return results


def random_baseline(df_full, n_samples=1000, seed=42):
    """Random entry baseline for comparison."""
    rng = np.random.default_rng(seed)
    idxs = rng.integers(0, len(df_full) - max(HORIZONS.values()), n_samples)
    results = {h: [] for h in HORIZONS}
    for idx in idxs:
        close = df_full.iloc[idx]["close"]
        d = "BUY" if rng.random() > 0.5 else "SELL"
        for h_name, h_bars in HORIZONS.items():
            fwd_close = df_full.iloc[idx + h_bars]["close"]
            pct = (fwd_close - close) / close * 100
            if d == "SELL":
                pct = -pct
            results[h_name].append(pct)
    return results


def print_results(name, events, df_full, baseline):
    n = len(events)
    print(f"\n{'='*60}")
    print(f" {name}: {n} events")
    print(f"{'='*60}")
    if n == 0:
        print("  No events fired — thresholds too tight or field not populated.")
        return

    rets = forward_returns(events, df_full)

    print(f"  {'Horizon':<12} {'Signal Win%':>12} {'Baseline Win%':>14} {'Edge':>8} {'Mean Ret':>10} {'n':>5}")
    print(f"  {'-'*65}")
    for h in HORIZONS:
        arr  = np.array(rets[h])
        barr = np.array(baseline[h])
        if len(arr) == 0:
            continue
        wr  = (arr > 0).mean() * 100
        bwr = (barr > 0).mean() * 100
        edge = wr - bwr
        mean = arr.mean()
        print(f"  {h:<12} {wr:>11.1f}% {bwr:>13.1f}% {edge:>+7.1f}% {mean:>+9.3f}% {len(arr):>5}")

    # Best horizon
    best_h = max(HORIZONS.keys(), key=lambda h: (np.array(rets[h]) > 0).mean() if rets[h] else 0)
    best_arr = np.array(rets[best_h])
    print(f"\n  Best horizon: {best_h}  win={100*(best_arr>0).mean():.1f}%  mean={best_arr.mean():+.3f}%")

    # Direction distribution
    buys  = sum(1 for e in events if e["direction"] == "BUY")
    sells = sum(1 for e in events if e["direction"] == "SELL")
    print(f"  Directions: BUY={buys}  SELL={sells}  ratio={buys/max(sells,1):.1f}:1")

    # Fire rate
    total_scanned = MAX_WINDOWS * WINDOW
    print(f"  Fire rate: {n/total_scanned*100:.2f}% of bars scanned")


# ──────────────────────────────────────────────────────────────
# Run everything
# ──────────────────────────────────────────────────────────────
print("\n" + "="*60)
print(" STEP 1: Collect MVB events (2022-2026, 30 windows)")
print("="*60)
mvb_events = collect_events_v2(df, is_mvb, "MVB", max_windows=MAX_WINDOWS, start_year=2022)
print(f"  Total MVB events: {len(mvb_events)}")

print("\n" + "="*60)
print(" STEP 2: Collect SVA events (2022-2026, 30 windows)")
print("="*60)
sva_events = collect_events_v2(df, is_sva, "SVA", max_windows=MAX_WINDOWS, start_year=2022)
print(f"  Total SVA events: {len(sva_events)}")

print("\n" + "="*60)
print(" STEP 3: Random baseline")
print("="*60)
baseline = random_baseline(df, n_samples=2000)

# ──────────────────────────────────────────────────────────────
# Results
# ──────────────────────────────────────────────────────────────
print_results("MVB — Momentum Velocity Burst", mvb_events, df, baseline)
print_results("SVA — Structure-Velocity Alignment", sva_events, df, baseline)

# ──────────────────────────────────────────────────────────────
# Regime split for winner
# ──────────────────────────────────────────────────────────────
print("\n" + "="*60)
print(" STEP 4: Regime split — MVB (2012-2026)")
print("="*60)
regimes = [
    ("2012-2018", 2012, 2018),
    ("2019-2021", 2019, 2021),
    ("2022-2026", 2022, 2026),
]
for rname, ry, ey in regimes:
    r_events = collect_events_v2(df, is_mvb, f"MVB-{rname}", max_windows=10, start_year=ry, end_year=ey)
    if not r_events:
        print(f"  {rname}: 0 events")
        continue
    r_rets = forward_returns(r_events, df)
    arr = np.array(r_rets["4b_1h"])
    arr8 = np.array(r_rets["8b_2h"])
    wr  = (arr > 0).mean() * 100 if len(arr) else 0
    wr8 = (arr8 > 0).mean() * 100 if len(arr8) else 0
    print(f"  {rname}: n={len(r_events)} | 1h win={wr:.1f}% | 2h win={wr8:.1f}%")

print("\n" + "="*60)
print(" DISCOVERY COMPLETE")
print("="*60)
print("""
Interpretation guide:
  > 58%  at 1b_15m  = viable 5m signal (15m proxy)
  > 60%  at 4b_1h   = viable scalp-to-intraday
  > 65%  at 8b_2h   = strong intraday signal
  ECS comparison: 40% at 15m, 68.5% at 8h (SWING only)
""")
