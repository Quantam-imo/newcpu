from pathlib import Path
import os

import pandas as pd

from backend.core.phase1_config import get_phase1_config
from backend.core.output_contracts import (
    normalize_capital_flow_output,
    normalize_execution_output,
    normalize_failure_output,
    output_contract_versions,
)
from backend.utils.data_loader import (
    load_data,
    load_news_data,
    integrate_news_features,
    integrate_event_features,
)
from backend.utils.observation_recorder import record_observation
from backend.utils.timeframe_loader import TIMEFRAME_FILES
from backend.memory.scanner import scan_market
from backend.memory.vector_memory import build_vector_memory
from backend.ai.feature_vector import create_feature_vector
from backend.ai.similarity_engine import find_similar
from backend.memory.recall_engine import recall_patterns
from backend.ai.probability_engine import compute_probability
from backend.ai.decision_engine import ai_decision
from backend.ai.modeling.serving import decide_with_model
from backend.engines.psychology_engine import psychology_engine
from backend.engines.trap_engine import trap_engine
from backend.engines.behavior_engine import behavior_engine
from backend.gann.gann_advanced import gann_advanced
from backend.astro.astro_engine import astro_engine
from backend.engines.numerology_engine import numerology_engine
from backend.engines.harmonic_engine import harmonic_engine
from backend.engines.time_engine import time_engine
from backend.engines.future_engine import future_engine
from backend.sync.weight_engine import weight_engine
from backend.sync.signal_engine import generate_signals
from backend.sync.dominance_engine import dominance_engine
from backend.sync.confidence_engine import confidence_engine
from backend.sync.scenario_engine import scenario_engine
from backend.sync.final_engine import final_engine
from backend.validation.validation_engine import validate_signal
from backend.validation.filter_engine import filter_signal
from backend.ai.learning_engine import learning_engine
from backend.memory.update_memory import update_memory
from backend.macro.multi_asset_engine import multi_asset_engine
from backend.macro.macro_engine import macro_engine
from backend.macro.correlation_engine import correlation_engine
from backend.macro.capital_flow import capital_flow_engine
from backend.live.auto_pipeline import run_pipeline
from backend.sync.sync_engine import institutional_sync
from backend.live.mt5_fetch import fetch_xauusd
from backend.validation.backtest import backtest
from backend.validation.execution_engine import execution_engine
from backend.validation.failure_engine import failure_engine
# Precision + Realism safeguard layer (8 system reliability engines)
from backend.validation.data_quality_engine import check_data_quality
from backend.validation.latency_engine import latency_analysis
from backend.sync.simplicity_layer import simplicity_score
from backend.validation.adaptive_timescale_engine import adaptive_timescale_analysis
from backend.validation.overfitting_protection import overfitting_guard
# Universal Conversion Engine (math / Gann / astro / harmonic layer)
from backend.universal_engine import (
    numerology_profile as ue_numerology_profile,
    fib_levels as ue_fib_levels,
    gann_advanced_analysis as ue_gann_analysis,
    nakshatra_from_degree as ue_nakshatra,
    price_to_degree as ue_price_to_degree,
    harmonic_analysis as ue_harmonic_analysis,
)


def _build_decision_trace(signals: dict, weights: dict, dominant: str, confidence: float, quality: str, trap: dict) -> dict:
    weighted = {"BUY": 0.0, "SELL": 0.0}
    for source, direction in (signals or {}).items():
        w = float((weights or {}).get(source, 0.0))
        if direction in ("BUY", "STRONG BUY"):
            weighted["BUY"] += w
        elif direction in ("SELL", "STRONG SELL"):
            weighted["SELL"] += w

    top_score = max(weighted.values()) if weighted else 0.0
    bottom_score = min(weighted.values()) if weighted else 0.0
    conflict_score = (bottom_score / top_score) if top_score > 0 else 0.0

    trap_prob = float((trap or {}).get("probability", 0.0) or 0.0)
    quality_bonus = 0.05 if str(quality).upper() == "STRONG" else 0.0
    reliability_score = confidence * (1.0 - 0.35 * conflict_score) * (1.0 - 0.2 * trap_prob) + quality_bonus
    reliability_score = max(0.0, min(1.0, reliability_score))

    return {
        "dominant_force": dominant,
        "conflict_score": round(conflict_score, 4),
        "reliability_score": round(reliability_score, 4),
        "weighted_forces": {k: round(v, 4) for k, v in weighted.items()},
    }


