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

GANN_ICT_FEATURE_NAMES = ELLIOTT_UNIFIED_FEATURE_NAMES + [
    # === Gann fan angle features ===
    "gann_1x1_angle_above",           # price is above the 1x1 (45°) angle from major swing low
    "gann_1x2_angle_active",          # trend is steep (>63.4°) — 1 price unit per 2 time units
    "gann_2x1_angle_active",          # trend is slow (<26.6°) — 2 time units per 1 price unit
    "gann_sq9_next_level_distance",   # normalised distance to next Sq9 cardinal level (0–1)
    "gann_time_cycle_90d_window",     # within the 90-day Gann time-cycle window
    "gann_time_cycle_360d_window",    # within the annual Gann time-cycle window
    "gann_master_price_number",       # price is near a Gann master number (144, 288, 432…)
    # === ICT killzone & precision features ===
    "ict_killzone_london_open",       # current bar is inside London Open killzone (02:00–05:00 EST)
    "ict_killzone_ny_open",           # current bar is inside New York Open killzone (07:00–10:00 EST)
    "ict_optimal_trade_entry",        # OTE retracement (61.8–79%) into a FVG is active
    "ict_mss_active",                 # Market Structure Shift (bullish or bearish) detected
    "ict_fvg_present",                # Fair Value Gap present near current price
    "ict_breaker_block",              # Failed order block flipped to opposite use
    "ict_power_of_3_phase",           # AMD phase score: accumulation=0, manipulation=0.5, distribution=1
    "ict_previous_day_high_near",     # price is within 1 ATR of previous day's high
    "ict_weekly_bias_bullish",        # weekly candle direction is bullish
    "ict_weekly_bias_score",          # normalised weekly directional bias (−1 to +1 mapped to 0–1)
]

# === v7 Novel Discovery — 5 original signals never defined in any trading methodology ===
NOVEL_FEATURE_NAMES = GANN_ICT_FEATURE_NAMES + [
    # Entropy Collapse Signal (ECS)
    "novel_ecs_active",            # all sub-systems simultaneously at minimum entropy (coiled spring)
    "novel_ecs_strength",          # 0–1 strength of entropy collapse
    "novel_ecs_energy_stored",     # compression energy loaded at collapse point
    # Nakshatra Velocity Anomaly (NVA)
    "novel_nva_active",            # lunar transition + Gann rotation velocity anomaly
    "novel_nva_strength",          # 0–1 strength of rotation velocity spike
    "novel_nva_rot_velocity",      # angular velocity of price rotation (deg / 3 bars)
    # Planetary Aspect Compression Lock (PACL)
    "novel_pacl_active",           # 3+ planetary aspects holding a structural lock
    "novel_pacl_strength",         # 0–1 strength of astro pressure lock
    "novel_pacl_aspect_count",     # number of active planetary aspects
    # Reliability Inversion Signal (RIS)
    "novel_ris_active",            # manufactured conflict → deceptive move about to reverse
    "novel_ris_strength",          # 0–1 strength of inversion
    "novel_ris_conflict_score",    # raw conflict score at inversion
    # Cycle Alignment Resonance (CAR)
    "novel_car_active",            # Elliott + Gann + lunar three-system resonance
    "novel_car_strength",          # 0–1 resonance strength
    "novel_car_cycle_align",       # Elliott cycle alignment score component
    # Cross-signal composite
    "novel_signal_count",          # number of novel signals active simultaneously
    "novel_combined_strength",     # directional-weighted average strength of active signals
]

# v8: adds Volume-Structure Trend Bias (VSTB) signal features
VSTB_FEATURE_NAMES = NOVEL_FEATURE_NAMES + [
    # Volume-Structure Trend Bias (VSTB) — empirically strongest predictor (88% at 4h)
    "novel_vstb_active",           # quiet vol in uptrend OR loud vol in downtrend
    "novel_vstb_strength",         # 0–1 strength of volume-trend confluence
    "novel_vstb_vol_z",            # raw volume z-score at signal bar
]

