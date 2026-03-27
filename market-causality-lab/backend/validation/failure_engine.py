"""Failure Mode Engine — identify conditions that invalidate the current signal."""
from __future__ import annotations


def failure_condition(state: dict) -> dict:
    """
    Evaluate conditions that invalidate or weaken the current signal.
    Returns a structured failure assessment with status, severity, and issues.
    """
    issues: list[str] = []
    severity = "NONE"

    trend = state.get("trend", "NEUTRAL")
    momentum = float(state.get("momentum", 0.0))
    volatility = float(state.get("volatility", 1.0))
    market_structure = str(state.get("market_structure", "NORMAL")).upper()

    # 1. Trend-momentum divergence (most common real-world failure)
    if trend == "UP" and momentum < -2:
        issues.append("TREND_MOMENTUM_DIVERGENCE")
        severity = "HIGH"
    elif trend == "DOWN" and momentum > 2:
        issues.append("TREND_MOMENTUM_DIVERGENCE")
        severity = "HIGH"

    # 2. Structure break against position
    if market_structure in ("BREAK_DOWN", "BREAK_UP", "BROKEN", "STRUCTURE_BREAK"):
        issues.append("STRUCTURE_BREAK_AGAINST")
        severity = "CRITICAL"

    # 3. Extreme volatility blow-out
    if volatility > 5.0:
        issues.append("EXTREME_VOLATILITY")
        if severity not in ("CRITICAL",):
            severity = "HIGH"

    # 4. Choppy / flat market — no directional edge
    if volatility < 0.2:
        issues.append("CHOPPY_FLAT_MARKET")
        if severity == "NONE":
            severity = "LOW"

    if not issues:
        status = "VALID"
    elif severity == "CRITICAL":
        status = "INVALIDATED"
    elif severity == "HIGH":
        status = "WEAKENED"
    else:
        status = "CAUTION"

    return {
        "status": status,
        "severity": severity,
        "issues": issues if issues else ["NONE"],
        "invalidated": status == "INVALIDATED",
    }


def failure_engine(state: dict) -> dict:
    """Full failure mode analysis of current market state."""
    return failure_condition(state)

    return "VALID"