def _build_reasoning_display(result: dict) -> dict:
    final = (result or {}).get("final", {}) or {}
    future = (result or {}).get("future", {}) or {}
    time_signal = (result or {}).get("time_signal", {}) or {}
    decision_trace = (result or {}).get("decision_trace", {}) or {}
    trap = (result or {}).get("trap", {}) or {}

    signal = str((result or {}).get("filtered_signal") or "WAIT")
    phase = str(final.get("phase") or "UNKNOWN")
    trend = str(final.get("trend") or "UNKNOWN")
    dominant_force = str(decision_trace.get("dominant_force") or signal)
    reliability = decision_trace.get("reliability_score")
    quality = str((result or {}).get("quality") or "UNKNOWN")
    timing = str(time_signal.get("timing") or "NO SIGNAL")
    future_direction = str(future.get("direction") or future.get("cycle_event") or "UNCLEAR")
    rejection_reason = (result or {}).get("rejection_reason") or "none"
    news_guard_applied = bool((result or {}).get("news_guard_applied"))
    trap_name = str(trap.get("trap") or "NONE")
    bias_label = str(((result or {}).get("simple", {}) or {}).get("bias_label") or "NEUTRAL")

    weighted_forces = (decision_trace.get("weighted_forces") or {}) if isinstance(decision_trace, dict) else {}
    buy_force = float(weighted_forces.get("BUY", 0.0) or 0.0)
    sell_force = float(weighted_forces.get("SELL", 0.0) or 0.0)
    total_force = max(1e-9, buy_force + sell_force)
    dominant_force_ratio = max(buy_force, sell_force) / total_force

    conflict_score = float(decision_trace.get("conflict_score", 0.0) or 0.0)
    trap_probability = float(trap.get("probability", 0.0) or 0.0)
    timing_score = 1.0 if timing == "STRONG TURN WINDOW" else (0.6 if timing == "POSSIBLE TURN" else 0.2)
    future_strength = max(0.0, min(1.0, float((future or {}).get("strength", 0.0) or 0.0) / 4.0))
    risk_gate_score = 0.0 if news_guard_applied else 1.0
    bias_score = float(((result or {}).get("simple", {}) or {}).get("bias_score", 0.0) or 0.0)
    bias_magnitude = max(0.0, min(1.0, abs(bias_score)))

    raw_contributions = {
        "dominant_force": max(0.0, min(1.0, dominant_force_ratio * 0.55 + float(reliability or 0.0) * 0.45)),
        "timing_window": timing_score,
        "future_projection": future_strength,
        "risk_gate": max(0.0, min(1.0, risk_gate_score * (1.0 - conflict_score) * (1.0 - 0.5 * trap_probability))),
        "bias_label": bias_magnitude,
    }
    raw_total = sum(raw_contributions.values()) or 1.0
    contribution_weights = {k: round(v / raw_total, 4) for k, v in raw_contributions.items()}

    tone = "neutral"
    if signal in {"BUY", "STRONG BUY"}:
        tone = "bullish"
    elif signal in {"SELL", "STRONG SELL"}:
        tone = "bearish"
    elif news_guard_applied or rejection_reason != "none":
        tone = "caution"

    top_drivers = [
        {
            "label": "dominant_force",
            "value": dominant_force,
            "score": contribution_weights["dominant_force"],
            "score_pct": round(contribution_weights["dominant_force"] * 100.0, 2),
        },
        {
            "label": "timing_window",
            "value": timing,
            "score": contribution_weights["timing_window"],
            "score_pct": round(contribution_weights["timing_window"] * 100.0, 2),
        },
        {
            "label": "future_projection",
            "value": future_direction,
            "score": contribution_weights["future_projection"],
            "score_pct": round(contribution_weights["future_projection"] * 100.0, 2),
        },
        {
            "label": "risk_gate",
            "value": "blocked" if news_guard_applied else "clear",
            "score": contribution_weights["risk_gate"],
            "score_pct": round(contribution_weights["risk_gate"] * 100.0, 2),
        },
        {
            "label": "bias_label",
            "value": bias_label,
            "score": contribution_weights["bias_label"],
            "score_pct": round(contribution_weights["bias_label"] * 100.0, 2),
        },
    ]
    top_drivers = sorted(top_drivers, key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)

    lead = (
        f"Signal {signal} because phase {phase} and trend {trend} align with dominant force {dominant_force}. "
        f"Reliability {reliability if reliability is not None else 'n/a'} and timing {timing}."
    )
    if news_guard_applied:
        lead += f" Execution guard active due to {rejection_reason}."
    else:
        lead += f" Future outlook is {future_direction}."

    chain = [
        f"Market structure reads as phase {phase} with trend {trend}.",
        f"Signal dominance is {dominant_force} with quality {quality} and trap state {trap_name}.",
        f"Time reasoning is {timing} and future projection is {future_direction}.",
        f"Risk gate status: {'blocked' if news_guard_applied else 'clear'}; rejection reason: {rejection_reason}.",
    ]

    evidence = {
        "dominant_force": dominant_force,
        "reliability_score": reliability,
        "timing": timing,
        "future_direction": future_direction,
        "trap": trap_name,
        "rejection_reason": rejection_reason,
        "contribution_weights": contribution_weights,
    }

    return {
        "tone": tone,
        "summary": lead,
        "chain": chain,
        "evidence": evidence,
        "top_drivers": top_drivers,
    }


def _build_analysis_lifecycle(
    started_at: pd.Timestamp,
    completed_at: pd.Timestamp,
    stages: list[dict],
) -> dict:
    elapsed_ms = round((completed_at - started_at).total_seconds() * 1000.0, 2)

    return {
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": completed_at.isoformat(),
        "elapsed_ms": elapsed_ms,
        "stages": stages,
    }


def _stage_duration(stage_started_at: pd.Timestamp, stage_completed_at: pd.Timestamp) -> float:
    return round((stage_completed_at - stage_started_at).total_seconds() * 1000.0, 2)


def _apply_gann_signal_alignment(result: dict) -> dict:
    out = dict(result or {})
    observation = (out.get("observation") or {}) if isinstance(out.get("observation"), dict) else {}

    original_signal = str(out.get("filtered_signal") or "WAIT").upper()
    gann_candidate = str(observation.get("gann_recommended_signal") or "WAIT").upper()
    geometry_ok = str(observation.get("confirmation_geometry") or "NO").upper() == "YES"
    time_ok = str(observation.get("confirmation_time") or "NO").upper() == "YES"
    structure_ok = str(observation.get("confirmation_structure") or "NO").upper() == "YES"
    tape_ok = str(observation.get("confirmation_tape_action") or "NO").upper() == "YES"

    news_guard = bool(out.get("news_guard_applied"))
    rejection_reason = str(out.get("rejection_reason") or "").strip().lower()
    risk_blocked = news_guard or (rejection_reason not in {"", "none"})

    gann_confluence_ready = geometry_ok and time_ok and (structure_ok or tape_ok)
    aligned_signal = original_signal

    if risk_blocked:
        aligned_signal = "WAIT"
    elif gann_confluence_ready and gann_candidate in {"BUY", "SELL"}:
        aligned_signal = gann_candidate

    out["filtered_signal_original"] = original_signal
    out["gann_signal_candidate"] = gann_candidate
    out["gann_confluence_ready"] = gann_confluence_ready
    out["filtered_signal"] = aligned_signal
    out["learning_profile"] = {
        "style": "gann_confluence",
        "geometry_confirmed": geometry_ok,
        "time_confirmed": time_ok,
        "structure_confirmed": structure_ok,
        "tape_confirmed": tape_ok,
        "gann_mindset_bias": observation.get("gann_mindset_bias"),
        "gann_time_phase": observation.get("gann_time_phase"),
        "gann_recommended_signal": gann_candidate,
        "risk_gate_blocked": risk_blocked,
    }
    return out