# v9: adds FRV signal + full ICT engine context (25 ICT + 2 FRV + 3 ICT composite = 30 new features)
ICT_EXTENDED_FEATURE_NAMES = VSTB_FEATURE_NAMES + [
    # === FRV signal (Fade Reversal — 54.3% at 15m, 19,246 events, 26yr) ===
    "novel_frv_active",            # fade reversal setup active
    "novel_frv_strength",          # 0–1 strength of fade reversal setup
    # === ICT Composite Signal ===
    "novel_ict_signal_active",     # ICT composite signal active (score>=0.30, 2+ conditions)
    "novel_ict_signal_strength",   # 0–1 ICT composite strength
    "novel_ict_signal_score",      # raw ICT setup score (0–1 alignment of concepts)
    # === ICT Engine — PD Array ===
    "ict_pd_premium",              # price in premium zone (>55% of HTF range) → sell zone
    "ict_pd_discount",             # price in discount zone (<45% of HTF range) → buy zone
    "ict_pd_equilibrium",          # price near equilibrium (45–55%) → neutral
    "ict_pd_price_position_pct",   # normalised price position in range (0=bottom, 1=top)
    # === ICT Engine — HTF Bias ===
    "ict_htf_daily_bullish",       # today's price above prior day's midpoint
    "ict_htf_daily_bearish",       # today's price below prior day's midpoint
    "ict_htf_weekly_bullish",      # price above weekly range midpoint
    "ict_htf_weekly_bearish",      # price below weekly range midpoint
    # === ICT Engine — Session Setups ===
    "ict_judas_swing_buy",         # Judas Swing detected — false down spike before real up move
    "ict_judas_swing_sell",        # Judas Swing detected — false up spike before real down move
    "ict_judas_strength",          # strength of Judas rejection wick (0–1)
    "ict_silver_bullet_active",    # Silver Bullet setup active (10–11am or 2–3pm EST)
    "ict_silver_bullet_buy",       # Silver Bullet BUY direction (discount + FVG + displacement)
    "ict_silver_bullet_sell",      # Silver Bullet SELL direction (premium + FVG + displacement)
    # === ICT Engine — Gaps & Voids ===
    "ict_ndog_bullish",            # New Day Opening Gap up (price opened above prev close)
    "ict_ndog_bearish",            # New Day Opening Gap down
    "ict_nwog_bullish",            # New Week Opening Gap up
    "ict_nwog_bearish",            # New Week Opening Gap down
    "ict_liquidity_void_up",       # bullish liquidity void present (to be filled from above)
    "ict_liquidity_void_down",     # bearish liquidity void present
    # === ICT Engine — High-Probability Levels ===
    "ict_propulsion_block_near",   # price at or near propulsion block level
    "ict_propulsion_block_bull",   # bullish propulsion block being revisited
    "ict_propulsion_block_bear",   # bearish propulsion block being revisited
    "ict_ce_fvg_bull_tested",      # Consequent Encroachment: 50% of bullish FVG being tested
    "ict_ce_fvg_bear_tested",      # Consequent Encroachment: 50% of bearish FVG being tested
    # === MMS (Money Market Structure) Programs ===
    "ict_mms_buy_program",         # institutional buy program running (EMA bull + discount)
    "ict_mms_sell_program",        # institutional sell program running (EMA bear + premium)
    "ict_mms_program_strength",    # strength of detected MMS program (0–1)
    "ict_market_expanding",        # market is in expansion (avg range > 1.2 ATR)
    "ict_market_consolidating",    # market is in consolidation (avg range < 0.7 ATR)
    "ict_smt_divergence",          # SMT proxy: session momentum divergence detected
]

FEATURE_NAMES_BY_VERSION = {
    "v3_amd_cycle_state": FEATURE_NAMES,
    "v4_layered_execution": LAYERED_FEATURE_NAMES,
    "v5_elliott_unified": ELLIOTT_UNIFIED_FEATURE_NAMES,
    # Backward-compatible alias used by older model bundles.
    "v5_unified_elliott_cycle": ELLIOTT_UNIFIED_FEATURE_NAMES,
    "v6_gann_ict": GANN_ICT_FEATURE_NAMES,
    "v7_novel_discovery": NOVEL_FEATURE_NAMES,
    "v8_vstb": VSTB_FEATURE_NAMES,
    "v9_ict_extended": ICT_EXTENDED_FEATURE_NAMES,
}


def feature_names_for_version(feature_version: str | None = None) -> list[str]:
    version = str(feature_version or "v3_amd_cycle_state").strip().lower() or "v3_amd_cycle_state"
    if version == "v5_unified_elliott_cycle":
        version = "v5_elliott_unified"
    if version not in FEATURE_NAMES_BY_VERSION:
        raise ValueError(f"Unsupported feature version: {feature_version}")
    return FEATURE_NAMES_BY_VERSION[version]


