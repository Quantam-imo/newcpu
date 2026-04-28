from __future__ import annotations

from typing import Any

import numpy as np

from backend.ai.feature_vector import create_feature_vector


PHASE_MAP = {
    "ACCUMULATION": 0,
    "MANIPULATION": 1,
    "EXPANSION": 2,
    "DISTRIBUTION": 3,
    "NEUTRAL": 4,
}


DEFAULT_LABEL_MODE = "trend_up"
DEFAULT_TARGET_RETURN_PCT = 0.002
DEFAULT_STOP_RETURN_PCT = 0.001
DEFAULT_SETUP_MODE = "all_bars"


FEATURE_NAMES = [
    "base_trend",
    "base_momentum",
    "base_volatility",
    "physics_force",
    "physics_velocity",
    "gann_zone_reversal",
    "liq_buy_side_sweep",
    "liq_sell_side_sweep",
    "phase_code",
    "news_impact_score",
    "news_event_count",
    "news_high_impact_active",
    "news_aspect_event_count",
    "news_conjunction_count",
    "news_square_count",
    "news_opposition_count",
    "news_trine_count",
    "news_sextile_count",
    "news_ingress_event_count",
    "news_nakshatra_event_count",
    "news_gann_event_count",
    "news_eclipse_event_count",
    "signal_buy_flag",
    "signal_sell_flag",
    "state_price",
    "structure_bos_up",
    "structure_bos_down",
    "structure_choch_up",
    "structure_choch_down",
    "structure_hh_hl",
    "structure_ll_lh",
    "structure_trend_strength",
    "reliability_score",
    "conflict_score",
    "confluence_ready",
    "buy_force",
    "sell_force",
    "trap_buyer",
    "trap_seller",
    "trap_probability",
    "compression_score",
    "compression_breakout_near",
    "compression_silence_active",
    "compression_cycle_tightening",
    "compression_energy_stored",
    "compression_bars_in_compression",
    "cycle_moon_phase_position",
    "cycle_nakshatra_sequence",
    "cycle_gann_degree",
    "cycle_days_to_next_node",
    "cycle_planetary_active",
    "regime_trend_up",
    "regime_trend_down",
    "regime_range",
    "regime_transition",
    "phase_accumulation",
    "phase_manipulation",
    "phase_expansion",
    "phase_distribution",
    "phase_neutral",
    "signal_active_in_accumulation",
    "signal_active_in_manipulation",
    "signal_active_in_distribution",
]

LAYERED_FEATURE_NAMES = FEATURE_NAMES + [
    "time_planetary_aspects_active",
    "time_planetary_conjunction_active",
    "time_planetary_square_active",
    "time_planetary_opposition_active",
    "time_moon_phase_active",
    "time_retrograde_active",
    "time_nakshatra_transition_active",
    "time_moon_eclipse_active",
    "time_moon_new_active",
    "time_moon_full_active",
    "time_sq9_level_active",
    "time_gann_45_cycle_active",
    "time_gann_90_cycle_active",
    "time_gann_180_cycle_active",
    "time_gann_pressure_window",
    "time_gann_station_active",
    "time_gann_synodic_active",
    "time_gann_time_cycle_exact",
    "time_cycle_active",
    "time_window_score",
    "location_bullish_fvg_near",
    "location_bearish_fvg_near",
    "location_bullish_order_block_near",
    "location_bearish_order_block_near",
    "location_equal_highs_near",
    "location_equal_lows_near",
    "location_session_high_near",
    "location_session_low_near",
    "location_at_key_level",
    "location_zone_score",
    "trigger_sweep_buy_side",
    "trigger_sweep_sell_side",
    "trigger_mss_bullish",
    "trigger_mss_bearish",
    "trigger_bos_bullish",
    "trigger_bos_bearish",
    "trigger_displacement_bullish",
    "trigger_displacement_bearish",
    "trigger_confirmed",
    "participation_news_active",
    "participation_volume_spike",
    "participation_london_open",
    "participation_newyork_open",
    "participation_score",
    "participation_strong",
    "decision_time_score",
    "decision_execute_trade",
    "gann_tangent_angle_deg",
    "gann_tangent_expansion_strength",
    "gann_cosine_retracement",
    "gann_circle_projection_deg",
    "gann_circle_harmonic_proximity",
    "gann_sqrt_rotation_deg",
    "gann_degree_projection_active",
    "gann_degree_projection_distance",
    "gann_time_price_balance_ratio",
    "gann_major_turn_window",
]