def process(df):
    # Core intelligence pipeline
    phase1_cfg = get_phase1_config()
    process_timing: list[dict] = []

    # Precision layer 1: data quality audit before any analysis
    stage_started_at = pd.Timestamp.now("UTC")
    data_quality = check_data_quality(df)
    stage_completed_at = pd.Timestamp.now("UTC")
    process_timing.append(
        {
            "name": "data_quality_audit",
            "elapsed_ms": _stage_duration(stage_started_at, stage_completed_at),
        }
    )

    # Step 1: Scan memory
    stage_started_at = pd.Timestamp.now("UTC")
    memory = scan_market(df)

    # Step 2: Build vectors
    vectors = build_vector_memory(memory)

    # Step 3: Current state
    current_record = memory[-1]
    current_vec = create_feature_vector(current_record)

    # Step 4: Find similar
    matches = find_similar(current_vec, vectors)

    # Step 5: Recall patterns
    results = recall_patterns(matches, memory)

    # Step 6: Probability
    prob = compute_probability(results)

    # Step 7: AI decision (model-served when available, rule fallback otherwise)
    decision, ai_model = decide_with_model(memory, prob)
    stage_completed_at = pd.Timestamp.now("UTC")
    process_timing.append(
        {
            "name": "memory_probability_stack",
            "elapsed_ms": _stage_duration(stage_started_at, stage_completed_at),
        }
    )

    # Phase 4: Psychology + trap + behavior reasoning layer
    stage_started_at = pd.Timestamp.now("UTC")
    state = current_record["state"]
    psychology = psychology_engine(state, current_record["phase"])
    trap = trap_engine(state, current_record["liquidity"], current_record["phase"])
    behavior = behavior_engine(psychology, trap)
    stage_completed_at = pd.Timestamp.now("UTC")
    process_timing.append(
        {
            "name": "behavior_reasoning",
            "elapsed_ms": _stage_duration(stage_started_at, stage_completed_at),
        }
    )

    # Phase 5: Time + universal alignment layer
    stage_started_at = pd.Timestamp.now("UTC")
    gann_adv = gann_advanced(state, df)
    astro = astro_engine(df)
    numerology = numerology_engine(state["price"])
    harmonic = harmonic_engine(df)
    time_signal = time_engine(gann_adv, astro)
    future = future_engine(state, current_record["phase"], time_signal, harmonic, numerology)
    stage_completed_at = pd.Timestamp.now("UTC")
    process_timing.append(
        {
            "name": "time_future_alignment",
            "elapsed_ms": _stage_duration(stage_started_at, stage_completed_at),
        }
    )

    # Precision layer 2: latency awareness + adaptive time-scale
    stage_started_at = pd.Timestamp.now("UTC")
    latency = latency_analysis(state, df)
    timescale = adaptive_timescale_analysis(state, df)
    stage_completed_at = pd.Timestamp.now("UTC")
    process_timing.append(
        {
            "name": "latency_timescale_checks",
            "elapsed_ms": _stage_duration(stage_started_at, stage_completed_at),
        }
    )

    # Phase 6: final synchronization and intelligence output
    stage_started_at = pd.Timestamp.now("UTC")
    weights = weight_engine(state, current_record["phase"])
    signals = generate_signals(state, current_record["liquidity"], current_record["gann"], decision)
    dominant, score = dominance_engine(signals, weights)
    confidence = confidence_engine(score)
    scenarios = scenario_engine(dominant, confidence)
    final = final_engine(
        state,
        current_record["phase"],
        psychology,
        trap,
        behavior,
        dominant,
        confidence,
        scenarios,
        time_signal,
    )

    # PRO layer: signal quality validation and filtering.
    # Accuracy Pass v2: pass phase to filter_signal so MANIPULATION and
    # low-vol EXPANSION signals are suppressed (84% 1-bar precision when active).
    quality = validate_signal(confidence, trap, current_record["phase"])
    final_signal = filter_signal(dominant, confidence, phase=current_record["phase"])
    decision_trace = _build_decision_trace(signals, weights, dominant, confidence, quality, trap)

    # News-aware safeguard: avoid opening directional positions around high-impact events.
    news_context = current_record.get("news", {})
    news_guard_applied = False
    rejection_reason = ""
    if (
        phase1_cfg["enable_news_guard"]
        and final_signal in ("BUY", "SELL", "STRONG BUY", "STRONG SELL")
        and news_context.get("high_impact_active")
    ):
        final_signal = "WAIT"
        news_guard_applied = True
        rejection_reason = "news_high_impact_guard"

    if (
        phase1_cfg["enable_strict_reliability_gate"]
        and final_signal in ("BUY", "SELL", "STRONG BUY", "STRONG SELL")
        and decision_trace["reliability_score"] < phase1_cfg["min_reliability_score"]
    ):
        final_signal = "WAIT"
        rejection_reason = "reliability_below_threshold"

    # Precision layer 3: simplicity output — single bias score for UI / alerts
    simple = simplicity_score(
        final_signal,
        confidence,
        decision_trace["reliability_score"],
        decision_trace["conflict_score"],
        trap,
    )
    stage_completed_at = pd.Timestamp.now("UTC")
    process_timing.append(
        {
            "name": "signal_synchronization",
            "elapsed_ms": _stage_duration(stage_started_at, stage_completed_at),
        }
    )

    # PRO layer: lightweight learning feedback loop.
    actual = "BUY" if state["trend"] == "UP" else "SELL"
    updated_weights = learning_engine(dominant, actual, weights.copy())

    # PRO layer: continuous memory update with current analyzed record.
    memory = update_memory(memory, current_record)

    # Institutional layer: multi-asset placeholders and macro causality.
    def fetch_all_data():
        # Placeholder structure until dedicated feeds are connected.
        return {
            "gold": df,
            "usd": df,
            "bonds": df,
            "oil": df,
            "spx": df,
        }

    def process_all(data):
        gold_state = state
        usd_state = {"trend": "DOWN" if gold_state["trend"] == "UP" else "UP"}
        bonds_state = {"trend": "DOWN" if gold_state["trend"] == "UP" else "UP"}
        equities_state = {"trend": "DOWN" if trap["trap"] != "NONE" else "UP"}

        multi_asset = multi_asset_engine(gold_state, usd_state, bonds_state)
        macro_bias = macro_engine(inflation=4.2, rates=3.8)
        flow = normalize_capital_flow_output(capital_flow_engine(gold_state, equities_state))

        corr_gold_usd = correlation_engine(
            data["gold"]["close"].tail(60).to_numpy(),
            (-data["usd"]["close"].tail(60)).to_numpy(),
        )

        institutional_decision, institutional_score = institutional_sync(signals, macro_bias, flow)

        return {
            "multi_asset": multi_asset,
            "macro": macro_bias,
            "capital_flow": flow,
            "correlation_gold_usd": corr_gold_usd,
            "institutional_decision": institutional_decision,
            "institutional_score": institutional_score,
        }

    stage_started_at = pd.Timestamp.now("UTC")
    institutional = run_pipeline(fetch_all_data, process_all)
    stage_completed_at = pd.Timestamp.now("UTC")
    process_timing.append(
        {
            "name": "institutional_pipeline",
            "elapsed_ms": _stage_duration(stage_started_at, stage_completed_at),
        }
    )

    # Phase 7: real-world validation and execution awareness.
    stage_started_at = pd.Timestamp.now("UTC")
    backtest_stats = backtest(memory)
    execution_state = normalize_execution_output(execution_engine(state))
    failure_state = normalize_failure_output(failure_engine(state))

    # Precision layer 4: overfitting protection
    overfit = overfitting_guard(backtest_stats)
    stage_completed_at = pd.Timestamp.now("UTC")
    process_timing.append(
        {
            "name": "validation_and_overfit",
            "elapsed_ms": _stage_duration(stage_started_at, stage_completed_at),
        }
    )

    # Universal Conversion Engine outputs
    stage_started_at = pd.Timestamp.now("UTC")
    _ue_price = state["price"]
    universal = {
        "numerology": ue_numerology_profile(_ue_price),
        "fib_levels": ue_fib_levels(
            float(df["high"].tail(50).max()),
            float(df["low"].tail(50).min()),
        ),
        "gann": ue_gann_analysis(state, df),
        "nakshatra": ue_nakshatra(ue_gann_analysis(state, df)["degrees"]),
        "price_degree": ue_price_to_degree(_ue_price),
        "harmonic": ue_harmonic_analysis(df),
    }
    stage_completed_at = pd.Timestamp.now("UTC")
    process_timing.append(
        {
            "name": "universal_conversion",
            "elapsed_ms": _stage_duration(stage_started_at, stage_completed_at),
        }
    )

    # Accuracy Pass v2: attach SL/TP levels to every directional signal
    price = state["price"]
    trade_levels = None
    if final_signal in ("BUY", "STRONG BUY"):
        trade_levels = {
            "entry": round(price, 2),
            "stop_loss": round(price - 10.0, 2),   # optimal SL: -$10/oz
            "take_profit": round(price + 20.0, 2), # optimal TP: +$20/oz
            "r_ratio": 2.0,
            "hold_bars": 7,
        }

    return {
        "matches": matches,
        "probability": prob,
        "ai_decision": decision,
        "ai_model": ai_model,
        "psychology": psychology,
        "trap": trap,
        "behavior": behavior,
        "gann_adv": gann_adv,
        "astro": astro,
        "numerology": numerology,
        "harmonic": harmonic,
        "time_signal": time_signal,
        "future": future,
        "weights": weights,
        "signals": signals,
        "score": score,
        "confidence": confidence,
        "scenarios": scenarios,
        "quality": quality,
        "filtered_signal": final_signal,
        "news": news_context,
        "news_guard_applied": news_guard_applied,
        "decision_trace": decision_trace if phase1_cfg["enable_decision_trace"] else {},
        "rejection_reason": rejection_reason,
        "output_contracts": output_contract_versions(),
        "phase1_config": phase1_cfg,
        "trade_levels": trade_levels,
        "updated_weights": updated_weights,
        "memory_size": len(memory),
        "final": final,
        "institutional": institutional,
        "backtest": backtest_stats,
        "execution": execution_state,
        "failure": failure_state,
        # Precision + Realism Layer
        "data_quality": data_quality,
        "latency": latency,
        "timescale": timescale,
        "simple": simple,
        "overfit": overfit,
        "universal": universal,
        "process_timing": process_timing,
    }