def _compute_novel_layer(record: dict[str, Any]) -> list[float]:
    """Compute the 18 v7_novel_discovery extension features from the novel signal engine."""
    # Use pre-computed novel_signals if already in record (set by scanner.py),
    # otherwise compute on the fly (e.g. during inference / serving).
    ns = (record or {}).get("novel_signals")
    if not ns:
        try:
            from backend.engines.novel_signal_engine import run_novel_signals
            ns = run_novel_signals(record)
        except Exception:
            return [0.0] * 17

    ecs  = ns.get("ecs") or {}
    nva  = ns.get("nva") or {}
    pacl = ns.get("pacl") or {}
    ris  = ns.get("ris") or {}
    car  = ns.get("car") or {}

    return [
        1.0 if ecs.get("active") else 0.0,
        float(ecs.get("strength", 0.0) or 0.0),
        float((ecs.get("components") or {}).get("energy_stored_pct", 0.0) or 0.0),
        1.0 if nva.get("active") else 0.0,
        float(nva.get("strength", 0.0) or 0.0),
        min(1.0, float(nva.get("rot_velocity_deg", 0.0) or 0.0) / 90.0),
        1.0 if pacl.get("active") else 0.0,
        float(pacl.get("strength", 0.0) or 0.0),
        min(1.0, float((pacl.get("components") or {}).get("aspect_count", 0.0) or 0.0) / 6.0),
        1.0 if ris.get("active") else 0.0,
        float(ris.get("strength", 0.0) or 0.0),
        float((ris.get("components") or {}).get("conflict_score", 0.0) or 0.0),
        1.0 if car.get("active") else 0.0,
        float(car.get("strength", 0.0) or 0.0),
        float((car.get("components") or {}).get("cycle_alignment_score", 0.0) or 0.0),
        min(1.0, float(ns.get("novel_signal_count", 0) or 0) / 5.0),
        float(ns.get("novel_combined_strength", 0.0) or 0.0),
    ]


def _compute_vstb_layer(record: dict[str, Any]) -> list[float]:
    """Compute the 3 v8_vstb extension features (VSTB signal)."""
    ns = (record or {}).get("novel_signals")
    if not ns:
        try:
            from backend.engines.novel_signal_engine import run_novel_signals
            ns = run_novel_signals(record)
        except Exception:
            return [0.0] * 3
    vstb = ns.get("vstb") or {}
    comps = vstb.get("components") or {}
    return [
        1.0 if vstb.get("active") else 0.0,
        float(vstb.get("strength", 0.0) or 0.0),
        max(-1.0, min(1.0, float(comps.get("vol_z", 0.0) or 0.0) / 3.0)),  # normalised to [-1,1]
    ]


