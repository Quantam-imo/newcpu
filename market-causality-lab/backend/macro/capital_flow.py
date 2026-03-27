"""Capital Flow Engine — global money flow, risk-on/off regime, safe-haven demand."""
from __future__ import annotations


def _regime(
    gold_up: bool,
    equities_up: bool,
    bonds_up: bool,
) -> str:
    if gold_up and bonds_up and not equities_up:
        return "SAFE_HAVEN_FLIGHT"
    if gold_up and not equities_up:
        return "RISK_OFF"
    if equities_up and not gold_up:
        return "RISK_ON"
    if not gold_up and not equities_up:
        return "RISK_NEUTRAL"
    return "MIXED"


def capital_flow_analysis(
    gold_state: dict,
    equities_state: dict,
    bonds_state: dict | None = None,
) -> dict:
    """
    Determine global capital flow regime from multi-asset trend signals.
    Returns regime, safe-haven demand level, and gold directional bias.
    """
    gold_up = gold_state.get("trend", "NEUTRAL") == "UP"
    equities_up = equities_state.get("trend", "NEUTRAL") == "UP"
    bonds_up = (bonds_state or {}).get("trend", "NEUTRAL") == "UP" if bonds_state else False

    regime = _regime(gold_up, equities_up, bonds_up)

    if regime in ("RISK_OFF", "SAFE_HAVEN_FLIGHT"):
        safe_haven_demand = "HIGH"
    elif regime == "MIXED":
        safe_haven_demand = "MEDIUM"
    else:
        safe_haven_demand = "LOW"

    if regime in ("RISK_OFF", "SAFE_HAVEN_FLIGHT"):
        gold_bias = "BULLISH"
    elif regime == "RISK_ON":
        gold_bias = "BEARISH"
    else:
        gold_bias = "NEUTRAL"

    return {
        "regime": regime,
        "safe_haven_demand": safe_haven_demand,
        "gold_bias": gold_bias,
        "risk_on": equities_up and not gold_up,
        "risk_off": gold_up and not equities_up,
    }


def capital_flow_engine(
    gold: dict,
    equities: dict,
    bonds: dict | None = None,
) -> dict:
    """Main entry point (backward-compatible, now returns full structured dict)."""
    return capital_flow_analysis(gold, equities, bonds)

    return "NEUTRAL"