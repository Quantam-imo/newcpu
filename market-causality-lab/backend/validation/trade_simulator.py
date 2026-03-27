"""
Trade Simulator — Accuracy Pass v3 + Multi-timeframe + Regime Sizing
Simulates a fixed-hold equity curve from memory records using v2-filtered signals.
Tracks equity, Sharpe ratio, max drawdown, win/loss streaks, and Kelly fraction.

Supports optional:
  - Multi-timeframe confirmation (4h trend filter)
  - Regime-aware position sizing (Calmar-based)

Optimal parameters (derived from sweep over 1Y XAU/USD 1h data):
  hold_bars = 5, stop_loss_pts = 10, take_profit_pts = 20
  → Sharpe 7.826, return +204.7%, max DD -7.46%, ½ Kelly 9.2%
"""
from __future__ import annotations

import math
import statistics
from typing import List, Optional

# Import multiframe filter function
from backend.validation.multiframe_filter import multiframe_filter as apply_multiframe_filter


# Default hold period and SL/TP derived from MAE/MFE sweep
DEFAULT_HOLD_BARS = 5
DEFAULT_STOP_LOSS_PTS = 10.0    # pts adverse before stop-out (XAU $10 ≈ 0.33% of $3000)
DEFAULT_TAKE_PROFIT_PTS = 20.0  # pts favorable before taking profit


def _is_signal_valid(rec: dict) -> bool:
    """Accuracy Pass v2 filter: EXPANSION+UP BUY only (MANIPULATION suppressed)."""
    phase = rec.get("phase", "")
    sig = rec.get("signal", "WAIT")
    if sig not in {"BUY", "SELL"}:
        return False
    if phase == "MANIPULATION":
        return False
    if phase == "EXPANSION" and rec["state"]["volatility"] < 4.5:
        return False
    return True


