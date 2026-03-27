"""Execution Reality Engine — model real-world entry feasibility and slippage risk."""
from __future__ import annotations

_VOL_THRESHOLDS = {"LOW": 1.0, "MEDIUM": 2.5, "HIGH": 4.0}
_SPREAD_THRESHOLDS = {"LOW": 0.5, "MEDIUM": 1.5, "HIGH": 3.0}


def _vol_risk(vol: float) -> str:
    if vol >= _VOL_THRESHOLDS["HIGH"]:
        return "CRITICAL"
    if vol >= _VOL_THRESHOLDS["MEDIUM"]:
        return "HIGH"
    if vol >= _VOL_THRESHOLDS["LOW"]:
        return "MEDIUM"
    return "LOW"


def _spread_risk(spread: float) -> str:
    if spread >= _SPREAD_THRESHOLDS["HIGH"]:
        return "CRITICAL"
    if spread >= _SPREAD_THRESHOLDS["MEDIUM"]:
        return "HIGH"
    if spread >= _SPREAD_THRESHOLDS["LOW"]:
        return "MEDIUM"
    return "LOW"


def execution_feasibility(state: dict) -> dict:
    """Detailed entry feasibility: spread, slippage, momentum, and liquidity."""
    volatility = float(state.get("volatility", 1.0))
    momentum = float(state.get("momentum", 0.0))
    spread = float(state.get("spread", 0.5))
    volume = float(state.get("volume", 1.0))  # relative volume (1.0 = average)

    vol_risk = _vol_risk(volatility)
    sp_risk = _spread_risk(spread)

    issues: list[str] = []
    score = 100

    if vol_risk in ("HIGH", "CRITICAL"):
        issues.append("HIGH_VOLATILITY_SLIPPAGE")
        score -= 30 if vol_risk == "CRITICAL" else 15

    if sp_risk in ("HIGH", "CRITICAL"):
        issues.append("WIDE_SPREAD")
        score -= 25 if sp_risk == "CRITICAL" else 12

    if abs(momentum) > 5:
        issues.append("FAST_MOVE_ENTRY_RISK")
        score -= 20

    if volume < 0.4:
        issues.append("LOW_LIQUIDITY")
        score -= 15

    score = max(0, score)

    if score >= 80:
        verdict = "OK"
    elif score >= 55:
        verdict = "CAUTION"
    elif score >= 30:
        verdict = "RISKY_ENTRY"
    else:
        verdict = "DO_NOT_ENTER"

    return {
        "verdict": verdict,
        "score": score,
        "volatility_risk": vol_risk,
        "spread_risk": sp_risk,
        "issues": issues if issues else ["NONE"],
        "estimated_slippage": round(volatility * spread * 0.25, 4),
    }


def execution_engine(state: dict) -> dict:
    """Full execution feasibility analysis."""
    return execution_feasibility(state)