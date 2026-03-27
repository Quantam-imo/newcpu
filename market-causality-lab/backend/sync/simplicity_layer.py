"""Simplicity Layer — distil all engine outputs into a single clear bias score."""
from __future__ import annotations

_BIAS_MAP: dict[str, float] = {
    "STRONG BUY": 1.0,
    "BUY": 0.6,
    "WAIT": 0.0,
    "NEUTRAL": 0.0,
    "HOLD": 0.0,
    "SELL": -0.6,
    "STRONG SELL": -1.0,
}

_SENTIMENT_THRESHOLDS = [
    (0.6, "STRONGLY BULLISH"),
    (0.2, "BULLISH"),
    (-0.2, "NEUTRAL"),
    (-0.6, "BEARISH"),
    (-1.01, "STRONGLY BEARISH"),
]


def _signal_bias(signal: str) -> float:
    return _BIAS_MAP.get(str(signal).strip().upper(), 0.0)


def simplicity_score(
    filtered_signal: str,
    confidence: float,
    reliability_score: float,
    conflict_score: float,
    trap: dict,
) -> dict:
    """
    Produce a single [-1, 1] directional bias and 0–100 clarity score.
    These are the two numbers a live UI or alert system needs most.
    """
    direction = _signal_bias(filtered_signal)
    trap_prob = float((trap or {}).get("probability", 0.0) or 0.0)

    # Weight direction by reliability, penalise by conflict and trap probability
    raw = (
        direction
        * max(0.0, reliability_score)
        * (1.0 - 0.30 * max(0.0, conflict_score))
        * (1.0 - 0.20 * trap_prob)
    )
    bias_score = max(-1.0, min(1.0, raw))

    # Clarity: 0 = no idea, 100 = maximum conviction
    clarity = int(round(abs(bias_score) * max(0.0, confidence) * 100.0))
    clarity = max(0, min(100, clarity))

    # Human-readable label
    bias_label = "NEUTRAL"
    for threshold, label in _SENTIMENT_THRESHOLDS:
        if bias_score >= threshold:
            bias_label = label
            break

    conviction = "HIGH" if clarity >= 70 else ("MEDIUM" if clarity >= 40 else "LOW")

    return {
        "bias_score": round(bias_score, 4),
        "bias_label": bias_label,
        "clarity": clarity,
        "conviction": conviction,
        "signal": filtered_signal,
    }