def _compute_ict_extended_layer(record: dict[str, Any]) -> list[float]:
    """
    Compute the 36 v9_ict_extended features.
    Reads from record["novel_signals"] (FRV + ICT composite) and record["ict"] (ICT engine).
    Returns exactly 36 floats matching ICT_EXTENDED_FEATURE_NAMES[-36:].
    """
    # Novel signals — FRV + ICT composite
    ns = (record or {}).get("novel_signals")
    if not ns:
        try:
            from backend.engines.novel_signal_engine import run_novel_signals
            ns = run_novel_signals(record)
        except Exception:
            ns = {}

    frv      = (ns or {}).get("frv") or {}
    ict_sig  = (ns or {}).get("ict") or {}
    ict_comp = (ict_sig.get("components") or {})

    frv_active   = 1.0 if frv.get("active") else 0.0
    frv_strength = float(frv.get("strength", 0.0) or 0.0)

    ict_sig_active   = 1.0 if ict_sig.get("active") else 0.0
    ict_sig_strength = float(ict_sig.get("strength", 0.0) or 0.0)
    ict_sig_score    = float(ict_comp.get("ict_setup_score", 0.0) or 0.0)

    # ICT engine context
    ict = (record or {}).get("ict") or {}

    def _b(key: str) -> float:
        return 1.0 if bool(ict.get(key, False)) else 0.0

    def _f(key: str) -> float:
        return float(ict.get(key, 0.0) or 0.0)

    sb_dir = str(ict.get("silver_bullet_direction", "NEUTRAL")).upper()

    return [
        # FRV signal
        frv_active,
        frv_strength,
        # ICT composite signal
        ict_sig_active,
        ict_sig_strength,
        ict_sig_score,
        # PD Array
        _b("pd_premium"),
        _b("pd_discount"),
        _b("pd_equilibrium"),
        _f("pd_price_position_pct"),
        # HTF Bias
        _b("htf_daily_bias_bullish"),
        _b("htf_daily_bias_bearish"),
        _b("htf_weekly_bias_bullish"),
        _b("htf_weekly_bias_bearish"),
        # Judas Swing
        _b("judas_swing_buy"),
        _b("judas_swing_sell"),
        _f("judas_strength"),
        # Silver Bullet
        _b("silver_bullet_active"),
        1.0 if (bool(ict.get("silver_bullet_active")) and sb_dir == "BUY")  else 0.0,
        1.0 if (bool(ict.get("silver_bullet_active")) and sb_dir == "SELL") else 0.0,
        # Gaps & Voids
        _b("ndog_bullish"),
        _b("ndog_bearish"),
        _b("nwog_bullish"),
        _b("nwog_bearish"),
        _b("liquidity_void_up"),
        _b("liquidity_void_down"),
        # High-probability levels
        _b("propulsion_block_near"),
        _b("propulsion_block_bullish"),
        _b("propulsion_block_bearish"),
        _b("ce_fvg_bullish_tested"),
        _b("ce_fvg_bearish_tested"),
        # MMS programs
        _b("mms_buy_program"),
        _b("mms_sell_program"),
        _f("mms_program_strength"),
        _b("market_is_expanding"),
        _b("market_is_consolidating"),
        _b("smt_session_divergence"),
    ]


_GANN_MASTER_NUMBERS = [x * 144 for x in range(1, 30)]  # 144, 288, 432 … 4176