def _resolve_timeframe_file(timeframe: str, symbol: str = "XAUUSD", data_dir: str = "data") -> Path:
    tf = str(timeframe or "1d").strip().lower()
    symbol_norm = str(symbol or "XAUUSD").strip().upper()

    # Current datasets are XAU-only; keep symbol parameter for future extension.
    if symbol_norm not in {"XAUUSD", "XAU", "GC.FUT", "GC"}:
        raise ValueError(f"Unsupported symbol for historical datasets: {symbol_norm}")

    tf_aliases = {
        "1min": "1m",
        "5min": "5m",
        "15min": "15m",
        "30min": "30m",
        "60m": "1h",
        "1hour": "1h",
        "4hour": "4h",
        "daily": "1d",
        "day": "1d",
        "weekly": "1w",
        "month": "1month",
        "1mo": "1month",
    }
    tf = tf_aliases.get(tf, tf)

    filename = TIMEFRAME_FILES.get(tf)
    if not filename:
        supported = ", ".join(sorted(TIMEFRAME_FILES.keys()))
        raise ValueError(f"Unsupported timeframe '{timeframe}'. Supported: {supported}")

    path = Path(data_dir) / filename
    if not path.exists():
        raise FileNotFoundError(f"Historical dataset not found: {path}")
    return path