ELLIOTT_UNIFIED_FEATURE_NAMES = LAYERED_FEATURE_NAMES + [
    "elliott_wave_phase_impulse",
    "elliott_wave_phase_corrective",
    "elliott_wave_confidence",
    "elliott_wave_direction_up",
    "elliott_wave_position_norm",
    "elliott_wave_progress",
    "elliott_adjacent_wave_alignment",
    "elliott_cycle_alignment_score",
    "elliott_angle_alignment_score",
    "elliott_astro_alignment_score",
    "elliott_market_phase_alignment_score",
    "elliott_wave_span_bars",
    "elliott_wave_amplitude_norm",
    "elliott_initial_to_current_norm",
    "elliott_current_to_ending_norm",
    # Explicit Elliott x Gann-wheel confluence features.
    "elliott_wheel_rotation_alignment",
    "elliott_wheel_major_turn_confluence",
    "elliott_wheel_progress_sync",
    "elliott_wheel_balance_confluence",
    "elliott_wheel_phase_rotation_gate",
]

FEATURE_NAMES_BY_VERSION = {
    "v3_amd_cycle_state": FEATURE_NAMES,
    "v4_layered_execution": LAYERED_FEATURE_NAMES,
    "v5_elliott_unified": ELLIOTT_UNIFIED_FEATURE_NAMES,
    # Backward-compatible alias used by older model bundles.
    "v5_unified_elliott_cycle": ELLIOTT_UNIFIED_FEATURE_NAMES,
}


def feature_names_for_version(feature_version: str | None = None) -> list[str]:
    version = str(feature_version or "v3_amd_cycle_state").strip().lower() or "v3_amd_cycle_state"
    if version == "v5_unified_elliott_cycle":
        version = "v5_elliott_unified"
    if version not in FEATURE_NAMES_BY_VERSION:
        raise ValueError(f"Unsupported feature version: {feature_version}")
    return FEATURE_NAMES_BY_VERSION[version]