def _compute_gann_ict_layer(record: dict[str, Any]) -> list[float]:
    """Compute the 17 v6_gann_ict extension features."""
    gann_astro_math = (record or {}).get("gann_astro_math") or {}
    time_engine     = (record or {}).get("time_engine") or {}
    participation   = (record or {}).get("participation") or {}
    location        = (record or {}).get("location") or {}
    trigger         = (record or {}).get("trigger") or {}
    cycle           = (record or {}).get("cycle") or {}
    structure       = (record or {}).get("structure") or {}
    phase           = str((record or {}).get("phase") or "NEUTRAL").upper()
    state           = (record or {}).get("state") or {}

    # --- Gann fan angle features ---
    tangent_deg = float(gann_astro_math.get("tangent_angle_deg", 0.0) or 0.0)
    gann_1x1_angle_above  = 1.0 if tangent_deg >= 45.0 else 0.0
    gann_1x2_angle_active = 1.0 if tangent_deg >= 63.43 else 0.0
    gann_2x1_angle_active = 1.0 if 0.0 < tangent_deg <= 26.57 else 0.0

    sq9_dist = float(gann_astro_math.get("degree_projection_distance", 1.0) or 1.0)
    gann_sq9_next_level_distance = max(0.0, min(1.0, sq9_dist / 360.0))

    gann_time_cycle_90d_window  = 1.0 if bool(time_engine.get("gann_90_cycle_active", False)) else 0.0
    gann_time_cycle_360d_window = 1.0 if bool(time_engine.get("gann_180_cycle_active", False)) else 0.0

    price = float(state.get("price", 0.0) or 0.0)
    gann_master_price_number = 0.0
    if price > 0:
        for mn in _GANN_MASTER_NUMBERS:
            if abs(price - mn) / mn < 0.005:  # within 0.5%
                gann_master_price_number = 1.0
                break

    # --- ICT killzone & precision features ---
    ict_killzone_london_open = 1.0 if bool(participation.get("london_open", False)) else 0.0
    ict_killzone_ny_open     = 1.0 if bool(participation.get("newyork_open", False)) else 0.0

    # OTE: 61.8–79% retracement into a FVG
    fvg_bullish = bool(location.get("bullish_fvg_near", False))
    fvg_bearish = bool(location.get("bearish_fvg_near", False))
    retracement = float(gann_astro_math.get("cosine_retracement", 0.0) or 0.0)
    ict_optimal_trade_entry = 1.0 if (fvg_bullish or fvg_bearish) and 0.618 <= retracement <= 0.79 else 0.0

    ict_mss_active  = 1.0 if (bool(trigger.get("mss_bullish", False)) or bool(trigger.get("mss_bearish", False))) else 0.0
    ict_fvg_present = 1.0 if (fvg_bullish or fvg_bearish) else 0.0
    # breaker_block is only set by the ICT engine (record["ict"]), not in location
    ict_ctx = (record or {}).get("ict") or {}
    ict_breaker_block = 1.0 if bool(ict_ctx.get("propulsion_block_near", False)) else 0.0

    # Power of 3: accumulation=0.0, manipulation=0.5, distribution=1.0
    _p3_map = {"ACCUMULATION": 0.0, "MANIPULATION": 0.5, "DISTRIBUTION": 1.0}
    ict_power_of_3_phase = _p3_map.get(phase, 0.25)

    # previous_day_high_near: approximated via pd_range_midpoint proximity in ICT engine
    ict_previous_day_high_near = 1.0 if bool(ict_ctx.get("propulsion_block_bullish", False) or
                                              ict_ctx.get("propulsion_block_bearish", False)) else 0.0

    # Weekly bias — from structure if available, otherwise fall back to ICT engine
    weekly_dir = str(structure.get("weekly_bias") or structure.get("weekly_direction") or "").upper()
    if not weekly_dir or weekly_dir not in {"UP", "BULLISH", "BUY", "DOWN", "BEARISH", "SELL"}:
        # Fall back to ICT engine HTF weekly bias
        if ict_ctx.get("htf_weekly_bias_bullish"):
            weekly_dir = "BULLISH"
        elif ict_ctx.get("htf_weekly_bias_bearish"):
            weekly_dir = "BEARISH"
    ict_weekly_bias_bullish = 1.0 if weekly_dir in {"UP", "BULLISH", "BUY"} else 0.0
    weekly_score = float(structure.get("weekly_bias_score", 0.0) or 0.0)
    if weekly_score == 0.0:
        # Use ICT htf_weekly_bias as proxy: +1 = bullish, -1 = bearish
        if ict_ctx.get("htf_weekly_bias_bullish"):
            weekly_score = 1.0
        elif ict_ctx.get("htf_weekly_bias_bearish"):
            weekly_score = -1.0
    # Map from [-1, 1] or any range to [0, 1]
    ict_weekly_bias_score = max(0.0, min(1.0, (weekly_score + 1.0) / 2.0))

    return [
        gann_1x1_angle_above,
        gann_1x2_angle_active,
        gann_2x1_angle_active,
        gann_sq9_next_level_distance,
        gann_time_cycle_90d_window,
        gann_time_cycle_360d_window,
        gann_master_price_number,
        ict_killzone_london_open,
        ict_killzone_ny_open,
        ict_optimal_trade_entry,
        ict_mss_active,
        ict_fvg_present,
        ict_breaker_block,
        ict_power_of_3_phase,
        ict_previous_day_high_near,
        ict_weekly_bias_bullish,
        ict_weekly_bias_score,
    ]


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
    if version not in {"v4_layered_execution", "v5_elliott_unified", "v6_gann_ict",
                       "v7_novel_discovery", "v8_vstb", "v9_ict_extended"}:
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

    if version == "v5_elliott_unified":
        return [float(x) for x in (row + layered + elliott_layer)]

    # v6_gann_ict — extends v5 with 17 Gann-fan + ICT features
    gann_ict_layer = _compute_gann_ict_layer(record)
    if version == "v6_gann_ict":
        return [float(x) for x in (row + layered + elliott_layer + gann_ict_layer)]

    # v7_novel_discovery — extends v6 with 18 novel cross-domain signal features
    novel_layer = _compute_novel_layer(record)
    if version == "v7_novel_discovery":
        return [float(x) for x in (row + layered + elliott_layer + gann_ict_layer + novel_layer)]

    # v8_vstb — extends v7 with 3 VSTB features (Volume-Structure Trend Bias)
    vstb_layer = _compute_vstb_layer(record)
    if version == "v8_vstb":
        return [float(x) for x in (row + layered + elliott_layer + gann_ict_layer + novel_layer + vstb_layer)]

    # v9_ict_extended — extends v8 with 35 ICT engine + FRV + ICT composite features
    ict_ext_layer = _compute_ict_extended_layer(record)
    return [float(x) for x in (row + layered + elliott_layer + gann_ict_layer + novel_layer + vstb_layer + ict_ext_layer)]


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
