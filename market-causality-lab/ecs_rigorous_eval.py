"""
ecs_rigorous_eval.py
====================
Rigorous ECS evaluation per the framework:
  1. Forward return distributions (mean, median, std, %+, MAE, MFE)
  2. Percentile-based thresholds (regime-stable)
  3. Entry type comparison: immediate / delayed / retest
  4. ECS vs ECS+AI vs ECS+AI-disagree win rate
  5. Expectancy (win_rate*avg_win - loss_rate*avg_loss)
  6. Regime split: 2000-2011 / 2012-2018 / 2019-2021 / 2022-2026
  7. Walk-forward validation (4 folds)
  8. ECS "break it" stress test

Run:
    python3 ecs_rigorous_eval.py
"""

import sys
import time
import warnings
import numpy as np
import pandas as pd
from collections import defaultdict

sys.path.insert(0, ".")
warnings.filterwarnings("ignore")

from backend.memory.scanner import scan_market

# ─────────────────────────────────────────────────────────────────────────────
# 0. DATA
# ─────────────────────────────────────────────────────────────────────────────
print("Loading data …")
df = pd.read_csv("data/XAU_15m_data.csv", sep=";")
df.columns = [c.lower() for c in df.columns]
df["date"] = pd.to_datetime(df["date"], errors="coerce")
df = df.dropna(subset=["close", "date"]).reset_index(drop=True)
print(f"  {len(df):,} bars  {df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}")