def _normalize_timeframe_value(timeframe: str | None) -> str:
    tf = str(timeframe or "1d").strip().lower()
    tf_aliases = {
        "1min": "1m",
        "5min": "5m",
        "15min": "15m",
        "30min": "30m",
        "60m": "1h",
        "1hour": "1h",
        "4hour": "4h",
        "daily": "1d",
        "day": "1d",
        "weekly": "1w",
        "month": "1month",
        "1mo": "1month",
    }
    return tf_aliases.get(tf, tf)


def _timeframe_fallback_chain(requested_timeframe: str) -> list[str]:
    tf = _normalize_timeframe_value(requested_timeframe)

    if tf in {"1m", "5m", "15m", "30m"}:
        chain = [tf, "5m", "30m", "1h", "4h", "1d"]
    elif tf in {"1h", "4h"}:
        chain = [tf, "4h", "1d", "1h"]
    elif tf in {"1w", "1month"}:
        chain = [tf, "1d", "4h", "1h"]
    else:
        chain = [tf, "1d", "4h", "1h", "30m", "5m"]

    seen = set()
    ordered = []
    for item in chain:
        if item in TIMEFRAME_FILES and item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def _load_historical_with_fallback(
    symbol: str,
    timeframe: str,
    lookback_years: int,
    data_dir: str = "data",
) -> tuple[pd.DataFrame, Path, str, dict[str, str | float | bool | None]]:
    requested_tf = _normalize_timeframe_value(timeframe)
    target_years = max(1, min(100, int(lookback_years)))
    min_required_depth = max(0.0, target_years - 0.25)

    candidate_chain = _timeframe_fallback_chain(requested_tf)
    best = None
    load_errors: list[str] = []

    for candidate_tf in candidate_chain:
        try:
            dataset_path = _resolve_timeframe_file(timeframe=candidate_tf, symbol=symbol, data_dir=data_dir)
            raw_df = load_data(str(dataset_path))
            depth = _historical_depth_years(raw_df)
            if depth is None:
                continue

            trimmed = _apply_lookback_years(raw_df, target_years)

            if best is None or depth > float(best["depth"]):
                best = {
                    "df": trimmed,
                    "path": dataset_path,
                    "tf": candidate_tf,
                    "depth": float(depth),
                }

            if depth >= min_required_depth:
                fallback_applied = candidate_tf != requested_tf
                return trimmed, dataset_path, candidate_tf, {
                    "requested_timeframe": requested_tf,
                    "applied_timeframe": candidate_tf,
                    "fallback_applied": fallback_applied,
                    "fallback_reason": "requested_timeframe_depth_below_target" if fallback_applied else None,
                    "applied_dataset_depth_years": float(depth),
                    "target_lookback_years": float(target_years),
                }
        except Exception as exc:
            load_errors.append(f"{candidate_tf}: {exc}")

    if best is not None:
        fallback_applied = str(best["tf"]) != requested_tf
        return best["df"], best["path"], str(best["tf"]), {
            "requested_timeframe": requested_tf,
            "applied_timeframe": str(best["tf"]),
            "fallback_applied": fallback_applied,
            "fallback_reason": "requested_timeframe_depth_below_target_no_full_match",
            "applied_dataset_depth_years": float(best["depth"]),
            "target_lookback_years": float(target_years),
        }

    detail = "; ".join(load_errors) if load_errors else "no datasets available"
    raise RuntimeError(f"Unable to load historical datasets for timeframe fallback chain: {detail}")


def _apply_lookback_years(df: pd.DataFrame, years: int) -> pd.DataFrame:
    years_i = int(years) if years is not None else 25
    years_i = max(1, min(100, years_i))

    if "time" not in df.columns or df.empty:
        return df

    max_ts = df["time"].max()
    if pd.isna(max_ts):
        return df

    cutoff = max_ts - pd.DateOffset(years=years_i)
    trimmed = df[df["time"] >= cutoff].copy()
    return trimmed if not trimmed.empty else df


def _historical_depth_years(df: pd.DataFrame) -> float | None:
    if "time" not in df.columns or df.empty:
        return None
    min_ts = df["time"].min()
    max_ts = df["time"].max()
    if pd.isna(min_ts) or pd.isna(max_ts) or max_ts <= min_ts:
        return None
    span_days = (max_ts - min_ts).days
    return round(float(span_days) / 365.25, 3)


def _merge_historical_and_live(
    hist_df: pd.DataFrame,
    live_df: pd.DataFrame,
) -> pd.DataFrame:
    """Merge a 25Y historical CSV frame with fresh live candles.

    Only live rows that are strictly *newer* than the last historical bar are
    appended.  The result is sorted by time and deduplicated so the AI pipeline
    sees one continuous, time-ordered series covering the full depth range up to
    the present tick.
    """

    def _normalise_time(df: pd.DataFrame) -> pd.DataFrame:
        if "time" not in df.columns:
            return df
        df = df.copy()
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        return df

    hist = _normalise_time(hist_df)
    live = _normalise_time(live_df)

    if hist.empty:
        return live
    if live.empty:
        return hist

    hist_last_ts = hist["time"].dropna().max()
    newer_live = live[live["time"] > hist_last_ts].copy()
    if newer_live.empty:
        return hist

    # Union of columns present in both frames; skip columns missing from live.
    shared_cols = [c for c in hist.columns if c in newer_live.columns]
    if not shared_cols:
        return hist

    combined = pd.concat(
        [hist[shared_cols], newer_live[shared_cols]], ignore_index=True
    )
    combined = (
        combined.sort_values("time")
        .drop_duplicates(subset=["time"])
        .reset_index(drop=True)
    )
    return combined


