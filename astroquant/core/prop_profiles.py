from __future__ import annotations

from copy import deepcopy

PROP_PROFILES = {
    "5K": {
        "account_size": 5000,
        "phase1_target_pct": 8.0,
        "phase2_target_pct": 5.0,
        "max_dd_pct": 8.0,
        "daily_dd_pct": 4.0,
        "phase1_risk": 0.8,
        "phase2_risk": 0.6,
        "funded_risk": 0.4,
    },
    "10K": {
        "account_size": 10000,
        "phase1_target_pct": 8.0,
        "phase2_target_pct": 5.0,
        "max_dd_pct": 8.0,
        "daily_dd_pct": 4.0,
        "phase1_risk": 0.7,
        "phase2_risk": 0.5,
        "funded_risk": 0.4,
    },
    "20K": {
        "account_size": 20000,
        "phase1_target_pct": 8.0,
        "phase2_target_pct": 5.0,
        "max_dd_pct": 8.0,
        "daily_dd_pct": 4.0,
        "phase1_risk": 0.6,
        "phase2_risk": 0.5,
        "funded_risk": 0.4,
    },
    "50K": {
        "account_size": 50000,
        "phase1_target_pct": 8.0,
        "phase2_target_pct": 5.0,
        "max_dd_pct": 8.0,
        "daily_dd_pct": 4.0,
        "phase1_risk": 0.5,
        "phase2_risk": 0.4,
        "funded_risk": 0.3,
    },
    "100K": {
        "account_size": 100000,
        "phase1_target_pct": 8.0,
        "phase2_target_pct": 5.0,
        "max_dd_pct": 8.0,
        "daily_dd_pct": 4.0,
        "phase1_risk": 0.4,
        "phase2_risk": 0.3,
        "funded_risk": 0.25,
    },
}

MODE_PROFILES = {
    "STANDARD": {
        "risk_multiplier": 1.0,
        "daily_dd_multiplier": 1.0,
        "max_dd_multiplier": 1.0,
        "confidence_shift": 0.0,
        "clawbot": {
            "consecutive_loss_defensive": 2,
            "consecutive_loss_halt": 3,
            "spread_defensive": 2.2,
            "spread_halt": 2.8,
            "slippage_halt": 1.2,
        },
    },
    "STRICT": {
        "risk_multiplier": 0.8,
        "daily_dd_multiplier": 0.85,
        "max_dd_multiplier": 0.9,
        "confidence_shift": 2.0,
        "clawbot": {
            "consecutive_loss_defensive": 2,
            "consecutive_loss_halt": 3,
            "spread_defensive": 1.8,
            "spread_halt": 2.3,
            "slippage_halt": 0.9,
        },
    },
    "AGGRESSIVE": {
        "risk_multiplier": 1.15,
        "daily_dd_multiplier": 1.1,
        "max_dd_multiplier": 1.05,
        "confidence_shift": -2.0,
        "clawbot": {
            "consecutive_loss_defensive": 2,
            "consecutive_loss_halt": 3,
            "spread_defensive": 2.5,
            "spread_halt": 3.1,
            "slippage_halt": 1.35,
        },
    },
}


def supported_account_keys() -> list[str]:
    return list(PROP_PROFILES.keys())


def supported_modes() -> list[str]:
    return list(MODE_PROFILES.keys())


def normalize_account_key(account_key: str | None, fallback: str = "50K") -> str:
    key = str(account_key or fallback).upper().strip()
    if key in PROP_PROFILES:
        return key
    return fallback if fallback in PROP_PROFILES else "50K"


def normalize_mode(mode: str | None, fallback: str = "STANDARD") -> str:
    key = str(mode or fallback).upper().strip()
    if key in MODE_PROFILES:
        return key
    return fallback if fallback in MODE_PROFILES else "STANDARD"


def profile_for(account_key: str | None, mode: str | None = "STANDARD") -> dict:
    account = normalize_account_key(account_key)
    strategy_mode = normalize_mode(mode)

    base = deepcopy(PROP_PROFILES[account])
    mode_cfg = MODE_PROFILES[strategy_mode]

    risk_mult = float(mode_cfg.get("risk_multiplier", 1.0))
    daily_mult = float(mode_cfg.get("daily_dd_multiplier", 1.0))
    max_mult = float(mode_cfg.get("max_dd_multiplier", 1.0))

    phase1_risk = max(0.1, min(2.0, float(base["phase1_risk"]) * risk_mult))
    phase2_risk = max(0.1, min(2.0, float(base["phase2_risk"]) * risk_mult))
    funded_risk = max(0.1, min(2.0, float(base["funded_risk"]) * risk_mult))

    daily_dd_pct = max(0.5, min(20.0, float(base["daily_dd_pct"]) * daily_mult))
    max_dd_pct = max(1.0, min(50.0, float(base["max_dd_pct"]) * max_mult))

    account_size = float(base["account_size"])
    phase1_target_pct = float(base["phase1_target_pct"])
    phase2_target_pct = float(base["phase2_target_pct"])

    return {
        "account_key": account,
        "mode": strategy_mode,
        "account_size": account_size,
        "phase1_target_pct": phase1_target_pct,
        "phase2_target_pct": phase2_target_pct,
        "max_dd_pct": max_dd_pct,
        "daily_dd_pct": daily_dd_pct,
        "phase1_risk": phase1_risk,
        "phase2_risk": phase2_risk,
        "funded_risk": funded_risk,
        "confidence_shift": float(mode_cfg.get("confidence_shift", 0.0)),
        "daily_max_loss": round(account_size * (daily_dd_pct / 100.0), 2),
        "total_max_loss": round(account_size * (max_dd_pct / 100.0), 2),
        "phase1_target": round(account_size * (phase1_target_pct / 100.0), 2),
        "phase2_target": round(account_size * (phase2_target_pct / 100.0), 2),
        "clawbot": deepcopy(mode_cfg.get("clawbot", {})),
    }


def profile_risk_pct(profile: dict, phase: str | None) -> float:
    phase_key = str(phase or "PHASE1").upper().strip()
    if phase_key == "PHASE2":
        return float(profile.get("phase2_risk", 0.5)) / 100.0
    if phase_key == "FUNDED":
        return float(profile.get("funded_risk", 0.4)) / 100.0
    return float(profile.get("phase1_risk", 0.6)) / 100.0