HORIZONS = {
    "1b_15m":  1,
    "4b_1h":   4,
    "8b_2h":   8,
    "16b_4h":  16,
    "32b_8h":  32,
    "80b_20h": 80,   # test beyond the "8-bar myth"
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. COLLECT ECS EVENTS (percentile-threshold version)
# ─────────────────────────────────────────────────────────────────────────────

def collect_ecs_events(df_slice, label="", percentile_thresholds=None, fixed_thresholds=None, max_windows=24):
    """
    Scan windows of df_slice, return list of event dicts.
    If percentile_thresholds supplied, compute them from this slice.
    If fixed_thresholds supplied, use them directly.
    """
    WINDOW = 600
    n = len(df_slice)
    n_windows = max(8, min(max_windows, n // WINDOW))
    sample_starts = np.linspace(0, n - WINDOW - 1, n_windows, dtype=int)

    raw_records = []   # (abs_idx, record)
    t0 = time.time()
    for i, start in enumerate(sample_starts):
        chunk = df_slice.iloc[int(start):int(start)+WINDOW].reset_index(drop=True)
        recs = scan_market(chunk, max_records=None)
        warmup = len(recs) // 3
        for local_i, r in enumerate(recs[warmup:]):
            abs_idx = int(start) + warmup + local_i
            raw_records.append((abs_idx, r))
        if label and (i+1) % max(1, n_windows//4) == 0:
            print(f"    [{i+1}/{n_windows}] {len(raw_records)} records | {time.time()-t0:.0f}s", flush=True)

    if not raw_records:
        return []

    # Compute percentile thresholds from collected records
    def _pct(key_fn, pct):
        vals = [key_fn(r) for _, r in raw_records if key_fn(r) is not None]
        if not vals:
            return None
        return np.percentile(vals, pct)

    get_vel  = lambda r: abs(float((r.get("physics") or {}).get("velocity") or 0))
    get_frc  = lambda r: abs(float((r.get("physics") or {}).get("force") or 0))
    get_conf = lambda r: float((r.get("reliability") or {}).get("conflict_score") or 0)
    get_comp = lambda r: float((r.get("compression") or {}).get("score") or 0)
    get_enrg = lambda r: float((r.get("compression") or {}).get("energy_stored") or 0)

    if percentile_thresholds:
        # Use higher percentiles for fields that are zero-heavy:
        # conflict_score: ~29% are 0 → use p45 to get non-zero threshold
        # compression.score: p25=0.066 → p35 gives a real value
        th_vel  = _pct(get_vel,  percentile_thresholds.get("velocity_pct",  25))
        th_frc  = _pct(get_frc,  percentile_thresholds.get("force_pct",     25))
        th_conf = _pct(get_conf, percentile_thresholds.get("conflict_pct",  45))
        th_comp = _pct(get_comp, percentile_thresholds.get("compression_pct", 35))
        th_enrg = _pct(get_enrg, percentile_thresholds.get("energy_pct",    50))  # above median
        # Guard: if any threshold is None or effectively zero (zero-heavy field), set fallback
        if th_conf is None or th_conf == 0.0:
            raw_conf = sorted([get_conf(r) for _, r in raw_records if get_conf(r) > 0])
            th_conf = raw_conf[len(raw_conf)//3] if raw_conf else 0.15
        if any(v is None for v in [th_vel, th_frc, th_comp, th_enrg]):
            return []
        # Debug: print computed thresholds
        if label:
            print(f"    Pct thresholds: vel<{th_vel:.3f} frc<{th_frc:.3f} "
                  f"conf<{th_conf:.3f} comp<{th_comp:.3f} enrg>{th_enrg:.1f}", flush=True)
    elif fixed_thresholds:
        th_vel  = fixed_thresholds["velocity"]
        th_frc  = fixed_thresholds["force"]
        th_conf = fixed_thresholds["conflict"]
        th_comp = fixed_thresholds["compression"]
        th_enrg = fixed_thresholds["energy"]
    else:
        # defaults from field audit
        th_vel  = 2.0
        th_frc  = 2.5
        th_conf = 0.10
        th_comp = 0.08
        th_enrg = 80.0

    events = []
    for abs_idx, r in raw_records:
        vel  = get_vel(r)
        frc  = get_frc(r)
        conf = get_conf(r)
        comp = get_comp(r)
        enrg = get_enrg(r)
        bias = (r.get("compression") or {}).get("direction_bias", "NEUTRAL")
        ai_dir = (r.get("ai_signal") or {}).get("direction", "NEUTRAL")
        ai_conf = float((r.get("ai_signal") or {}).get("confidence") or 0.5)

        active = (vel < th_vel and frc < th_frc and
                  conf < th_conf and comp < th_comp and enrg > th_enrg)
        # Note: volume_zscore is 0% populated in scanner → not used as filter

        if active:
            fi = abs_idx
            c0 = float(df_slice["close"].iloc[min(fi, len(df_slice)-1)])
            date = df_slice["date"].iloc[min(fi, len(df_slice)-1)]
            events.append({
                "abs": fi,
                "close": c0,
                "date": date,
                "bias": bias,
                "ai_dir": ai_dir,
                "ai_conf": ai_conf,
                "vel": vel, "frc": frc, "conf": conf, "comp": comp, "enrg": enrg,
            })

    return events


# ─────────────────────────────────────────────────────────────────────────────
# 2. FORWARD RETURN DISTRIBUTION
# ─────────────────────────────────────────────────────────────────────────────

def forward_returns(events, df_slice, direction_col="bias"):
    """
    For each event compute forward return at each horizon.
    direction_col: 'bias' (ECS compression bias) or 'ai_dir' (AI model direction).
    Returns dict: horizon -> array of log returns (+ = win)
    """
    results = {h: [] for h in HORIZONS}
    for ev in events:
        i = ev["abs"]
        c0 = ev["close"]
        d = ev.get(direction_col, "NEUTRAL")
        if d == "NEUTRAL":
            continue
        sign = 1 if d == "UP" or d == "BUY" else -1
        for h_name, h_bars in HORIZONS.items():
            fi = i + h_bars
            if fi >= len(df_slice):
                continue
            cf = float(df_slice["close"].iloc[fi])
            # Log return in direction of signal
            ret = sign * np.log(cf / c0) * 100  # in %
            results[h_name].append(ret)
    return results


def print_distribution_table(returns_dict, label):
    print(f"\n{'='*76}")
    print(f"  {label}")
    print(f"{'='*76}")
    print(f"{'Horizon':<12} {'N':>5}  {'Mean%':>7}  {'Median%':>8}  {'Std%':>7}  {'%+':>6}  {'MAE':>7}  {'MFE':>7}  {'E[R]':>8}")
    print(f"{'-'*76}")
    for h_name in HORIZONS:
        arr = np.array(returns_dict[h_name])
        if len(arr) < 3:
            continue
        pct_pos = np.mean(arr > 0) * 100
        mae = -np.mean(np.minimum(arr, 0))      # mean adverse (negative returns)
        mfe =  np.mean(np.maximum(arr, 0))       # mean favorable
        wins  = arr[arr > 0]
        losses = arr[arr <= 0]
        wr = len(wins)/len(arr)
        avg_w = wins.mean() if len(wins) else 0
        avg_l = abs(losses.mean()) if len(losses) else 0
        expectancy = wr * avg_w - (1-wr) * avg_l
        bar = "█" * int(pct_pos / 5)
        print(f"{h_name:<12} {len(arr):>5}  {arr.mean():>+7.3f}  {np.median(arr):>+8.3f}  "
              f"{arr.std():>7.3f}  {pct_pos:>5.1f}%  {mae:>7.3f}  {mfe:>7.3f}  {expectancy:>+8.4f}")
    print()


def baseline_distribution(df_slice):
    """Random baseline: sample same number of random bars."""
    rets = {h: [] for h in HORIZONS}
    idxs = np.random.choice(len(df_slice) - 81, size=500, replace=False)
    for i in idxs:
        c0 = float(df_slice["close"].iloc[i])
        sign = np.random.choice([-1, 1])
        for h_name, h_bars in HORIZONS.items():
            fi = i + h_bars
            if fi >= len(df_slice):
                continue
            cf = float(df_slice["close"].iloc[fi])
            rets[h_name].append(sign * np.log(cf / c0) * 100)
    return rets


# ─────────────────────────────────────────────────────────────────────────────
# 3. ENTRY TYPE COMPARISON
# ─────────────────────────────────────────────────────────────────────────────

def entry_comparison(events, df_slice, horizon_bars=16):
    """
    Compare 3 entry types at 4h horizon:
      A. Immediate (N+1)
      B. Delayed confirmation (wait for close outside range)
      C. Retest (breakout → pullback → continuation)
    """
    results = {"immediate": [], "delayed": [], "retest": []}

    for ev in events:
        i = ev["abs"]
        c0 = ev["close"]
        d = ev.get("bias", "NEUTRAL")
        if d not in ("UP", "DOWN", "BUY", "SELL"):
            continue
        sign = 1 if d in ("UP", "BUY") else -1

        # A: Immediate entry at next bar
        fi = i + horizon_bars
        if fi < len(df_slice):
            cf_a = float(df_slice["close"].iloc[fi])
            ret_a = sign * np.log(cf_a / c0) * 100
            results["immediate"].append(ret_a)

        # B: Delayed — enter when next 3 bars close in signal direction
        entry_b = None
        for j in range(i+1, min(i+6, len(df_slice))):
            cj = float(df_slice["close"].iloc[j])
            if sign == 1 and cj > c0 * 1.0001:
                entry_b = (j, cj)
                break
            elif sign == -1 and cj < c0 * 0.9999:
                entry_b = (j, cj)
                break
        if entry_b:
            je, ce = entry_b
            fi_b = je + horizon_bars
            if fi_b < len(df_slice):
                cf_b = float(df_slice["close"].iloc[fi_b])
                ret_b = sign * np.log(cf_b / ce) * 100
                results["delayed"].append(ret_b)

        # C: Retest — breakout then pulls back within 0.1% of entry
        retest_entry = None
        broken = False
        for j in range(i+1, min(i+20, len(df_slice))):
            cj = float(df_slice["close"].iloc[j])
            if not broken:
                if sign == 1 and cj > c0 * 1.0002:
                    broken = True
                elif sign == -1 and cj < c0 * 0.9998:
                    broken = True
            else:
                # Look for retest (pullback back near c0)
                if abs(cj - c0) / c0 < 0.0005:
                    retest_entry = (j, cj)
                    break
        if retest_entry:
            jr, cr = retest_entry
            fi_r = jr + horizon_bars
            if fi_r < len(df_slice):
                cf_r = float(df_slice["close"].iloc[fi_r])
                ret_r = sign * np.log(cf_r / cr) * 100
                results["retest"].append(ret_r)

    print(f"\n{'─'*60}")
    print(f"  Entry Type Comparison @ {horizon_bars}b horizon")
    print(f"{'─'*60}")
    print(f"{'Entry Type':<18} {'N':>5}  {'Win%':>6}  {'AvgWin%':>8}  {'AvgLoss%':>9}  {'Expectancy':>11}  {'R:R':>6}")
    print(f"{'─'*60}")
    for etype, arr_list in results.items():
        arr = np.array(arr_list)
        if len(arr) < 3:
            print(f"{etype:<18} {'<3 events':>5}")
            continue
        wins = arr[arr > 0]
        losses = arr[arr <= 0]
        wr = len(wins)/len(arr)
        avg_w = wins.mean() if len(wins) else 0
        avg_l = abs(losses.mean()) if len(losses) else 1
        exp = wr * avg_w - (1-wr) * abs(losses.mean() if len(losses) else 0)
        rr = avg_w / avg_l if avg_l > 0 else 0
        print(f"{etype:<18} {len(arr):>5}  {wr*100:>5.1f}%  {avg_w:>+8.3f}  {-abs(losses.mean() if len(losses) else 0):>+9.3f}  {exp:>+11.4f}  {rr:>6.2f}x")


# ─────────────────────────────────────────────────────────────────────────────
# 4. AI DIRECTION FILTER TEST
# ─────────────────────────────────────────────────────────────────────────────

def ai_filter_test(events, df_slice, horizon_bars=32):
    """Test: ECS only vs ECS+AI agree vs ECS+AI disagree."""
    cats = {"ecs_only": [], "agree": [], "disagree": []}

    for ev in events:
        i = ev["abs"]
        c0 = ev["close"]
        bias = ev.get("bias", "NEUTRAL")
        ai_d = ev.get("ai_dir", "NEUTRAL")

        if bias == "NEUTRAL":
            continue

        sign = 1 if bias in ("UP", "BUY") else -1
        fi = i + horizon_bars
        if fi >= len(df_slice):
            continue
        cf = float(df_slice["close"].iloc[fi])
        ret = sign * np.log(cf / c0) * 100

        cats["ecs_only"].append(ret)

        ai_sign = 1 if ai_d in ("UP", "BUY") else (-1 if ai_d in ("DOWN", "SELL") else 0)
        if ai_sign == 0:
            pass
        elif ai_sign == sign:
            cats["agree"].append(ret)
        else:
            cats["disagree"].append(ret)

    print(f"\n{'─'*64}")
    print(f"  AI Direction Filter @ {horizon_bars}b horizon")
    print(f"{'─'*64}")
    print(f"{'Case':<25} {'N':>5}  {'Win%':>6}  {'Mean%':>8}  {'Expectancy':>11}")
    print(f"{'─'*64}")
    for case, arr_list in cats.items():
        arr = np.array(arr_list)
        if len(arr) < 3:
            print(f"{case:<25} {'<3 events':>5}")
            continue
        wins = arr[arr > 0]
        losses = arr[arr <= 0]
        wr = len(wins)/len(arr)
        avg_w = wins.mean() if len(wins) else 0
        avg_l = abs(losses.mean()) if len(losses) else 0
        exp = wr * avg_w - (1-wr) * avg_l
        print(f"{case:<25} {len(arr):>5}  {wr*100:>5.1f}%  {arr.mean():>+8.3f}  {exp:>+11.4f}")


# ─────────────────────────────────────────────────────────────────────────────
# 5. EXPECTANCY CURVE (1→80 bars)
# ─────────────────────────────────────────────────────────────────────────────

def expectancy_curve(events, df_slice, label):
    """Plot expectancy from bar 1 to 80 to find the true peak (kill the 8-bar myth)."""
    BARS = list(range(1, 81))
    curve = []
    for h in BARS:
        rets = []
        for ev in events:
            i = ev["abs"]
            c0 = ev["close"]
            d = ev.get("bias", "NEUTRAL")
            if d == "NEUTRAL":
                continue
            sign = 1 if d in ("UP", "BUY") else -1
            fi = i + h
            if fi >= len(df_slice):
                continue
            cf = float(df_slice["close"].iloc[fi])
            rets.append(sign * np.log(cf / c0) * 100)
        if len(rets) < 5:
            curve.append((h, 0, 0, 0))
            continue
        arr = np.array(rets)
        wins = arr[arr > 0]
        losses = arr[arr <= 0]
        wr = len(wins)/len(arr)
        avg_w = wins.mean() if len(wins) else 0
        avg_l = abs(losses.mean()) if len(losses) else 0
        exp = wr * avg_w - (1-wr) * avg_l
        curve.append((h, wr*100, arr.mean(), exp))

    # Find peak expectancy
    best_bar = max(curve, key=lambda x: x[3])
    print(f"\n  Expectancy curve for '{label}'")
    print(f"  Peak expectancy: bar {best_bar[0]} | E[R]={best_bar[3]:+.4f}% | win%={best_bar[1]:.1f}%")

    # Print every 4th bar to not flood output
    print(f"\n  {'Bar':>5}  {'Win%':>6}  {'Mean%':>8}  {'E[R]':>9}")
    for h, wr, mean, exp in curve:
        if h in [1, 2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80] or h == best_bar[0]:
            marker = " ← PEAK" if h == best_bar[0] else ""
            print(f"  {h:>5}  {wr:>5.1f}%  {mean:>+8.3f}  {exp:>+9.4f}{marker}")
    return curve


# ─────────────────────────────────────────────────────────────────────────────
# 6. REGIME SPLIT
# ─────────────────────────────────────────────────────────────────────────────

REGIMES = {
    "2000–2011 (bull trend)":    ("2000-01-01", "2011-12-31"),
    "2012–2018 (range/bear)":    ("2012-01-01", "2018-12-31"),
    "2019–2021 (COVID shock)":   ("2019-01-01", "2021-12-31"),
    "2022–2026 (macro vol)":     ("2022-01-01", "2026-12-31"),
}


# ─────────────────────────────────────────────────────────────────────────────
# 7. WALK-FORWARD VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def walk_forward(df_full, n_folds=4):
    """
    Split df into n_folds equal chunks.
    For each fold: compute percentile thresholds on first half, test on second half.
    """
    fold_size = len(df_full) // n_folds
    print(f"\n{'='*76}")
    print(f"  WALK-FORWARD VALIDATION ({n_folds} folds, no data leakage)")
    print(f"{'='*76}")

    all_fold_results = []
    for fold in range(n_folds):
        start = fold * fold_size
        end   = start + fold_size
        df_fold = df_full.iloc[start:end].reset_index(drop=True)
        mid = len(df_fold) // 2

        train_slice = df_fold.iloc[:mid]
        test_slice  = df_fold.iloc[mid:]

        print(f"\n  Fold {fold+1}/{n_folds}: "
              f"train={train_slice['date'].iloc[0].date()}→{train_slice['date'].iloc[-1].date()} "
              f"test={test_slice['date'].iloc[0].date()}→{test_slice['date'].iloc[-1].date()}")

        # Compute thresholds from train slice
        print(f"    Computing thresholds from train …", flush=True)
        train_events = collect_ecs_events(
            train_slice.reset_index(drop=True), label="",
            percentile_thresholds={"velocity_pct": 15, "force_pct": 15,
                                   "conflict_pct": 20, "compression_pct": 25,
                                   "energy_pct": 50},
            max_windows=8,
        )
        if not train_events:
            print("    No events in train fold, skip.")
            continue

        # Derive thresholds from training events
        th_vel  = np.percentile([e["vel"]  for e in train_events], 90)  # top 10% of already-quiet
        th_frc  = np.percentile([e["frc"]  for e in train_events], 90)
        th_conf = np.percentile([e["conf"] for e in train_events], 75)
        th_comp = np.percentile([e["comp"] for e in train_events], 75)
        th_enrg = np.percentile([e["enrg"] for e in train_events], 25)  # energy > this

        fixed = {"velocity": th_vel, "force": th_frc, "conflict": th_conf,
                 "compression": th_comp, "energy": th_enrg}

        print(f"    Thresholds: vel<{th_vel:.2f} frc<{th_frc:.2f} conf<{th_conf:.3f} "
              f"comp<{th_comp:.3f} enrg>{th_enrg:.1f}")

        print(f"    Testing on unseen data …", flush=True)
        test_slice_ri = test_slice.reset_index(drop=True)
        test_events = collect_ecs_events(test_slice_ri, label="", fixed_thresholds=fixed, max_windows=8)

        if not test_events:
            print(f"    No ECS events in test fold.")
            continue

        print(f"    {len(test_events)} ECS events found.")

        # Compute win rate at 32-bar (8h)
        wins, total = 0, 0
        for ev in test_events:
            i = ev["abs"]
            c0 = ev["close"]
            d = ev.get("bias", "NEUTRAL")
            if d == "NEUTRAL":
                continue
            sign = 1 if d in ("UP", "BUY") else -1
            fi = i + 32
            if fi >= len(test_slice_ri):
                continue
            cf = float(test_slice_ri["close"].iloc[fi])
            if sign * (cf - c0) > 0:
                wins += 1
            total += 1

        wr = wins / total * 100 if total > 0 else 0
        print(f"    Win rate @ 8h: {wr:.1f}%  ({wins}/{total})")
        all_fold_results.append(wr)

    if all_fold_results:
        print(f"\n  Walk-forward summary:")
        print(f"    Fold win rates: {[f'{r:.1f}%' for r in all_fold_results]}")
        print(f"    Mean: {np.mean(all_fold_results):.1f}%  Std: {np.std(all_fold_results):.1f}%")
        if np.std(all_fold_results) > 15:
            print(f"    ⚠ HIGH VARIANCE — ECS is NOT stable across regimes")
        else:
            print(f"    ✓ Variance acceptable — ECS has consistent edge")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    np.random.seed(42)

    # ── Full 3-year dataset (2021-2026) ──────────────────────────────────────
    df_3y = df.tail(105000).reset_index(drop=True)

    print(f"\n{'='*76}")
    print(f"  STEP 1 — Collecting ECS events (percentile thresholds, 3-year data)")
    print(f"{'='*76}")
    print(f"  Thresholds: velocity<p15, force<p15, conflict<p20, compression<p25, energy>p50")

    events_pct = collect_ecs_events(
        df_3y, label="3yr",
        percentile_thresholds={
            "velocity_pct":    15,
            "force_pct":       15,
            "conflict_pct":    20,
            "compression_pct": 25,
            "energy_pct":      50,
        }
    )
    print(f"\n  ECS events (percentile): {len(events_pct)}")
    if not events_pct:
        print("  ERROR: 0 events — scanner fields may not be populated. Exiting.")
        return

    # ── Fixed thresholds (original) ──────────────────────────────────────────
    print(f"\n{'='*76}")
    print(f"  STEP 1b — Fixed threshold comparison (original ECS definition)")
    print(f"{'='*76}")
    events_fixed = collect_ecs_events(
        df_3y, label="",
        fixed_thresholds={
            "velocity":    2.0,
            "force":       2.5,
            "conflict":    0.10,
            "compression": 0.08,
            "energy":      80.0,
        }
    )
    print(f"  ECS events (fixed):      {len(events_fixed)}")

    # ── Forward return distributions ─────────────────────────────────────────
    print(f"\n{'='*76}")
    print(f"  STEP 2 — Forward Return Distributions")
    print(f"{'='*76}")

    rets_pct   = forward_returns(events_pct,   df_3y, direction_col="bias")
    rets_fixed = forward_returns(events_fixed, df_3y, direction_col="bias")
    rets_base  = baseline_distribution(df_3y)

    print_distribution_table(rets_pct,   f"ECS (Percentile thresholds, {len(events_pct)} events)")
    print_distribution_table(rets_fixed, f"ECS (Fixed thresholds, {len(events_fixed)} events)")
    print_distribution_table(rets_base,  "BASELINE (random, 500 samples)")

    # ── Entry type comparison ─────────────────────────────────────────────────
    print(f"\n{'='*76}")
    print(f"  STEP 3 — Entry Type Comparison @ 4h")
    print(f"{'='*76}")
    entry_comparison(events_pct, df_3y, horizon_bars=16)

    # ── AI filter test ────────────────────────────────────────────────────────
    print(f"\n{'='*76}")
    print(f"  STEP 4 — AI Direction Filter")
    print(f"{'='*76}")
    ai_filter_test(events_pct, df_3y, horizon_bars=32)

    # ── Expectancy curve ──────────────────────────────────────────────────────
    print(f"\n{'='*76}")
    print(f"  STEP 5 — Expectancy Curve (Kill the 8-bar myth)")
    print(f"{'='*76}")
    expectancy_curve(events_pct, df_3y, "ECS percentile")

    # ── Regime split ─────────────────────────────────────────────────────────
    print(f"\n{'='*76}")
    print(f"  STEP 6 — Regime Split")
    print(f"{'='*76}")

    for regime_name, (start_s, end_s) in REGIMES.items():
        df_regime = df[(df["date"] >= start_s) & (df["date"] <= end_s)].reset_index(drop=True)
        if len(df_regime) < 1200:
            print(f"\n  {regime_name}: insufficient data ({len(df_regime)} bars)")
            continue
        print(f"\n  {regime_name}: {len(df_regime):,} bars", flush=True)
        evts = collect_ecs_events(
            df_regime, label="",
            percentile_thresholds={
                "velocity_pct": 15, "force_pct": 15,
                "conflict_pct": 20, "compression_pct": 25,
                "energy_pct": 50,
            }
            ,max_windows=8
        )
        if not evts:
            print(f"    No events.")
            continue
        rets = forward_returns(evts, df_regime, direction_col="bias")
        print_distribution_table(rets, f"{regime_name} ({len(evts)} events)")

    # ── Walk-forward ──────────────────────────────────────────────────────────
    walk_forward(df.tail(105000).reset_index(drop=True), n_folds=4)

    # ── Final verdict ─────────────────────────────────────────────────────────
    print(f"\n{'='*76}")
    print(f"  FINAL VERDICT")
    print(f"{'='*76}")

    if events_pct:
        rets_8h = np.array(rets_pct.get("32b_8h", []))
        if len(rets_8h) > 0:
            wr_8h = np.mean(rets_8h > 0) * 100
            wins_8h  = rets_8h[rets_8h > 0]
            losses_8h = rets_8h[rets_8h <= 0]
            avg_w = wins_8h.mean()  if len(wins_8h)  else 0
            avg_l = abs(losses_8h.mean()) if len(losses_8h) else 0
            wr = len(wins_8h)/len(rets_8h)
            exp = wr * avg_w - (1-wr) * avg_l

            print(f"\n  ECS @ 8h (percentile version, {len(events_pct)} events):")
            print(f"    Win rate: {wr_8h:.1f}%")
            print(f"    Expectancy: {exp:+.4f}% per trade")
            if exp > 0.05:
                print(f"    VERDICT: ECS has positive expectancy — keep as REGIME FILTER")
            elif exp > 0:
                print(f"    VERDICT: Marginal edge — combine with AI confirmation before trading")
            else:
                print(f"    VERDICT: No edge — ECS is currently noise at this threshold setting")

    print(f"\n{'='*76}")
    print(f"  DONE. This is the honest evaluation.")
    print(f"  Professional target: 55-65% win rate + positive expectancy across regimes.")
    print(f"{'='*76}\n")


if __name__ == "__main__":
    main()