def build_feature_row(record: dict[str, Any], feature_version: str = "v3_amd_cycle_state") -> list[float]:
    """Build an extended feature row from a scanned market record."""
    base = list(create_feature_vector(record))

    news = (record or {}).get("news") or {}
    structure = (record or {}).get("structure") or {}
    trap = (record or {}).get("trap") or {}
    compression = (record or {}).get("compression") or {}
    cycle = (record or {}).get("cycle") or {}
    time_engine = (record or {}).get("time_engine") or {}
    reliability = (record or {}).get("reliability") or {}
    location = (record or {}).get("location") or {}
    trigger = (record or {}).get("trigger") or {}
    participation = (record or {}).get("participation") or {}
    decision_context = (record or {}).get("decision_context") or {}
    gann_astro_math = (record or {}).get("gann_astro_math") or {}
    elliott_wave = (record or {}).get("elliott_wave") or {}
    signal = str((record or {}).get("signal") or "WAIT").upper()
    state = (record or {}).get("state") or {}
    phase = str((record or {}).get("phase") or "NEUTRAL").upper()

    regime = str(structure.get("regime") or "TRANSITION").upper()
    regime_trend_up = 1.0 if regime == "TREND_UP" else 0.0
    regime_trend_down = 1.0 if regime == "TREND_DOWN" else 0.0
    regime_range = 1.0 if regime == "RANGE" else 0.0
    regime_transition = 1.0 if regime not in {"TREND_UP", "TREND_DOWN", "RANGE"} else 0.0
    phase_accumulation = 1.0 if phase == "ACCUMULATION" else 0.0
    phase_manipulation = 1.0 if phase == "MANIPULATION" else 0.0
    phase_expansion = 1.0 if phase == "EXPANSION" else 0.0
    phase_distribution = 1.0 if phase == "DISTRIBUTION" else 0.0
    phase_neutral = 1.0 if phase not in PHASE_MAP else 0.0
    signal_active = 1.0 if signal in {"BUY", "SELL", "STRONG BUY", "STRONG SELL"} else 0.0
    days_to_node = float(cycle.get("days_to_next_node", 365.0) or 365.0)
    days_to_node = max(0.0, min(365.0, days_to_node))

    extra = [
        float(news.get("impact_score", 0.0) or 0.0),
        float(news.get("event_count", 0.0) or 0.0),
        1.0 if bool(news.get("high_impact_active", False)) else 0.0,
        float(news.get("aspect_event_count", 0.0) or 0.0),
        float(news.get("conjunction_count", 0.0) or 0.0),
        float(news.get("square_count", 0.0) or 0.0),
        float(news.get("opposition_count", 0.0) or 0.0),
        float(news.get("trine_count", 0.0) or 0.0),
        float(news.get("sextile_count", 0.0) or 0.0),
        float(news.get("ingress_event_count", 0.0) or 0.0),
        float(news.get("nakshatra_event_count", 0.0) or 0.0),
        float(news.get("gann_event_count", 0.0) or 0.0),
        float(news.get("eclipse_event_count", 0.0) or 0.0),
        1.0 if signal in {"BUY", "STRONG BUY"} else 0.0,
        1.0 if signal in {"SELL", "STRONG SELL"} else 0.0,
        float(state.get("price", 0.0) or 0.0),
        # Structure learning features.
        1.0 if bool(structure.get("bos_up", False)) else 0.0,
        1.0 if bool(structure.get("bos_down", False)) else 0.0,
        1.0 if bool(structure.get("choch_up", False)) else 0.0,
        1.0 if bool(structure.get("choch_down", False)) else 0.0,
        1.0 if bool(structure.get("hh_hl", False)) else 0.0,
        1.0 if bool(structure.get("ll_lh", False)) else 0.0,
        float(structure.get("trend_strength", 0.0) or 0.0),
        # Reliability + confluence learning features.
        float(reliability.get("reliability_score", 0.0) or 0.0),
        float(reliability.get("conflict_score", 0.0) or 0.0),
        1.0 if bool(reliability.get("confluence_ready", False)) else 0.0,
        float(reliability.get("buy_force", 0.0) or 0.0),
        float(reliability.get("sell_force", 0.0) or 0.0),
        # Trap / pressure features.
        1.0 if str(trap.get("trap") or "").upper() == "BUYER_TRAP" else 0.0,
        1.0 if str(trap.get("trap") or "").upper() == "SELLER_TRAP" else 0.0,
        float(trap.get("probability", 0.0) or 0.0),
        # Time-compression / cycle features.
        float(compression.get("score", 0.0) or 0.0),
        1.0 if bool(compression.get("breakout_near", False)) else 0.0,
        1.0 if bool(compression.get("silence_active", False)) else 0.0,
        1.0 if bool(compression.get("cycle_tightening", False)) else 0.0,
        float(compression.get("energy_stored", 0.0) or 0.0),
        float(compression.get("bars_in_compression", 0.0) or 0.0),
        # Master-cycle state features.
        float(cycle.get("moon_phase_position", 0.0) or 0.0),
        float(cycle.get("nakshatra_sequence", 0.0) or 0.0),
        float(cycle.get("gann_degree", 0.0) or 0.0),
        days_to_node,
        1.0 if bool(cycle.get("planetary_active", False)) else 0.0,
        # Regime one-hot.
        regime_trend_up,
        regime_trend_down,
        regime_range,
        regime_transition,
        # Explicit AMD phase learning features.
        phase_accumulation,
        phase_manipulation,
        phase_expansion,
        phase_distribution,
        phase_neutral,
        signal_active * phase_accumulation,
        signal_active * phase_manipulation,
        signal_active * phase_distribution,
    ]

    row = [float(x) for x in (base + extra)]

    version = str(feature_version or "v3_amd_cycle_state").strip().lower() or "v3_amd_cycle_state"
    if version == "v5_unified_elliott_cycle":
        version = "v5_elliott_unified"
    if version == "v3_amd_cycle_state":
        return row
    if version not in {"v4_layered_execution", "v5_elliott_unified"}:
        raise ValueError(f"Unsupported feature version: {feature_version}")

    layered = [
        1.0 if bool(time_engine.get("planetary_aspects_active", False)) else 0.0,
        1.0 if bool(time_engine.get("planetary_conjunction_active", False)) else 0.0,
        1.0 if bool(time_engine.get("planetary_square_active", False)) else 0.0,
        1.0 if bool(time_engine.get("planetary_opposition_active", False)) else 0.0,
        1.0 if bool(time_engine.get("moon_phase_active", False)) else 0.0,
        1.0 if bool(time_engine.get("retrograde_active", False)) else 0.0,
        1.0 if bool(time_engine.get("nakshatra_transition_active", False)) else 0.0,
        1.0 if bool(time_engine.get("moon_eclipse_active", False)) else 0.0,
        1.0 if bool(time_engine.get("moon_new_active", False)) else 0.0,
        1.0 if bool(time_engine.get("moon_full_active", False)) else 0.0,
        1.0 if bool(time_engine.get("sq9_level_active", False)) else 0.0,
        1.0 if bool(time_engine.get("gann_45_cycle_active", False)) else 0.0,
        1.0 if bool(time_engine.get("gann_90_cycle_active", False)) else 0.0,
        1.0 if bool(time_engine.get("gann_180_cycle_active", False)) else 0.0,
        1.0 if bool(time_engine.get("gann_pressure_window", False)) else 0.0,
        1.0 if bool(time_engine.get("gann_station_active", False)) else 0.0,
        1.0 if bool(time_engine.get("gann_synodic_active", False)) else 0.0,
        1.0 if bool(time_engine.get("gann_time_cycle_exact", False)) else 0.0,
        1.0 if bool(time_engine.get("time_cycle_active", False)) else 0.0,
        float(time_engine.get("time_window_score", 0.0) or 0.0),
        1.0 if bool(location.get("bullish_fvg_near", False)) else 0.0,
        1.0 if bool(location.get("bearish_fvg_near", False)) else 0.0,
        1.0 if bool(location.get("bullish_order_block_near", False)) else 0.0,
        1.0 if bool(location.get("bearish_order_block_near", False)) else 0.0,
        1.0 if bool(location.get("equal_highs_near", False)) else 0.0,
        1.0 if bool(location.get("equal_lows_near", False)) else 0.0,
        1.0 if bool(location.get("session_high_near", False)) else 0.0,
        1.0 if bool(location.get("session_low_near", False)) else 0.0,
        1.0 if bool(location.get("at_key_level", False)) else 0.0,
        float(location.get("zone_score", 0.0) or 0.0),
        1.0 if bool(trigger.get("sweep_buy_side", False)) else 0.0,
        1.0 if bool(trigger.get("sweep_sell_side", False)) else 0.0,
        1.0 if bool(trigger.get("mss_bullish", False)) else 0.0,
        1.0 if bool(trigger.get("mss_bearish", False)) else 0.0,
        1.0 if bool(trigger.get("bos_bullish", False)) else 0.0,
        1.0 if bool(trigger.get("bos_bearish", False)) else 0.0,
        1.0 if bool(trigger.get("displacement_bullish", False)) else 0.0,
        1.0 if bool(trigger.get("displacement_bearish", False)) else 0.0,
        1.0 if bool(trigger.get("trigger_confirmed", False)) else 0.0,
        1.0 if bool(participation.get("news_active", False)) else 0.0,
        1.0 if bool(participation.get("volume_spike", False)) else 0.0,
        1.0 if bool(participation.get("london_open", False)) else 0.0,
        1.0 if bool(participation.get("newyork_open", False)) else 0.0,
        float(participation.get("participation_score", 0.0) or 0.0),
        1.0 if str(participation.get("participation_strength") or "weak") == "strong" else 0.0,
        float(decision_context.get("time_score", 0.0) or 0.0),
        1.0 if bool(decision_context.get("execute_trade", False)) else 0.0,
        float(gann_astro_math.get("tangent_angle_deg", 0.0) or 0.0),
        float(gann_astro_math.get("tangent_expansion_strength", 0.0) or 0.0),
        float(gann_astro_math.get("cosine_retracement", 0.0) or 0.0),
        float(gann_astro_math.get("circle_projection_deg", 0.0) or 0.0),
        float(gann_astro_math.get("circle_harmonic_proximity", 0.0) or 0.0),
        float(gann_astro_math.get("sqrt_rotation_deg", 0.0) or 0.0),
        1.0 if bool(gann_astro_math.get("degree_projection_active", False)) else 0.0,
        float(gann_astro_math.get("degree_projection_distance", 0.0) or 0.0),
        float(gann_astro_math.get("time_price_balance_ratio", 0.0) or 0.0),
        1.0 if bool(gann_astro_math.get("major_turn_window", False)) else 0.0,
    ]

    if version == "v4_layered_execution":
        return [float(x) for x in (row + layered)]

    elliott_wave_confidence = float(elliott_wave.get("wave_confidence", 0.0) or 0.0)
    elliott_wave_progress = float(elliott_wave.get("wave_progress", 0.0) or 0.0)
    elliott_wave_direction_up = 1.0 if bool(elliott_wave.get("wave_direction_up", False)) else 0.0
    elliott_wave_phase_impulse = 1.0 if str(elliott_wave.get("wave_phase") or "").upper() == "IMPULSE" else 0.0
    elliott_wave_phase_corrective = 1.0 if str(elliott_wave.get("wave_phase") or "").upper() == "CORRECTIVE" else 0.0
    elliott_cycle_alignment = float(elliott_wave.get("cycle_alignment_score", 0.0) or 0.0)
    elliott_angle_alignment = float(elliott_wave.get("angle_alignment_score", 0.0) or 0.0)
    elliott_market_phase_alignment = float(elliott_wave.get("market_phase_alignment_score", 0.0) or 0.0)

    gann_rotation = float(gann_astro_math.get("sqrt_rotation_deg", 0.0) or 0.0)
    gann_circle_harmonic = float(gann_astro_math.get("circle_harmonic_proximity", 0.0) or 0.0)
    gann_major_turn = 1.0 if bool(gann_astro_math.get("major_turn_window", False)) else 0.0
    gann_balance = float(gann_astro_math.get("time_price_balance_ratio", 0.0) or 0.0)
    gann_degree = float(cycle.get("gann_degree", 0.0) or 0.0)
    gann_degree_norm = max(0.0, min(1.0, gann_degree / 360.0))

    # Elliott-wave x wheel rotation fusion features to teach start->end confluence.
    elliott_wheel_rotation_alignment = elliott_angle_alignment * gann_circle_harmonic
    elliott_wheel_major_turn_confluence = elliott_wave_confidence * gann_major_turn
    elliott_wheel_progress_sync = 1.0 - abs(elliott_wave_progress - gann_degree_norm)
    elliott_wheel_progress_sync = max(0.0, min(1.0, elliott_wheel_progress_sync))
    elliott_wheel_balance_confluence = elliott_cycle_alignment * gann_balance
    elliott_wheel_phase_rotation_gate = (
        elliott_wave_phase_impulse * elliott_wave_direction_up * max(0.0, gann_rotation)
        + elliott_wave_phase_corrective * (1.0 - elliott_wave_direction_up) * max(0.0, -gann_rotation)
    )
    elliott_wheel_phase_rotation_gate *= max(0.0, min(1.0, elliott_market_phase_alignment))

    elliott_layer = [
        elliott_wave_phase_impulse,
        elliott_wave_phase_corrective,
        elliott_wave_confidence,
        elliott_wave_direction_up,
        float(elliott_wave.get("wave_position_norm", 0.0) or 0.0),
        elliott_wave_progress,
        float(elliott_wave.get("adjacent_wave_alignment", 0.0) or 0.0),
        elliott_cycle_alignment,
        elliott_angle_alignment,
        float(elliott_wave.get("astro_alignment_score", 0.0) or 0.0),
        elliott_market_phase_alignment,
        float(elliott_wave.get("wave_span_bars", 0.0) or 0.0),
        float(elliott_wave.get("wave_amplitude_norm", 0.0) or 0.0),
        float(elliott_wave.get("initial_to_current_norm", 0.0) or 0.0),
        float(elliott_wave.get("current_to_ending_norm", 0.0) or 0.0),
        elliott_wheel_rotation_alignment,
        elliott_wheel_major_turn_confluence,
        elliott_wheel_progress_sync,
        elliott_wheel_balance_confluence,
        elliott_wheel_phase_rotation_gate,
    ]

    return [float(x) for x in (row + layered + elliott_layer)]


