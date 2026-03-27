from __future__ import annotations

from typing import Any


OUTPUT_CONTRACT_VERSION = "v1"

_ALLOWED_EXECUTION_VERDICTS = {"OK", "CAUTION", "RISKY_ENTRY", "DO_NOT_ENTER"}
_ALLOWED_FAILURE_STATUS = {"VALID", "CAUTION", "WEAKENED", "INVALIDATED"}
_ALLOWED_SEVERITY = {"NONE", "LOW", "HIGH", "CRITICAL"}
_ALLOWED_REGIMES = {"SAFE_HAVEN_FLIGHT", "RISK_OFF", "RISK_ON", "RISK_NEUTRAL", "MIXED"}
_ALLOWED_DEMAND = {"HIGH", "MEDIUM", "LOW"}
_ALLOWED_GOLD_BIAS = {"BULLISH", "BEARISH", "NEUTRAL"}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        out = [str(v) for v in value if str(v).strip()]
        return out or ["NONE"]
    if value is None:
        return ["NONE"]
    text = str(value).strip()
    return [text] if text else ["NONE"]


def normalize_execution_output(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}

    verdict = str(raw.get("verdict", "CAUTION")).upper()
    if verdict not in _ALLOWED_EXECUTION_VERDICTS:
        verdict = "CAUTION"

    score = max(0.0, min(100.0, _as_float(raw.get("score"), 50.0)))

    return {
        "contract_version": OUTPUT_CONTRACT_VERSION,
        "verdict": verdict,
        "score": round(score, 2),
        "volatility_risk": str(raw.get("volatility_risk", "UNKNOWN")).upper(),
        "spread_risk": str(raw.get("spread_risk", "UNKNOWN")).upper(),
        "issues": _as_list(raw.get("issues")),
        "estimated_slippage": round(max(0.0, _as_float(raw.get("estimated_slippage"), 0.0)), 4),
    }


def normalize_failure_output(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}

    status = str(raw.get("status", "CAUTION")).upper()
    if status not in _ALLOWED_FAILURE_STATUS:
        status = "CAUTION"

    severity = str(raw.get("severity", "LOW")).upper()
    if severity not in _ALLOWED_SEVERITY:
        severity = "LOW"

    invalidated = _as_bool(raw.get("invalidated"), default=(status == "INVALIDATED"))

    return {
        "contract_version": OUTPUT_CONTRACT_VERSION,
        "status": status,
        "severity": severity,
        "issues": _as_list(raw.get("issues")),
        "invalidated": invalidated,
    }


def normalize_capital_flow_output(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}

    regime = str(raw.get("regime", "MIXED")).upper()
    if regime not in _ALLOWED_REGIMES:
        regime = "MIXED"

    safe_haven_demand = str(raw.get("safe_haven_demand", "MEDIUM")).upper()
    if safe_haven_demand not in _ALLOWED_DEMAND:
        safe_haven_demand = "MEDIUM"

    gold_bias = str(raw.get("gold_bias", "NEUTRAL")).upper()
    if gold_bias not in _ALLOWED_GOLD_BIAS:
        gold_bias = "NEUTRAL"

    return {
        "contract_version": OUTPUT_CONTRACT_VERSION,
        "regime": regime,
        "safe_haven_demand": safe_haven_demand,
        "gold_bias": gold_bias,
        "risk_on": _as_bool(raw.get("risk_on"), False),
        "risk_off": _as_bool(raw.get("risk_off"), False),
    }


def output_contract_versions() -> dict[str, str]:
    return {
        "execution": OUTPUT_CONTRACT_VERSION,
        "failure": OUTPUT_CONTRACT_VERSION,
        "capital_flow": OUTPUT_CONTRACT_VERSION,
    }
