from __future__ import annotations

from typing import Any

import numpy as np

from backend.ai.decision_engine import ai_decision
from backend.ai.learning_engine import apply_confidence_weight
from backend.ai.modeling.baseline_models import model_from_dict
from backend.ai.modeling.calibration import apply_temperature
from backend.ai.modeling.drift_monitor import evaluate_drift, write_drift_snapshot
from backend.ai.modeling.feature_pipeline import (
    DEFAULT_LABEL_MODE,
    DEFAULT_SETUP_MODE,
    DEFAULT_STOP_RETURN_PCT,
    DEFAULT_TARGET_RETURN_PCT,
    build_dataset_from_memory,
    build_feature_row,
    record_matches_setup,
    standardize_transform,
)
from backend.ai.modeling.registry import load_latest_bundle
from backend.engines.intraday_strategy_engine import evaluate_bar, calculate_position_size


def _decision_from_prob(p_buy: float) -> str:
    return ai_decision({"BUY": float(p_buy), "SELL": float(1.0 - p_buy)})


def _bundle_feature_count(bundle: dict[str, Any] | None) -> int:
    scaler = (bundle or {}).get("scaler") or {}
    return int(len(scaler.get("mean") or []))


def _live_feature_count(memory: list[dict[str, Any]], feature_version: str) -> int:
    x_live = np.array([build_feature_row(memory[-1], feature_version=feature_version)], dtype=float)
    return int(x_live.shape[1]) if x_live.ndim == 2 else 0


def _scope_candidates(memory: list[dict[str, Any]], timeframe: str | None) -> list[str | None]:
    tf = str(timeframe or "").strip().lower() or None
    if not tf:
        return [None]

    trigger = (memory[-1] or {}).get("trigger") or {}
    direction = str(trigger.get("trigger_direction") or "").strip().upper()

    candidates: list[str | None] = []
    if direction == "BUY":
        candidates.append(f"{tf}__buy_trigger_candidate__first_touch_buy")
    elif direction == "SELL":
        candidates.append(f"{tf}__sell_trigger_candidate__first_touch_sell")
    candidates.append(tf)
    candidates.append(None)

    deduped: list[str | None] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _trigger_direction(memory: list[dict[str, Any]]) -> str:
    trigger = (memory[-1] or {}).get("trigger") or {}
    direction = str(trigger.get("trigger_direction") or "WAIT").strip().upper()
    return direction if direction in {"BUY", "SELL"} else "WAIT"


def _bundle_trade_direction(bundle: dict[str, Any] | None) -> str:
    label = str((((bundle or {}).get("label") or {}).get("label_mode") or "")).strip().lower()
    setup = str((((bundle or {}).get("setup") or {}).get("setup_mode") or "")).strip().lower()
    if label.endswith("_buy") or "buy" in setup:
        return "BUY"
    if label.endswith("_sell") or "sell" in setup:
        return "SELL"
    return "WAIT"


def _meta_base(bundle: dict[str, Any] | None, bundle_source: str | None, requested_timeframe: str | None, feature_version: str | None = None) -> dict[str, Any]:
    return {
        "version": (bundle or {}).get("version"),
        "bundle_source": bundle_source,
        "requested_timeframe": requested_timeframe,
        "resolved_model_scope": (bundle or {}).get("model_scope") or (bundle or {}).get("timeframe"),
        "model_timeframe": (bundle or {}).get("timeframe") or (bundle or {}).get("model_scope"),
        "model_dataset_path": (bundle or {}).get("dataset_path"),
        "model_trade_direction": _bundle_trade_direction(bundle),
        "feature_version": feature_version or (bundle or {}).get("feature_version") or "v3_amd_cycle_state",
    }


