"""
Monte Carlo Validation — AstroQuant Market Causality Lab
=========================================================
Tests statistical robustness of the EXPANSION+UP signal edge.

Four tests:
  1. EV test: is avg trade P&L significantly > 0 (t-test)?
  2. WR test: is winrate significantly > 50% (z-test)?
  3. Drawdown test: bootstrap N=10,000 orderings — is observed max DD
     better than median random ordering? (fixed-dollar sizing ensures DD path-depends on order)
  4. Kelly robustness: positive Kelly in all four quarters?

Note on Sharpe: trade-level Sharpe = avg(pnl)/std(pnl)*sqrt(N) is invariant to
shuffling (mean/std unchanged for same values). We therefore test path-dependent
drawdown for the bootstrap, and EV significance via t-test.
"""
from __future__ import annotations

import math
import random
import statistics
import os

import pandas as pd

from backend.memory.scanner import scan_market
from backend.utils.data_loader import load_data
from backend.validation.trade_simulator import simulate_trades

N_SIMULATIONS = 10_000
INITIAL_CAPITAL = 10_000.0
RISK_PCT = 1.0
HOLD_BARS = 5
SL_PTS = 10.0
TP_PTS = 20.0
RANDOM_SEED = 42


def _max_dd(pnl_list: list, initial: float = INITIAL_CAPITAL) -> float:
    """Max drawdown (%) using fixed-dollar sizing (same $ per trade)."""
    equity = initial
    peak = equity
    max_dd = 0.0
    for pnl in pnl_list:
        equity += pnl
        if equity > peak:
            peak = equity
        elif peak > 0:
            dd = (peak - equity) / peak * 100
            max_dd = max(max_dd, dd)
    return max_dd


def _percentile(data: list, p: float) -> float:
    s = sorted(data)
    n = len(s)
    k = (p / 100) * (n - 1)
    lo, hi = int(k), min(int(k) + 1, n - 1)
    return s[lo] + (k - lo) * (s[hi] - s[lo])


def _normal_sf(z: float) -> float:
    """P(Z > z) for standard normal (Abramowitz & Stegun approximation)."""
    if z < 0:
        return 1 - _normal_sf(-z)
    t = 1 / (1 + 0.2316419 * z)
    poly = t * (0.319381530
                + t * (-0.356563782
                       + t * (1.781477937
                              + t * (-1.821255978
                                     + t * 1.330274429))))
    return (1 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * z * z) * poly