def _label_from_record(record: dict[str, Any]) -> int:
    trend = str(((record or {}).get("state") or {}).get("trend") or "DOWN").upper()
    return 1 if trend == "UP" else 0


def _record_price(record: dict[str, Any]) -> float | None:
    state = (record or {}).get("state") or {}
    try:
        price = float(state.get("price", 0.0) or 0.0)
    except Exception:
        return None
    if not np.isfinite(price) or price <= 0.0:
        return None
    return price


def _first_touch_buy_label(
    memory: list[dict[str, Any]],
    start_idx: int,
    horizon: int,
    target_return_pct: float,
    stop_return_pct: float,
) -> int:
    entry = _record_price(memory[start_idx])
    if entry is None:
        return 0

    target = abs(float(target_return_pct or 0.0))
    stop = abs(float(stop_return_pct or 0.0))
    upper = min(len(memory) - 1, start_idx + int(max(1, horizon)))

    for idx in range(start_idx + 1, upper + 1):
        future_price = _record_price(memory[idx])
        if future_price is None:
            continue
        move = (future_price - entry) / entry
        if move >= target:
            return 1
        if stop > 0.0 and move <= -stop:
            return 0

    final_price = _record_price(memory[upper])
    if final_price is None:
        return 0
    final_move = (final_price - entry) / entry
    return 1 if final_move >= target else 0