def _select_compatible_bundle(memory: list[dict[str, Any]], model_scope: str | None) -> tuple[dict[str, Any] | None, str, int, str]:
    last_incompatible: tuple[dict[str, Any], str, int, str] | None = None
    for scope in _scope_candidates(memory, model_scope):
        scoped_bundle = load_latest_bundle(scope=scope)
        if not scoped_bundle:
            continue
        scoped_feature_version = str(scoped_bundle.get("feature_version") or "v3_amd_cycle_state")
        scoped_live_count = _live_feature_count(memory, scoped_feature_version)
        if _bundle_feature_count(scoped_bundle) == scoped_live_count:
            source = "scoped" if scope else "global_fallback"
            if scope and scope != model_scope:
                source = f"{source}:{scope}"
            return scoped_bundle, source, scoped_live_count, scoped_feature_version
        if last_incompatible is None:
            source = "scoped_incompatible" if scope else "global_incompatible"
            if scope and scope != model_scope:
                source = f"{source}:{scope}"
            last_incompatible = (scoped_bundle, source, scoped_live_count, scoped_feature_version)

    global_bundle = load_latest_bundle()
    if global_bundle:
        global_feature_version = str(global_bundle.get("feature_version") or "v3_amd_cycle_state")
        global_live_count = _live_feature_count(memory, global_feature_version)
        if _bundle_feature_count(global_bundle) == global_live_count:
            return global_bundle, "global_fallback", global_live_count, global_feature_version
    if last_incompatible is not None:
        return last_incompatible
    if global_bundle is not None:
        global_feature_version = str(global_bundle.get("feature_version") or "v3_amd_cycle_state")
        return global_bundle, "global_incompatible", _live_feature_count(memory, global_feature_version), global_feature_version
    return None, "missing", 0, "v3_amd_cycle_state"