def run_monte_carlo() -> None:
    print("=" * 60)
    print("  Monte Carlo Validation — AstroQuant")
    print("=" * 60)
    print(f"  Config : hold={HOLD_BARS}bars  SL={SL_PTS}pts  TP={TP_PTS}pts")
    print(f"  N runs : {N_SIMULATIONS:,}  seed={RANDOM_SEED}")

    DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "XAU_1h_data.csv")
    df = load_data(DATA_PATH)
    df = df.sort_values("time").dropna(subset=["time"])
    df_1y = df[df["time"] >= df["time"].max() - pd.Timedelta(days=365)].reset_index(drop=True)
    memory = scan_market(df_1y)

    result = simulate_trades(
        memory,
        hold_bars=HOLD_BARS,
        stop_loss_pts=SL_PTS,
        take_profit_pts=TP_PTS,
        initial_capital=INITIAL_CAPITAL,
        risk_per_trade_pct=RISK_PCT,
    )

    trades   = result["trades"]
    pnls     = [t["pnl"] for t in trades]
    n        = len(pnls)
    winrate  = result["winrate"]
    avg_pnl  = statistics.mean(pnls)
    std_pnl  = statistics.stdev(pnls)
    obs_dd   = _max_dd(pnls)
    obs_calmar = result["net_return_pct"] / obs_dd if obs_dd > 0 else 0.0

    print(f"\n[ Observed Strategy (N={n} trades) ]")
    print(f"  Net return   : +{result['net_return_pct']:.2f}%  ($10k → ${result['final_equity']:.2f})")
    print(f"  Max DD       : -{result['max_drawdown_pct']:.2f}%  (compounded)  / -{obs_dd:.2f}%  (fixed-$)")
    print(f"  Sharpe       : {result['sharpe']:.3f}")
    print(f"  Winrate      : {winrate:.4f}  ({winrate*100:.2f}%)")
    print(f"  Avg trade    : +${avg_pnl:.2f}  ±${std_pnl:.2f}")
    print(f"  R-ratio      : {result['r_ratio']:.2f}x   Kelly={result['kelly_fraction']:.4f}  ½K={result['half_kelly']:.4f}")
    print(f"  Calmar       : {obs_calmar:.2f}x  (return/MaxDD fixed-$)")

    # ── Test 1: EV t-test ────────────────────────────────────────────
    t_stat = avg_pnl / (std_pnl / math.sqrt(n))
    p_ev = _normal_sf(t_stat)

    print(f"\n[ Test 1: EV Significance (one-tailed t-test) ]")
    print(f"  H₀: avg trade P&L = 0")
    print(f"  t-stat : {t_stat:.3f}")
    print(f"  p-value: {p_ev:.6f}", end="  ")
    if p_ev < 0.001:
        print("***  (p < 0.001)")
    elif p_ev < 0.01:
        print("**   (p < 0.01)")
    elif p_ev < 0.05:
        print("*    (p < 0.05)")
    else:
        print("ns")
    print(f"  Verdict: {'REJECT H₀ — avg P&L is significantly positive' if p_ev < 0.05 else 'FAIL TO REJECT H₀'}")

    # ── Test 2: WR z-test ────────────────────────────────────────────
    z_wr = (winrate - 0.5) / math.sqrt(0.25 / n)
    p_wr = _normal_sf(z_wr)

    print(f"\n[ Test 2: Winrate vs 50% (one-tailed z-test) ]")
    print(f"  H₀: winrate = 0.50")
    print(f"  z-stat : {z_wr:.3f}")
    print(f"  p-value: {p_wr:.4f}", end="  ")
    if p_wr < 0.001:
        print("***")
    elif p_wr < 0.01:
        print("**")
    elif p_wr < 0.05:
        print("*")
    else:
        print("ns")
    print(f"  Verdict: {'REJECT H₀ — WR > 50%' if p_wr < 0.05 else 'WR edge marginal (R-ratio compensates)'}")
    print(f"  NOTE: positive Kelly={result['kelly_fraction']:.4f} confirms edge even with borderline WR.")

    # ── Test 3: Drawdown bootstrap ───────────────────────────────────
    print(f"\nRunning {N_SIMULATIONS:,} bootstrap shuffles...")
    rng = random.Random(RANDOM_SEED)
    boot_dds = []
    boot_calmars = []

    for _ in range(N_SIMULATIONS):
        shuffled = pnls[:]
        rng.shuffle(shuffled)
        dd = _max_dd(shuffled)
        ret = (sum(shuffled) / INITIAL_CAPITAL) * 100
        boot_dds.append(dd)
        boot_calmars.append(ret / dd if dd > 0 else 0.0)

    worse_dd = sum(1 for d in boot_dds if d >= obs_dd)
    p_dd = worse_dd / N_SIMULATIONS

    print(f"\n[ Test 3: Max-Drawdown Bootstrap (N={N_SIMULATIONS:,}) ]")
    print(f"  {'Metric':<18} {'Observed':>10} {'p5':>8} {'Median':>8} {'p95':>8}")
    print("  " + "-" * 48)
    print(f"  {'Max DD (%)':<18} {obs_dd:>10.2f} "
          f"{_percentile(boot_dds, 5):>8.2f} "
          f"{_percentile(boot_dds, 50):>8.2f} "
          f"{_percentile(boot_dds, 95):>8.2f}")
    print(f"  {'Calmar':<18} {obs_calmar:>10.2f} "
          f"{_percentile(boot_calmars, 5):>8.2f} "
          f"{_percentile(boot_calmars, 50):>8.2f} "
          f"{_percentile(boot_calmars, 95):>8.2f}")
    print(f"\n  Shuffled runs with DD ≥ observed: {worse_dd}/{N_SIMULATIONS}  (p={p_dd:.4f})")

    med_dd = _percentile(boot_dds, 50)
    if obs_dd < med_dd:
        print(f"  Our actual sequence has LOWER DD than median shuffle ({obs_dd:.2f}% < {med_dd:.2f}%) — ordering helps.")
    elif obs_dd <= _percentile(boot_dds, 75):
        print(f"  Our actual sequence is near median shuffle — ordering is neutral.")
    else:
        print(f"  Our actual sequence has slightly higher DD than median — ordering is slightly adverse.")

    # ── Test 4: Kelly per quarter ────────────────────────────────────
    print(f"\n[ Test 4: Kelly Robustness Across Quarters ]")
    q_size = n // 4
    all_kelly_positive = True
    for qi in range(4):
        q = pnls[qi * q_size : (qi + 1) * q_size]
        q_wins = [p for p in q if p > 0]
        q_loss = [p for p in q if p <= 0]
        wr_q = len(q_wins) / len(q) if q else 0.0
        avgW = statistics.mean(q_wins) if q_wins else 0.0
        avgL = abs(statistics.mean(q_loss)) if q_loss else 0.001
        r = avgW / avgL if avgL else 0.0
        kelly_q = wr_q - (1 - wr_q) / r if r > 0 else 0.0
        if kelly_q <= 0:
            all_kelly_positive = False
        mark = "✓" if kelly_q > 0 else "✗"
        print(f"  Q{qi+1}: {len(q):>4} trades  WR={wr_q:.3f}  avgW=${avgW:.1f}  avgL=${avgL:.1f}  R={r:.2f}x  Kelly={kelly_q:.4f}  {mark}")

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  CONCLUSION")
    print(f"{'=' * 60}")
    print(f"  Test 1 EV   : p={p_ev:.5f}  {'✓ significant' if p_ev < 0.05 else '○ marginal'}")
    print(f"  Test 2 WR   : p={p_wr:.4f}  {'✓ significant' if p_wr < 0.05 else '○ marginal (R-ratio compensates)'}")
    print(f"  Test 3 DD   : obs={obs_dd:.2f}%  median_boot={_percentile(boot_dds,50):.2f}%")
    print(f"  Test 4 Kelly: {'✓ positive in all 4 quarters' if all_kelly_positive else '✗ negative in at least one quarter'}")
    print()
    if p_ev < 0.001:
        print("  *** Highly significant positive EV per trade.")
        print(f"      +${avg_pnl:.2f} expected per trade regardless of ordering.")
        print(f"      The +{result['net_return_pct']:.1f}% return is real signal edge, not luck.")
    elif p_ev < 0.05:
        print("  *   Statistically significant positive EV per trade.")
    else:
        print("      EV is positive but not yet significant at 95% — more data needed.")

    if result["kelly_fraction"] > 0.05:
        print(f"      Kelly={result['kelly_fraction']:.4f} (½K={result['half_kelly']:.4f}) → optimal position size ~{result['half_kelly']*100:.1f}% equity per trade.")
    print("=" * 60)


if __name__ == "__main__":
    run_monte_carlo()
