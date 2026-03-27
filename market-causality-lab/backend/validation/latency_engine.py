"""Latency + Timing Delay Awareness Engine — model signal staleness and entry urgency."""
from __future__ import annotations


def _bar_latency_risk(delay_bars: int) -> str:
    if delay_bars == 0:
        return "LOW"
    if delay_bars <= 2:
        return "MEDIUM"
    if delay_bars <= 5:
        return "HIGH"
    return "CRITICAL"


def estimate_bar_latency(df, signal_bar_offset: int = 0) -> dict:
    """
    Estimate how many bars have elapsed since the signal bar.
    signal_bar_offset=0 means the current (latest) bar, 1 = one bar ago, etc.
    """
    delay = max(0, signal_bar_offset)
    risk = _bar_latency_risk(delay)

    if delay == 0:
        status = "FRESH"
    elif delay <= 2:
        status = "SLIGHT_DELAY"
    elif delay <= 5:
        status = "DELAYED"
    else:
        status = "STALE_SIGNAL"

    return {
        "delay_bars": delay,
        "status": status,
        "risk": risk,
    }


def reaction_time_model(volatility: float, spread: float = 0.5) -> dict:
    """
    Model the available reaction window (in bars) before a signal becomes stale.
    High volatility or wide spreads compress the safe entry window.
    """
    base_window = 3
    vol_penalty = 0 if volatility < 1.0 else (1 if volatility < 3.0 else 2)
    spread_penalty = 0 if spread < 0.5 else (1 if spread < 2.0 else 2)
    safe_bars = max(1, base_window - vol_penalty - spread_penalty)

    urgency = "HIGH" if safe_bars <= 1 else ("MEDIUM" if safe_bars == 2 else "LOW")
    return {
        "safe_entry_bars": safe_bars,
        "urgency": urgency,
        "volatility_risk": vol_penalty > 0,
        "spread_risk": spread_penalty > 0,
    }


def latency_analysis(state: dict, df) -> dict:
    """
    Combined latency assessment: bar freshness + reaction window.
    Returns timing_verdict: OK | CAUTION | ENTRY_RISK.
    """
    volatility = float(state.get("volatility", 1.0))
    spread = float(state.get("spread", 0.5))

    bar_lat = estimate_bar_latency(df, signal_bar_offset=0)
    reaction = reaction_time_model(volatility, spread)

    if bar_lat["risk"] == "CRITICAL" or reaction["urgency"] == "HIGH":
        verdict = "ENTRY_RISK"
    elif bar_lat["risk"] == "HIGH":
        verdict = "CAUTION"
    else:
        verdict = "OK"

    return {
        "bar_latency": bar_lat,
        "reaction_window": reaction,
        "timing_verdict": verdict,
    }