def decide_with_model(
    memory: list[dict[str, Any]],
    fallback_prob: dict[str, float],
    timeframe: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Return (decision, meta). Uses latest registered model when healthy,
    otherwise falls back to the existing rule decision.
    """
    fallback_decision = ai_decision(fallback_prob)
    live_trigger_direction = _trigger_direction(memory) if memory else "WAIT"

    if not memory:
        return fallback_decision, {
            "used_model": False,
            "reason": "empty_memory",
            "requested_timeframe": str(timeframe or "").strip().lower() or None,
            "trigger_direction": "WAIT",
        }

    model_scope = str(timeframe or "").strip().lower() or None
    bundle, bundle_source, feature_count, feature_version = _select_compatible_bundle(memory, model_scope)
    if not bundle:
        return fallback_decision, {
            "used_model": False,
            "reason": "no_registered_model",
            "requested_timeframe": model_scope,
            "trigger_direction": live_trigger_direction,
        }

    if bundle_source.endswith("incompatible"):
        meta = _meta_base(bundle, bundle_source, model_scope, feature_version)
        meta.update({
            "used_model": False,
            "reason": "no_compatible_model_schema",
            "model_feature_count": _bundle_feature_count(bundle),
            "live_feature_count": feature_count,
            "trigger_direction": live_trigger_direction,
        })
        return fallback_decision, meta

    try:
        x_live = np.array([build_feature_row(memory[-1], feature_version=feature_version)], dtype=float)
        scaler = bundle.get("scaler") or {}
        mean = np.array(scaler.get("mean") or [], dtype=float)
        std = np.array(scaler.get("std") or [], dtype=float)

        best = (bundle.get("best_model") or {})
        model_payload = best.get("serialized") or {}
        model = model_from_dict(model_payload)
        temperature = float(best.get("temperature", 1.0) or 1.0)

        if len(mean) and len(std):
            x_live = standardize_transform(x_live, mean, std)

        raw_p = float(model.predict_proba(x_live)[0])
        p_buy = float(apply_temperature(np.array([raw_p], dtype=float), temperature)[0])
        # Apply per-scope learned confidence weight from trade journal outcomes.
        p_buy = apply_confidence_weight(bundle_source or model_scope or "", p_buy)

        # Drift check on most recent labeled window using the same label contract as training.
        label_meta = bundle.get("label") or {}
        setup_meta = bundle.get("setup") or {}
        setup_mode = str(setup_meta.get("setup_mode") or DEFAULT_SETUP_MODE)
        if not record_matches_setup(memory[-1], setup_mode=setup_mode):
            meta = _meta_base(bundle, bundle_source, model_scope, feature_version)
            meta.update({
                "used_model": False,
                "reason": "setup_not_active",
                "label": label_meta,
                "setup": setup_meta,
                "trigger_direction": live_trigger_direction,
            })
            return fallback_decision, meta
        X_recent, y_recent = build_dataset_from_memory(
            memory[-450:],
            horizon=int(bundle.get("horizon", 1) or 1),
            label_mode=str(label_meta.get("label_mode") or DEFAULT_LABEL_MODE),
            target_return_pct=float(label_meta.get("target_return_pct", DEFAULT_TARGET_RETURN_PCT) or DEFAULT_TARGET_RETURN_PCT),
            stop_return_pct=float(label_meta.get("stop_return_pct", DEFAULT_STOP_RETURN_PCT) or DEFAULT_STOP_RETURN_PCT),
            feature_version=feature_version,
            setup_mode=setup_mode,
        )
        drift_meta = {
            "status": "unknown",
            "drift_detected": False,
            "reason": "insufficient_recent_labels",
        }
        if len(X_recent) >= 80 and len(mean) and len(std):
            X_recent = standardize_transform(X_recent, mean, std)
            p_recent_raw = model.predict_proba(X_recent)
            p_recent = apply_temperature(p_recent_raw, temperature)
            base = bundle.get("validation_metrics") or {}
            drift_meta = evaluate_drift(
                y_true=y_recent,
                p=p_recent,
                baseline_brier=float(base.get("brier", 0.25) or 0.25),
                baseline_accuracy=float(base.get("accuracy", 0.5) or 0.5),
            )
            write_drift_snapshot({
                "version": bundle.get("version"),
                "requested_timeframe": model_scope,
                "model_timeframe": bundle.get("timeframe") or bundle.get("model_scope"),
                "drift": drift_meta,
            })

        if bool(drift_meta.get("drift_detected", False)):
            meta = _meta_base(bundle, bundle_source, model_scope, feature_version)
            meta.update({
                "used_model": False,
                "reason": "drift_guard_fallback",
                "label": label_meta,
                "setup": setup_meta,
                "drift": drift_meta,
                "trigger_direction": live_trigger_direction,
            })
            return fallback_decision, meta

        decision = _decision_from_prob(p_buy)
        meta = _meta_base(bundle, bundle_source, model_scope, feature_version)

        # ── IKZC Strategy Signal ──────────────────────────────────────────────
        strategy_signal = None
        try:
            import pandas as _pd
            bars_raw = [
                {
                    "open":   float((m.get("bar") or {}).get("open", 0)),
                    "high":   float((m.get("bar") or {}).get("high", 0)),
                    "low":    float((m.get("bar") or {}).get("low", 0)),
                    "close":  float((m.get("bar") or {}).get("close", 0)),
                    "volume": float((m.get("bar") or {}).get("volume", 0)),
                }
                for m in memory[-60:]
                if (m.get("bar") or {}).get("close")
            ]
            if bars_raw:
                bars_df = _pd.DataFrame(bars_raw)
                sig = evaluate_bar(memory[-1], p_buy, bars_df)
                if sig is not None:
                    strategy_signal = {
                        "active":          True,
                        "direction":       sig.direction,
                        "entry":           sig.entry_price,
                        "stop":            sig.stop_price,
                        "tp1":             sig.tp1_price,
                        "tp2":             sig.tp2_price,
                        "risk_points":     sig.risk_points,
                        "rr_ratio":        sig.rr_ratio,
                        "kill_zone":       sig.kill_zone,
                        "model_prob":      sig.model_prob,
                        "ict_score":       sig.ict_score,
                        "ict_concepts":    sig.ict_concepts,
                        "pd_position_pct": sig.pd_position_pct,
                        "active_signals":  sig.active_signals,
                        "confidence":      sig.confidence_score,
                        "notes":           sig.notes,
                        "position_sizing": calculate_position_size(
                            account_balance=10000.0,
                            stop_distance=sig.risk_points,
                        ),
                    }
        except Exception:
            pass
        # ─────────────────────────────────────────────────────────────────────

        meta.update({
            "used_model": True,
            "model_name": (best.get("name") or model_payload.get("name") or "unknown"),
            "label": label_meta,
            "setup": setup_meta,
            "p_buy": round(p_buy, 6),
            "p_sell": round(1.0 - p_buy, 6),
            "drift": drift_meta,
            "trigger_direction": live_trigger_direction,
            "strategy_signal": strategy_signal,
        })
        return decision, meta
    except Exception as exc:
        meta = _meta_base(bundle, bundle_source, model_scope, bundle.get("feature_version") or "v3_amd_cycle_state")
        meta.update({
            "used_model": False,
            "reason": f"model_runtime_error: {exc}",
            "label": bundle.get("label") or {},
            "setup": bundle.get("setup") or {},
            "trigger_direction": live_trigger_direction,
        })
        return fallback_decision, meta