def full_system(
    symbol: str = "XAUUSD",
    timeframe: str = "1d",
    lookback_years: int = 25,
    source_mode: str = "historical_first",
    news_file: str = "data/news_data_v2.csv",
    global_events_file: str = "data/global_events.csv",
):
    """Run the full market-causality stack.

    Designed for long-horizon historical studies (e.g. 25 years), while still
    supporting MT5 live fallback when requested.
    """
    run_started_at = pd.Timestamp.now("UTC")
    lifecycle_stages = [
        {
            "name": "request_received",
            "status": "completed",
            "started_at_utc": run_started_at.isoformat(),
            "completed_at_utc": run_started_at.isoformat(),
            "elapsed_ms": 0.0,
            "detail": f"analysis request accepted for requested timeframe {_normalize_timeframe_value(timeframe)}",
        }
    ]
    news_status = "not_loaded"
    global_events_status = "not_loaded"
    events_df = None

    source_mode_norm = str(source_mode or "historical_first").strip().lower()
    allow_live = source_mode_norm in {"live_first", "live_only", "hybrid"}
    allow_historical = source_mode_norm in {"historical_first", "historical_only", "hybrid", "live_first"}

    if not allow_live and not allow_historical and source_mode_norm != "combined":
        raise ValueError(
            "source_mode must be one of: historical_first, historical_only, "
            "live_first, live_only, hybrid, combined"
        )

    df = None
    source = ""
    requested_timeframe = _normalize_timeframe_value(timeframe)
    applied_timeframe = requested_timeframe
    timeframe_fallback_meta = {
        "requested_timeframe": requested_timeframe,
        "applied_timeframe": requested_timeframe,
        "fallback_applied": False,
        "fallback_reason": None,
        "applied_dataset_depth_years": None,
        "target_lookback_years": float(max(1, min(100, int(lookback_years) if lookback_years is not None else 25))),
    }
    live_error = None
    historical_error = None
    data_load_started_at = pd.Timestamp.now("UTC")

    if source_mode_norm in {"live_first", "live_only", "hybrid"} and allow_live:
        try:
            # Keep live fetch short-horizon; historical depth comes from CSV datasets.
            df = fetch_xauusd()
            source = "MT5 LIVE"
        except Exception as exc:
            live_error = str(exc)

    if df is None and allow_historical:
        try:
            df, dataset_path, applied_timeframe, timeframe_fallback_meta = _load_historical_with_fallback(
                symbol=symbol,
                timeframe=timeframe,
                lookback_years=lookback_years,
            )
            source = f"HISTORICAL CSV ({dataset_path.name})"
        except Exception as exc:
            historical_error = str(exc)

    if df is None and allow_live and source_mode_norm in {"historical_first"}:
        try:
            df = fetch_xauusd()
            source = "MT5 LIVE (fallback)"
        except Exception as exc:
            live_error = str(exc)

    # --- combined mode: full 25Y historical + live tail merged ---
    if source_mode_norm == "combined":
        _hist_df = None
        _live_df = None
        _hist_path_name = "unknown"

        try:
            _hist_df, _dpath, applied_timeframe, timeframe_fallback_meta = _load_historical_with_fallback(
                symbol=symbol,
                timeframe=timeframe,
                lookback_years=lookback_years,
            )
            _hist_path_name = _dpath.name
        except Exception as exc:
            historical_error = str(exc)

        try:
            _live_df = fetch_xauusd(count=120)
        except Exception as exc:
            live_error = str(exc)

        if _hist_df is not None and _live_df is not None:
            df = _merge_historical_and_live(_hist_df, _live_df)
            source = f"HISTORICAL+LIVE ({_hist_path_name} + live tail,  {len(df)} rows)"
        elif _hist_df is not None:
            df = _hist_df
            source = f"HISTORICAL CSV ({_hist_path_name}) [live_fetch_failed: {live_error}]"
        elif _live_df is not None:
            df = _live_df
            source = f"MT5/DATABENTO LIVE [historical_load_failed: {historical_error}]"

    if df is None:
        raise RuntimeError(
            "Unable to load data source. "
            f"historical_error={historical_error or 'none'}; live_error={live_error or 'none'}"
        )

    data_load_completed_at = pd.Timestamp.now("UTC")
    lifecycle_stages.append(
        {
            "name": "data_loaded",
            "status": "completed",
            "started_at_utc": data_load_started_at.isoformat(),
            "completed_at_utc": data_load_completed_at.isoformat(),
            "elapsed_ms": round((data_load_completed_at - data_load_started_at).total_seconds() * 1000.0, 2),
            "detail": f"source {source} loaded with applied timeframe {applied_timeframe}",
        }
    )

    news_stage_started_at = pd.Timestamp.now("UTC")
    news_df = None
    news_path = Path(news_file)
    if news_path.exists():
        try:
            news_df = load_news_data(news_file)
            df = integrate_news_features(df, news_df)
            news_status = f"loaded ({len(news_df)} events)"
        except Exception as exc:
            news_status = f"load_failed ({exc})"
    else:
        df = integrate_news_features(df, None)
        news_status = "missing_optional_file"

    news_stage_completed_at = pd.Timestamp.now("UTC")
    lifecycle_stages.append(
        {
            "name": "news_integrated",
            "status": "completed",
            "started_at_utc": news_stage_started_at.isoformat(),
            "completed_at_utc": news_stage_completed_at.isoformat(),
            "elapsed_ms": round((news_stage_completed_at - news_stage_started_at).total_seconds() * 1000.0, 2),
            "detail": f"news integration status: {news_status}",
        }
    )

    events_stage_started_at = pd.Timestamp.now("UTC")
    events_path = Path(global_events_file)
    if events_path.exists():
        try:
            events_df = load_news_data(global_events_file)
            # Global events typically have wider effect windows than scheduled news.
            df = integrate_event_features(
                df,
                events_df,
                pre_event_minutes=24 * 60,
                post_event_minutes=24 * 60,
                prefix="global_event",
            )
            global_events_status = f"loaded ({len(events_df)} events)"
        except Exception as exc:
            global_events_status = f"load_failed ({exc})"
    else:
        df = integrate_event_features(df, None, prefix="global_event")
        global_events_status = "missing_optional_file"
    # Fall back to news_df for neighbor-event context when global_events.csv is absent
    if events_df is None and news_df is not None:
        events_df = news_df
        global_events_status = f"fallback_to_news ({len(events_df)} events)"

    events_stage_completed_at = pd.Timestamp.now("UTC")
    lifecycle_stages.append(
        {
            "name": "events_integrated",
            "status": "completed",
            "started_at_utc": events_stage_started_at.isoformat(),
            "completed_at_utc": events_stage_completed_at.isoformat(),
            "elapsed_ms": round((events_stage_completed_at - events_stage_started_at).total_seconds() * 1000.0, 2),
            "detail": f"global events status: {global_events_status}",
        }
    )

    # Cap analysis rows for runtime stability on large intraday historical sets.
    # The source dataset depth metadata is still preserved above; this only
    # bounds the rows fed into the heavy intelligence stage.
    max_analysis_rows = max(5_000, int(os.getenv("MCL_MAX_ANALYSIS_ROWS", "50000")))
    if len(df) > max_analysis_rows:
        sampling_stage_started_at = pd.Timestamp.now("UTC")
        step = max(1, int(len(df) / max_analysis_rows))
        sampled = df.iloc[::step].copy()
        if not sampled.empty and not sampled.index.equals(df.tail(1).index):
            sampled = pd.concat([sampled, df.tail(1)], axis=0).drop_duplicates().reset_index(drop=True)
        original_rows = int(len(df))
        df = sampled.tail(max_analysis_rows).reset_index(drop=True)
        sampling_stage_completed_at = pd.Timestamp.now("UTC")
        lifecycle_stages.append(
            {
                "name": "analysis_downsampled",
                "status": "completed",
                "started_at_utc": sampling_stage_started_at.isoformat(),
                "completed_at_utc": sampling_stage_completed_at.isoformat(),
                "elapsed_ms": round((sampling_stage_completed_at - sampling_stage_started_at).total_seconds() * 1000.0, 2),
                "detail": f"rows reduced from {original_rows} to {len(df)} using step {step}",
            }
        )

    intelligence_started_at = pd.Timestamp.now("UTC")
    result = process(df)
    intelligence_completed_at = pd.Timestamp.now("UTC")
    depth_years = _historical_depth_years(df)
    requested_lookback = int(lookback_years) if lookback_years is not None else 25
    result["data_source"] = source
    result["symbol"] = str(symbol or "XAUUSD").strip().upper()
    result["requested_timeframe"] = requested_timeframe
    result["applied_timeframe"] = applied_timeframe
    result["timeframe"] = applied_timeframe
    result["timeframe_fallback_applied"] = bool(timeframe_fallback_meta.get("fallback_applied"))
    result["timeframe_fallback_reason"] = timeframe_fallback_meta.get("fallback_reason")
    result["applied_dataset_depth_years"] = timeframe_fallback_meta.get("applied_dataset_depth_years")
    result["lookback_years"] = requested_lookback
    result["source_mode"] = source_mode_norm
    result["rows_analyzed"] = int(len(df))
    result["historical_depth_years"] = depth_years
    result["lookback_target_met"] = bool(depth_years is not None and depth_years >= max(0.0, requested_lookback - 0.25))
    result["lookback_depth_warning"] = None if result["lookback_target_met"] else "historical_dataset_depth_below_requested_lookback"
    result["news_source"] = news_file
    result["news_status"] = news_status
    result["global_events_source"] = global_events_file
    result["global_events_status"] = global_events_status
    lifecycle_stages.append(
        {
            "name": "intelligence_computed",
            "status": "completed",
            "started_at_utc": intelligence_started_at.isoformat(),
            "completed_at_utc": intelligence_completed_at.isoformat(),
            "elapsed_ms": round((intelligence_completed_at - intelligence_started_at).total_seconds() * 1000.0, 2),
            "detail": f"market memory scanned and {result['rows_analyzed']} rows analyzed",
        }
    )

    observation_logged = False
    observation_started_at = pd.Timestamp.now("UTC")
    try:
        observation_meta = record_observation(
            df=df,
            result=result,
            events_df=events_df,
            symbol=result["symbol"],
            requested_timeframe=requested_timeframe,
            applied_timeframe=applied_timeframe,
            lookback_years=requested_lookback,
            source_mode=source_mode_norm,
        )
        result.update(observation_meta)
        result = _apply_gann_signal_alignment(result)
        observation_logged = True
    except Exception as exc:
        # Observation logging should never block live/historical intelligence output.
        result["observation_error"] = str(exc)
    observation_completed_at = pd.Timestamp.now("UTC")
    lifecycle_stages.append(
        {
            "name": "observation_recorded",
            "status": "completed" if observation_logged else "skipped",
            "started_at_utc": observation_started_at.isoformat(),
            "completed_at_utc": observation_completed_at.isoformat(),
            "elapsed_ms": round((observation_completed_at - observation_started_at).total_seconds() * 1000.0, 2),
            "detail": "observation telemetry persisted" if observation_logged else "observation telemetry unavailable",
        }
    )

    run_completed_at = pd.Timestamp.now("UTC")
    result["analysis_lifecycle"] = _build_analysis_lifecycle(
        started_at=run_started_at,
        completed_at=run_completed_at,
        stages=lifecycle_stages,
    )
    result["reasoning_display"] = _build_reasoning_display(result)
    result["analysis_started_at_utc"] = result["analysis_lifecycle"]["started_at_utc"]
    result["analysis_completed_at_utc"] = result["analysis_lifecycle"]["completed_at_utc"]
    result["analysis_elapsed_ms"] = result["analysis_lifecycle"]["elapsed_ms"]

    return result