def _first_touch_sell_label(
    memory: list[dict[str, Any]],
    start_idx: int,
    horizon: int,
    target_return_pct: float,
    stop_return_pct: float,
) -> int:
    entry = _record_price(memory[start_idx])
    if entry is None:
        return 0

    target = abs(float(target_return_pct or 0.0))
    stop = abs(float(stop_return_pct or 0.0))
    upper = min(len(memory) - 1, start_idx + int(max(1, horizon)))

    for idx in range(start_idx + 1, upper + 1):
        future_price = _record_price(memory[idx])
        if future_price is None:
            continue
        move = (future_price - entry) / entry
        if move <= -target:
            return 1
        if stop > 0.0 and move >= stop:
            return 0

    final_price = _record_price(memory[upper])
    if final_price is None:
        return 0
    final_move = (final_price - entry) / entry
    return 1 if final_move <= -target else 0


def label_config(label_mode: str | None, target_return_pct: float, stop_return_pct: float) -> dict[str, float | str]:
    mode = str(label_mode or DEFAULT_LABEL_MODE).strip().lower() or DEFAULT_LABEL_MODE
    return {
        "label_mode": mode,
        "target_return_pct": float(target_return_pct),
        "stop_return_pct": float(stop_return_pct),
    }


def setup_config(setup_mode: str | None = None) -> dict[str, str]:
    mode = str(setup_mode or DEFAULT_SETUP_MODE).strip().lower() or DEFAULT_SETUP_MODE
    return {
        "setup_mode": mode,
    }


