"""
Backtest: Multi-timeframe Confirmation + Regime-Aware Sizing
=============================================================
Tests the effect of:
1. 4h trend confirmation (requires 4h trend = UP for 1h BUY)
2. Regime-aware position sizing (reduce size during drawdown, scale back in)

Compares three scenarios:
  A. Baseline: 1h only, fixed 1% risk per trade (original)
  B. With 4h filter: 1h BUY only when 4h trend = UP
  C. With 4h filter + regime sizing: above + dynamic position sizing
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from backend.memory.scanner import scan_market
from backend.utils.data_loader import load_data
from backend.validation.multiframe_filter import MultiFrameFilter
from backend.validation.regime_sizer import RegimeAwareSizer
from backend.validation.trade_simulator import simulate_trades


def main():
    print("=" * 70)
    print("  MULTI-TIMEFRAME + REGIME-AWARE BACKTEST")
    print("=" * 70)

    # Load data
    project_root = Path(__file__).parent
    data_1h = load_data(project_root / "data" / "XAU_1h_data.csv")
    data_1h = data_1h.sort_values("time").dropna(subset=["time"])
    df_1y = data_1h[data_1h["time"] >= data_1h["time"].max() - pd.Timedelta(days=365)].reset_index(drop=True)

    memory = scan_market(df_1y)
    print(f"\nData: {len(memory):,} 1h bars in 1-year window")

    # Inject timestamps into memory records for multiframe filtering
    for i, rec in enumerate(memory):
        if i < len(df_1y):
            rec["timestamp"] = df_1y.iloc[i]["time"]

    # ── Scenario A: Baseline (original) ─────────────────────────────────
    print(f"\n[ Scenario A: Baseline (1h only, fixed 1% risk) ]")
    sim_a = simulate_trades(
        memory,
        hold_bars=5,
        stop_loss_pts=10,
        take_profit_pts=20,
        initial_capital=10_000.0,
        risk_per_trade_pct=1.0,
        multiframe_filter=None,
        regime_sizer=None,
    )
    print(f"  Trades       : {sim_a['total_trades']}")
    print(f"  Winrate      : {sim_a['winrate']:.4f}")
    print(f"  Net return   : +{sim_a['net_return_pct']:.2f}%")
    print(f"  Max DD       : -{sim_a['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe       : {sim_a['sharpe']:.3f}")
    print(f"  Calmar       : {sim_a['net_return_pct'] / sim_a['max_drawdown_pct'] if sim_a['max_drawdown_pct'] > 0 else 0:.2f}x")
    a_calmar = sim_a["net_return_pct"] / sim_a["max_drawdown_pct"] if sim_a["max_drawdown_pct"] > 0 else 0

    # ── Scenario B: With 4h filter ─────────────────────────────────────
    print(f"\n[ Scenario B: With 4h trend confirmation ]")
    mf = MultiFrameFilter(project_root / "data" / "XAU_4h_data.csv")
    sim_b = simulate_trades(
        memory,
        hold_bars=5,
        stop_loss_pts=10,
        take_profit_pts=20,
        initial_capital=10_000.0,
        risk_per_trade_pct=1.0,
        multiframe_filter=mf,
        regime_sizer=None,
    )
    print(f"  Trades       : {sim_b['total_trades']:>4}  (Δ {sim_b['total_trades'] - sim_a['total_trades']:+d})")
    print(f"  Winrate      : {sim_b['winrate']:.4f}  (Δ {sim_b['winrate'] - sim_a['winrate']:+.4f})")
    print(f"  Net return   : +{sim_b['net_return_pct']:.2f}%  (Δ {sim_b['net_return_pct'] - sim_a['net_return_pct']:+.2f}%)")
    print(f"  Max DD       : -{sim_b['max_drawdown_pct']:.2f}%  (Δ {sim_b['max_drawdown_pct'] - sim_a['max_drawdown_pct']:+.2f}%)")
    print(f"  Sharpe       : {sim_b['sharpe']:.3f}  (Δ {sim_b['sharpe'] - sim_a['sharpe']:+.3f})")
    b_calmar = sim_b["net_return_pct"] / sim_b["max_drawdown_pct"] if sim_b["max_drawdown_pct"] > 0 else 0
    print(f"  Calmar       : {b_calmar:.2f}x  (Δ {b_calmar - a_calmar:+.2f}x)")

    # ── Scenario C: With 4h filter + regime sizing ─────────────────────
    print(f"\n[ Scenario C: With 4h filter + regime-aware sizing ]")
    mf2 = MultiFrameFilter(project_root / "data" / "XAU_4h_data.csv")
    regime_sizer = RegimeAwareSizer(peak_equity=10_000.0)

    sim_c = simulate_trades(
        memory,
        hold_bars=5,
        stop_loss_pts=10,
        take_profit_pts=20,
        initial_capital=10_000.0,
        risk_per_trade_pct=1.0,
        multiframe_filter=mf2,
        regime_sizer=regime_sizer,
    )
    print(f"  Trades       : {sim_c['total_trades']:>4}  (Δ {sim_c['total_trades'] - sim_a['total_trades']:+d})")
    print(f"  Winrate      : {sim_c['winrate']:.4f}  (Δ {sim_c['winrate'] - sim_a['winrate']:+.4f})")
    print(f"  Net return   : +{sim_c['net_return_pct']:.2f}%  (Δ {sim_c['net_return_pct'] - sim_a['net_return_pct']:+.2f}%)")
    print(f"  Max DD       : -{sim_c['max_drawdown_pct']:.2f}%  (Δ {sim_c['max_drawdown_pct'] - sim_a['max_drawdown_pct']:+.2f}%)")
    print(f"  Sharpe       : {sim_c['sharpe']:.3f}  (Δ {sim_c['sharpe'] - sim_a['sharpe']:+.3f})")
    c_calmar = sim_c["net_return_pct"] / sim_c["max_drawdown_pct"] if sim_c["max_drawdown_pct"] > 0 else 0
    print(f"  Calmar       : {c_calmar:.2f}x  (Δ {c_calmar - a_calmar:+.2f}x)")

    # ── Summary ────────────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Goal: reduce max DD while preserving return (improve Calmar ratio)")
    print(f"\n  Scenario A (baseline)  : DD = {sim_a['max_drawdown_pct']:.2f}%  return = {sim_a['net_return_pct']:.2f}%  Calmar = {a_calmar:.2f}x")
    print(f"  Scenario B (+4h)       : DD = {sim_b['max_drawdown_pct']:.2f}%  return = {sim_b['net_return_pct']:.2f}%  Calmar = {b_calmar:.2f}x  ← 4h trend filter alone")
    print(f"  Scenario C (+4h+sizing): DD = {sim_c['max_drawdown_pct']:.2f}%  return = {sim_c['net_return_pct']:.2f}%  Calmar = {c_calmar:.2f}x  ← full solution")
    print(f"\n  DD improvement (A→C): {sim_a['max_drawdown_pct'] - sim_c['max_drawdown_pct']:.2f}pp  ({(1 - sim_c['max_drawdown_pct']/sim_a['max_drawdown_pct'])*100:.1f}% reduction)")
    print(f"  Return trade-off    : {sim_c['net_return_pct'] - sim_a['net_return_pct']:+.2f}pp")
    print(f"  Calmar improvement  : {c_calmar / a_calmar:.2f}x better (Calmar {a_calmar:.2f}x → {c_calmar:.2f}x)")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
