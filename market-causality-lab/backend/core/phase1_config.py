from __future__ import annotations

import os


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def get_phase1_config() -> dict:
    """Global runtime controls for Phase 1 rollout."""
    profile = str(os.getenv("AQ_PHASE1_PROFILE", "stability")).strip().lower()
    if profile not in {"stability", "performance"}:
        profile = "stability"

    default_news_guard = profile == "stability"
    default_strict_reliability = profile == "stability"

    cfg = {
        "profile": profile,
        "enable_news_guard": _bool_env("AQ_ENABLE_NEWS_GUARD", default_news_guard),
        "enable_decision_trace": _bool_env("AQ_ENABLE_DECISION_TRACE", True),
        "enable_strict_reliability_gate": _bool_env("AQ_ENABLE_STRICT_RELIABILITY_GATE", default_strict_reliability),
        "min_reliability_score": _float_env("AQ_MIN_RELIABILITY_SCORE", 0.62),
    }

    # Clamp reliability threshold into [0,1].
    cfg["min_reliability_score"] = max(0.0, min(1.0, cfg["min_reliability_score"]))
    return cfg