def record_matches_setup(record: dict[str, Any], setup_mode: str = DEFAULT_SETUP_MODE) -> bool:
    mode = str(setup_mode or DEFAULT_SETUP_MODE).strip().lower() or DEFAULT_SETUP_MODE
    if mode == "all_bars":
        return True

    trigger = (record or {}).get("trigger") or {}
    location = (record or {}).get("location") or {}
    participation = (record or {}).get("participation") or {}
    decision_context = (record or {}).get("decision_context") or {}

    if mode == "triggered_trade":
        return bool(
            trigger.get("trigger_confirmed", False)
            and location.get("at_key_level", False)
        )

    if mode == "london_sweep_mss_buy":
        london_active = bool(participation.get("london_session", participation.get("london_open", False)))
        return bool(
            london_active
            and trigger.get("trigger_confirmed", False)
            and trigger.get("trigger_direction") == "BUY"
            and float(decision_context.get("time_score", 0.0) or 0.0) >= 0.35
        )

    if mode == "buy_trigger_candidate":
        return bool(
            trigger.get("trigger_confirmed", False)
            and trigger.get("trigger_direction") == "BUY"
            and float(decision_context.get("time_score", 0.0) or 0.0) >= 0.2
        )

    if mode == "sell_trigger_candidate":
        return bool(
            trigger.get("trigger_confirmed", False)
            and trigger.get("trigger_direction") == "SELL"
            and float(decision_context.get("time_score", 0.0) or 0.0) >= 0.2
        )

    raise ValueError(f"Unsupported setup mode: {setup_mode}")