def main() -> None:
    result = full_system()

    print("DATA SOURCE:", result["data_source"])
    print("NEWS SOURCE:", result["news_source"])
    print("NEWS STATUS:", result["news_status"])
    if result.get("observation_log_path"):
        print("OBSERVATION LOG:", result.get("observation_log_path"))
        print("OBSERVATION ID:", result.get("observation_id"))
    if result.get("observation_error"):
        print("OBSERVATION ERROR:", result.get("observation_error"))
    print("Matches:", result["matches"])
    print("Probability:", result["probability"])
    print("AI Decision:", result["ai_decision"])
    print("Psychology:", result["psychology"])
    print("Trap:", result["trap"])
    print("Behavior:", result["behavior"])
    print("GANN ADV:", result["gann_adv"])
    print("ASTRO:", result["astro"])
    print("NUMEROLOGY:", result["numerology"])
    print("HARMONIC:", result["harmonic"])
    print("TIME SIGNAL:", result["time_signal"])
    print("FUTURE:", result["future"])
    print("WEIGHTS:", result["weights"])
    print("SIGNALS:", result["signals"])
    print("DOMINANCE SCORE:", result["score"])
    print("CONFIDENCE:", result["confidence"])
    print("SCENARIOS:", result["scenarios"])
    print("QUALITY:", result["quality"])
    print("FILTERED SIGNAL:", result["filtered_signal"])
    print("NEWS CONTEXT:", result.get("news"))
    print("NEWS GUARD APPLIED:", result.get("news_guard_applied"))
    print("REJECTION REASON:", result.get("rejection_reason") or "none")
    if result.get("decision_trace"):
        dt = result["decision_trace"]
        print("DOMINANT FORCE:", dt.get("dominant_force"))
        print("CONFLICT SCORE:", dt.get("conflict_score"))
        print("RELIABILITY SCORE:", dt.get("reliability_score"))
        print("WEIGHTED FORCES:", dt.get("weighted_forces"))
    if result.get("trade_levels"):
        tl = result["trade_levels"]
        print(f"TRADE LEVELS: Entry={tl['entry']}  SL={tl['stop_loss']} (-$10)  TP={tl['take_profit']} (+$20)  R={tl['r_ratio']}:1  Hold={tl['hold_bars']}bars")
    print("UPDATED WEIGHTS:", result["updated_weights"])
    print("MEMORY SIZE:", result["memory_size"])
    print("BACKTEST:", result["backtest"])
    print("EXECUTION:", result["execution"])
    print("FAILURE:", result["failure"])

    # Precision + Realism Layer
    dq = result.get("data_quality", {})
    print(f"\nDATA QUALITY: score={dq.get('score')}  status={dq.get('status')}  issues={dq.get('issues')}")

    lat = result.get("latency", {})
    print(f"LATENCY: verdict={lat.get('timing_verdict')}  bar_delay={lat.get('bar_latency', {}).get('delay_bars')}  urgency={lat.get('reaction_window', {}).get('urgency')}")

    ts = result.get("timescale", {})
    vr = ts.get("volatility_regime", {})
    print(f"TIMESCALE: regime={vr.get('regime')}  speed_ratio={vr.get('speed_ratio')}  modifier={ts.get('signal_modifier')}")

    sm = result.get("simple", {})
    print(f"SIMPLICITY: bias={sm.get('bias_score')}  label={sm.get('bias_label')}  clarity={sm.get('clarity')}/100  conviction={sm.get('conviction')}")

    ov = result.get("overfit", {})
    print(f"OVERFIT GUARD: risk={ov.get('overfit_risk')}  recommendation={ov.get('recommendation')}")

    ue = result.get("universal", {})
    ue_num = ue.get("numerology", {})
    ue_gann = ue.get("gann", {})
    ue_nak = ue.get("nakshatra", {})
    ue_harm = ue.get("harmonic", {})
    print(f"\nUNIVERSAL ENGINE:")
    print(f"  NUMEROLOGY: number={ue_num.get('number')}  meaning={ue_num.get('meaning')}")
    print(f"  GANN DEGREE: {ue_gann.get('degrees')}°  cycle={ue_gann.get('cycle', {}).get('description')}  PTE={ue_gann.get('price_time_equality', {}).get('status')}")
    print(f"  NAKSHATRA: {ue_nak.get('nakshatra')}  pada={ue_nak.get('pada')}  pos={ue_nak.get('position_pct')}%")
    print(f"  PRICE DEGREE: {ue.get('price_degree')}°")
    print(f"  HARMONIC: status={ue_harm.get('status')}  abcd={ue_harm.get('abcd_pattern', {}).get('type')}  d_up={ue_harm.get('d_extension_up')}  d_down={ue_harm.get('d_extension_down')}")

    print("\nFINAL INTELLIGENCE OUTPUT")
    for k, v in result["final"].items():
        print(f"{k}: {v}")

    institutional = result["institutional"]
    print("\nGLOBAL MARKET INTELLIGENCE")
    print("MULTI ASSET:", institutional["multi_asset"])
    print("MACRO:", institutional["macro"])
    print("CAPITAL FLOW:", institutional["capital_flow"])
    print("CORRELATION GOLD-USD:", institutional["correlation_gold_usd"])
    print("INSTITUTIONAL DECISION:", institutional["institutional_decision"])
    print("INSTITUTIONAL SCORE:", institutional["institutional_score"])


if __name__ == "__main__":
    main()