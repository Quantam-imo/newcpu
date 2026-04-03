"""
AstroQuant Astro Backtest (fixed)

The original version called get_astro_signal() — which fetches *live* planetary
data — on every historical bar.  That is incorrect: every bar would return the
same live signal regardless of when it occurred historically.

This fixed version is a thin adapter that defers the actual backtesting to
BacktestEngine (astroquant/backtesting/backtest_engine.py) while still
exposing the same run_backtest(df) -> dict interface for callers that used
the old implementation.

For a complete multi-engine backtest (Gann + ICT + Astro) use
advanced/backtest_runner.py directly.
"""
from __future__ import annotations

import pandas as pd

from astroquant.backtesting.backtest_engine import BacktestEngine, Trade


def run_backtest(df: pd.DataFrame, sl_points: float = 25.0, tp_points: float = 80.0) -> dict:
    """
    Run a simple price-action-only backtest over *df* using the BacktestEngine.

    Each bar a BUY signal is generated when close > open, SELL when close < open.
    Positions are closed at the next bar's open.

    Args:
        df:         DataFrame with columns: open, high, low, close (float).
        sl_points:  Stop-loss distance in price points.
        tp_points:  Take-profit distance in price points.

    Returns:
        dict with keys: total, win_rate, profit_factor, sharpe_ratio, max_drawdown
    """
    engine = BacktestEngine()
    source = "ASTRO_BACKTEST"

    for i in range(1, len(df) - 1):
        bar = df.iloc[i]
        next_bar = df.iloc[i + 1]

        direction = "BUY" if bar["close"] > bar["open"] else "SELL"

        trade = Trade(
            signal_source=source,
            entry_price=float(bar["close"]),
            entry_time=i,
            exit_price=float(next_bar["open"]),
            exit_time=i + 1,
            direction=direction,
        )
        engine.add_trade(source, trade)

    metrics = engine.calculate_metrics(source)
    return {
        "total": metrics.total_trades,
        "win_rate": round(metrics.win_rate * 100, 2),
        "profit_factor": round(metrics.profit_factor, 4),
        "sharpe_ratio": round(metrics.sharpe_ratio, 4),
        "max_drawdown": round(metrics.max_drawdown * 100, 2),
    }