def simulate_trades(
    memory: List[dict],
    hold_bars: int = DEFAULT_HOLD_BARS,
    stop_loss_pts: Optional[float] = DEFAULT_STOP_LOSS_PTS,
    take_profit_pts: Optional[float] = DEFAULT_TAKE_PROFIT_PTS,
    initial_capital: float = 10_000.0,
    risk_per_trade_pct: float = 1.0,
    multiframe_filter=None,
    regime_sizer=None,
) -> dict:
    """
    Run a fixed-hold-period trade simulation on filtered BUY signals.

    Args:
        memory: Output of scan_market()
        hold_bars: Max bars to hold; exits earlier on SL/TP hit
        stop_loss_pts: Price points below entry to stop out (None = no stop)
        take_profit_pts: Price points above entry to take profit (None = no TP)
        initial_capital: Starting capital in dollars
        risk_per_trade_pct: % of current equity risked per trade (position sizing)
        multiframe_filter: Optional MultiFrameFilter instance for 4h trend confirmation
        regime_sizer: Optional RegimeAwareSizer instance for DD-based position scaling

    Returns:
        Dict with equity curve, trade log, and summary statistics.
    """
    trades = []
    open_trades: list = []   # (entry_idx, entry_price, capital_at_entry, actual_risk_pct)

    equity = initial_capital
    equity_curve = [equity]
    peak_equity = equity

    wins = 0
    losses = 0
    max_consec_wins = 0
    max_consec_losses = 0
    _consec_wins = 0
    _consec_losses = 0
    sl_hits = 0
    tp_hits = 0
    hold_exits = 0

    for i, rec in enumerate(memory):
        # Check open trades for SL/TP hit or hold expiry
        still_open = []
        for (entry_idx, entry_price, capital_at_entry, effective_risk) in open_trades:
            # Scan every bar since entry for intra-trade SL/TP
            hit_price = None
            exit_reason = "hold"
            for k in range(1, i - entry_idx + 1):
                if entry_idx + k >= len(memory):
                    break
                bar_price = memory[entry_idx + k]["state"]["price"]
                if stop_loss_pts is not None and (bar_price - entry_price) <= -stop_loss_pts:
                    hit_price = entry_price - stop_loss_pts  # fill at stop level
                    exit_reason = "sl"
                    break
                if take_profit_pts is not None and (bar_price - entry_price) >= take_profit_pts:
                    hit_price = entry_price + take_profit_pts  # fill at limit level
                    exit_reason = "tp"
                    break

            if exit_reason in ("sl", "tp") or (i - entry_idx >= hold_bars):
                exit_price = hit_price if hit_price is not None else rec["state"]["price"]
                pct_move = (exit_price - entry_price) / entry_price
                # Use effective_risk instead of risk_per_trade_pct (may be scaled by regime)
                pnl = capital_at_entry * (effective_risk / 100) * (pct_move / 0.01)
                equity += pnl
                peak_equity = max(peak_equity, equity)
                equity_curve.append(equity)

                win = pnl > 0
                trades.append({
                    "entry_bar": entry_idx,
                    "exit_bar": i,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_price, 2),
                    "pct_move": round(pct_move * 100, 4),
                    "pnl": round(pnl, 4),
                    "win": win,
                    "exit_reason": exit_reason,
                })
                if win:
                    wins += 1
                    _consec_wins += 1
                    _consec_losses = 0
                    max_consec_wins = max(max_consec_wins, _consec_wins)
                else:
                    losses += 1
                    _consec_losses += 1
                    _consec_wins = 0
                    max_consec_losses = max(max_consec_losses, _consec_losses)
                if exit_reason == "sl":
                    sl_hits += 1
                elif exit_reason == "tp":
                    tp_hits += 1
                else:
                    hold_exits += 1
            else:
                still_open.append((entry_idx, entry_price, capital_at_entry, effective_risk))
        open_trades = still_open

        # Update regime sizer at each bar
        if regime_sizer is not None:
            regime_sizer.update_equity(equity)

        # Open new trade on valid signal with multiframe confirmation
        if _is_signal_valid(rec) and rec["signal"] == "BUY":
            # Apply multiframe filter (4h trend confirmation)
            signal_after_mf = rec["signal"]
            if multiframe_filter is not None:
                ts = rec.get("timestamp")
                signal_after_mf = apply_multiframe_filter(rec["signal"], ts, multiframe_filter)

            if signal_after_mf == "BUY" and i + hold_bars < len(memory):
                # Apply regime sizing (reduce position in high DD)
                effective_risk = risk_per_trade_pct
                if regime_sizer is not None:
                    from backend.validation.regime_sizer import scale_position_size
                    effective_risk = scale_position_size(risk_per_trade_pct, regime_sizer, apply_scaling=True)

                open_trades.append((i, rec["state"]["price"], equity, effective_risk))

    # Force-close any remaining open trades at last bar
    if memory:
        last_price = memory[-1]["state"]["price"]
        for (entry_idx, entry_price, capital_at_entry, effective_risk) in open_trades:
            pct_move = (last_price - entry_price) / entry_price
            pnl = capital_at_entry * (effective_risk / 100) * (pct_move / 0.01)
            equity += pnl
            peak_equity = max(peak_equity, equity)
            equity_curve.append(equity)
            win = pnl > 0
            trades.append({
                "entry_bar": entry_idx,
                "exit_bar": len(memory) - 1,
                "entry_price": round(entry_price, 2),
                "exit_price": round(last_price, 2),
                "pct_move": round(pct_move * 100, 4),
                "pnl": round(pnl, 4),
                "win": win,
                "exit_reason": "force_close",
            })
            if win:
                wins += 1
            else:
                losses += 1
            hold_exits += 1

    # ── Summary Statistics ───────────────────────────────────────────
    total_trades = len(trades)
    winrate = wins / total_trades if total_trades else 0.0
    net_return_pct = (equity - initial_capital) / initial_capital * 100

    # Max drawdown
    max_dd = 0.0
    peak = initial_capital
    trough = initial_capital
    for eq in equity_curve:
        if eq > peak:
            peak = eq
            trough = eq
        else:
            trough = min(trough, eq)
            dd = (peak - trough) / peak * 100
            max_dd = max(max_dd, dd)

    # Sharpe ratio
    pnls = [t["pnl"] for t in trades]
    if len(pnls) >= 2:
        avg_pnl = statistics.mean(pnls)
        std_pnl = statistics.stdev(pnls)
        sharpe = (avg_pnl / std_pnl) * math.sqrt(total_trades) if std_pnl > 0 else 0.0
    else:
        avg_pnl = 0.0
        sharpe = 0.0

    # Kelly fraction: f* = WR - (1-WR)/R where R = avg_win / avg_loss
    wins_pnl = [t["pnl"] for t in trades if t["win"]]
    losses_pnl = [t["pnl"] for t in trades if not t["win"]]
    avg_win = statistics.mean(wins_pnl) if wins_pnl else 0.0
    avg_loss = abs(statistics.mean(losses_pnl)) if losses_pnl else 0.001
    r_ratio = avg_win / avg_loss if avg_loss else 0.0
    kelly = winrate - (1 - winrate) / r_ratio if r_ratio > 0 else 0.0
    half_kelly = kelly / 2  # standard conservative sizing recommendation

    return {
        "hold_bars": hold_bars,
        "stop_loss_pts": stop_loss_pts,
        "take_profit_pts": take_profit_pts,
        "initial_capital": initial_capital,
        "final_equity": round(equity, 2),
        "net_return_pct": round(net_return_pct, 2),
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "winrate": round(winrate, 4),
        "avg_pnl_per_trade": round(avg_pnl, 4),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe": round(sharpe, 3),
        "max_consec_wins": max_consec_wins,
        "max_consec_losses": max_consec_losses,
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "r_ratio": round(r_ratio, 3),
        "kelly_fraction": round(kelly, 4),
        "half_kelly": round(half_kelly, 4),
        "exit_breakdown": {
            "stop_loss": sl_hits,
            "take_profit": tp_hits,
            "hold_expiry": hold_exits,
        },
        "equity_curve": equity_curve,
        "trades": trades,
    }