def label_from_memory(
    memory: list[dict[str, Any]],
    start_idx: int,
    horizon: int,
    label_mode: str = DEFAULT_LABEL_MODE,
    target_return_pct: float = DEFAULT_TARGET_RETURN_PCT,
    stop_return_pct: float = DEFAULT_STOP_RETURN_PCT,
) -> int:
    mode = str(label_mode or DEFAULT_LABEL_MODE).strip().lower() or DEFAULT_LABEL_MODE
    if mode == "trend_up":
        return _label_from_record(memory[start_idx + horizon])
    if mode == "first_touch_buy":
        return _first_touch_buy_label(memory, start_idx, horizon, target_return_pct, stop_return_pct)
    if mode == "first_touch_sell":
        return _first_touch_sell_label(memory, start_idx, horizon, target_return_pct, stop_return_pct)
    raise ValueError(f"Unsupported label mode: {label_mode}")


def build_dataset_from_memory(
    memory: list[dict[str, Any]],
    horizon: int = 1,
    label_mode: str = DEFAULT_LABEL_MODE,
    target_return_pct: float = DEFAULT_TARGET_RETURN_PCT,
    stop_return_pct: float = DEFAULT_STOP_RETURN_PCT,
    feature_version: str = "v3_amd_cycle_state",
    setup_mode: str = DEFAULT_SETUP_MODE,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Build supervised dataset from memory records.

    Features at index i predict a future label computed over i+1..i+horizon.
    """
    if not memory or len(memory) < (horizon + 5):
        return np.empty((0, 0), dtype=float), np.empty((0,), dtype=int)

    X: list[list[float]] = []
    y: list[int] = []

    upper = len(memory) - int(max(1, horizon))
    for i in range(upper):
        if not record_matches_setup(memory[i], setup_mode=setup_mode):
            continue
        row = build_feature_row(memory[i], feature_version=feature_version)
        target = label_from_memory(
            memory,
            i,
            horizon=int(max(1, horizon)),
            label_mode=label_mode,
            target_return_pct=target_return_pct,
            stop_return_pct=stop_return_pct,
        )
        X.append(row)
        y.append(target)

    return np.array(X, dtype=float), np.array(y, dtype=int)


def standardize_fit(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if X.size == 0:
        return X, np.array([], dtype=float), np.array([], dtype=float)
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std = np.where(std < 1e-12, 1.0, std)
    Xs = (X - mean) / std
    return Xs, mean, std


def standardize_transform(X: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    if X.size == 0:
        return X
    return (X - mean) / np.where(std < 1e-12, 1.0, std)
