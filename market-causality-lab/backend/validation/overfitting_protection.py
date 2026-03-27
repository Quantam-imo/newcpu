"""Overfitting Protection Engine — walk-forward accuracy monitoring and regime drift guard."""
from __future__ import annotations


def rolling_accuracy(pnl_series: list, window: int = 20) -> dict:
    """
    Compute rolling win-rate over the most recent `window` trades.
    A large drop vs historical win-rate suggests curve-fitting / overfitting.
    """
    if len(pnl_series) < window:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "window_accuracy": None,
            "historical_accuracy": None,
            "degradation": None,
            "overfit_suspected": False,
        }

    recent = pnl_series[-window:]
    wins_recent = sum(1 for p in recent if p > 0)
    win_rate = round(wins_recent / window, 4)

    total_wins = sum(1 for p in pnl_series if p > 0)
    hist_rate = round(total_wins / len(pnl_series), 4)

    degradation = round(hist_rate - win_rate, 4)
    overfit_suspected = degradation > 0.15 and win_rate < 0.45

    return {
        "status": "OVERFIT_WARNING" if overfit_suspected else "STABLE",
        "window_accuracy": win_rate,
        "historical_accuracy": hist_rate,
        "degradation": degradation,
        "overfit_suspected": overfit_suspected,
    }


def regime_stability_check(signal_history: list, window: int = 30) -> dict:
    """
    Detect if recent signal distribution has materially shifted vs history.
    A large drift may indicate that market regime has changed or parameters are stale.
    """
    if len(signal_history) < window:
        return {
            "stable": True,
            "status": "INSUFFICIENT_HISTORY",
            "recent_buy_ratio": None,
            "historical_buy_ratio": None,
            "regime_drift": None,
        }

    def buy_ratio(sigs: list) -> float:
        buys = sum(1 for s in sigs if "BUY" in str(s).upper())
        sells = sum(1 for s in sigs if "SELL" in str(s).upper())
        total = buys + sells
        return buys / total if total > 0 else 0.5

    recent = signal_history[-window:]
    historical = signal_history[:-window]

    r_ratio = round(buy_ratio(recent), 3)
    h_ratio = round(buy_ratio(historical), 3) if historical else r_ratio
    drift = round(abs(r_ratio - h_ratio), 3)
    stable = drift < 0.20

    return {
        "stable": stable,
        "status": "STABLE" if stable else "REGIME_SHIFT_DETECTED",
        "recent_buy_ratio": r_ratio,
        "historical_buy_ratio": h_ratio,
        "regime_drift": drift,
    }


def overfitting_guard(backtest_stats: dict | None, signal_history: list | None = None) -> dict:
    """
    Master overfitting protection gate.
    Combines rolling accuracy decay + regime stability checks.
    Returns overall risk level and action recommendation.
    """
    pnl = (backtest_stats or {}).get("pnl_series", [])
    sigs = signal_history or []

    accuracy = rolling_accuracy(pnl)
    stability = regime_stability_check(sigs)

    high_risk = accuracy.get("overfit_suspected") or not stability["stable"]
    overfit_risk = "HIGH" if high_risk else "LOW"

    return {
        "accuracy": accuracy,
        "stability": stability,
        "overfit_risk": overfit_risk,
        "recommendation": "REDUCE_COMPLEXITY" if high_risk else "OK",
    }
