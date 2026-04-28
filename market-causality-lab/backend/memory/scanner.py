import math

from backend.core.state_engine import build_state
from backend.physics.physics_engine import physics_engine
from backend.gann.gann_engine import gann_engine
from backend.engines.liquidity_engine import liquidity_engine
from backend.engines.phase_engine import phase_engine
from backend.engines.trap_engine import trap_engine
from backend.engines.time_compression_engine import time_compression_engine
from backend.engines.order_flow_engine import order_flow_engine
from backend.sync.sync_engine import sync_engine
from backend.engines.amd_ifvg_engine import amd_ifvg_latest


def _extract_news_context(sub_df):
    if sub_df.empty:
        return {
            "event_active": False,
            "event_count": 0,
            "high_impact_active": False,
            "impact_score": 0,
            "aspect_event_count": 0,
            "conjunction_count": 0,
            "square_count": 0,
            "opposition_count": 0,
            "trine_count": 0,
            "sextile_count": 0,
            "ingress_event_count": 0,
            "nakshatra_event_count": 0,
            "gann_event_count": 0,
            "eclipse_event_count": 0,
        }

    last_row = sub_df.iloc[-1]
    event_count = int(last_row.get("news_event_count", 0) or 0)
    high_impact_count = int(last_row.get("news_high_impact_count", 0) or 0)
    impact_score = int(last_row.get("news_impact_score", 0) or 0)
    aspect_event_count = int(last_row.get("news_aspect_event_count", 0) or 0)
    conjunction_count = int(last_row.get("news_conjunction_count", 0) or 0)
    square_count = int(last_row.get("news_square_count", 0) or 0)
    opposition_count = int(last_row.get("news_opposition_count", 0) or 0)
    trine_count = int(last_row.get("news_trine_count", 0) or 0)
    sextile_count = int(last_row.get("news_sextile_count", 0) or 0)
    ingress_event_count = int(last_row.get("news_ingress_event_count", 0) or 0)
    nakshatra_event_count = int(last_row.get("news_nakshatra_event_count", 0) or 0)
    gann_event_count = int(last_row.get("news_gann_event_count", 0) or 0)
    eclipse_event_count = int(last_row.get("news_eclipse_event_count", 0) or 0)

    return {
        "event_active": bool(last_row.get("news_event_active", False)),
        "event_count": event_count,
        "high_impact_active": high_impact_count > 0,
        "impact_score": impact_score,
        "aspect_event_count": aspect_event_count,
        "conjunction_count": conjunction_count,
        "square_count": square_count,
        "opposition_count": opposition_count,
        "trine_count": trine_count,
        "sextile_count": sextile_count,
        "ingress_event_count": ingress_event_count,
        "nakshatra_event_count": nakshatra_event_count,
        "gann_event_count": gann_event_count,
        "eclipse_event_count": eclipse_event_count,
    }


def _extract_structure_context(sub_df):
    closes = sub_df["close"].astype(float)
    highs = sub_df["high"].astype(float)
    lows = sub_df["low"].astype(float)

    if len(closes) < 25:
        return {
            "bos_up": False,
            "bos_down": False,
            "choch_up": False,
            "choch_down": False,
            "hh_hl": False,
            "ll_lh": False,
            "trend_strength": 0.0,
            "regime": "TRANSITION",
        }

    # Swing structure approximation over recent windows.
    high_10 = float(highs.tail(10).max())
    low_10 = float(lows.tail(10).min())
    high_prev_10 = float(highs.iloc[-20:-10].max())
    low_prev_10 = float(lows.iloc[-20:-10].min())

    bos_up = high_10 > high_prev_10
    bos_down = low_10 < low_prev_10

    # CHOCH approximation via momentum sign flip + recent break.
    mom_recent = float(closes.iloc[-1] - closes.iloc[-5])
    mom_prev = float(closes.iloc[-6] - closes.iloc[-11])
    choch_up = bool(mom_prev <= 0 and mom_recent > 0 and bos_up)
    choch_down = bool(mom_prev >= 0 and mom_recent < 0 and bos_down)

    hh_hl = bool(high_10 >= high_prev_10 and low_10 >= low_prev_10)
    ll_lh = bool(high_10 <= high_prev_10 and low_10 <= low_prev_10)

    tr = (highs - lows).tail(20)
    tr_mean = float(tr.mean()) if len(tr) else 0.0
    trend_strength = abs(float(closes.iloc[-1] - closes.iloc[-20])) / max(1e-9, tr_mean)

    if hh_hl and trend_strength > 1.0:
        regime = "TREND_UP"
    elif ll_lh and trend_strength > 1.0:
        regime = "TREND_DOWN"
    elif tr_mean > 0 and abs(float(closes.iloc[-1] - closes.iloc[-20])) < tr_mean * 0.6:
        regime = "RANGE"
    else:
        regime = "TRANSITION"

    return {
        "bos_up": bos_up,
        "bos_down": bos_down,
        "choch_up": choch_up,
        "choch_down": choch_down,
        "hh_hl": hh_hl,
        "ll_lh": ll_lh,
        "trend_strength": float(trend_strength),
        "regime": regime,
    }


def _extract_reliability_context(state, gann, liquidity, phase, signal, trap, compression, structure):
    # Lightweight directional force voting from existing engines.
    buy_force = 0.0
    sell_force = 0.0

    if state.get("trend") == "UP":
        buy_force += 1.0
    else:
        sell_force += 1.0

    if liquidity.get("type") == "SELL_SIDE_SWEEP":
        buy_force += 1.0
    elif liquidity.get("type") == "BUY_SIDE_SWEEP":
        sell_force += 1.0

    if gann.get("zone") == "REVERSAL":
        sell_force += 0.7
    else:
        buy_force += 0.4

    if phase == "EXPANSION":
        if state.get("trend") == "UP":
            buy_force += 0.6
        else:
            sell_force += 0.6

    if structure.get("bos_up") or structure.get("hh_hl"):
        buy_force += 0.5
    if structure.get("bos_down") or structure.get("ll_lh"):
        sell_force += 0.5

    total_force = max(1e-9, buy_force + sell_force)
    dominant = max(buy_force, sell_force)
    conflict = min(buy_force, sell_force) / total_force

    trap_prob = float((trap or {}).get("probability", 0.0) or 0.0)
    comp_bonus = 0.1 if bool((compression or {}).get("breakout_near", False)) else 0.0
    reliability = (dominant / total_force) * (1.0 - 0.25 * conflict) * (1.0 - 0.2 * trap_prob) + comp_bonus
    reliability = max(0.0, min(1.0, reliability))

    sig = str(signal or "WAIT").upper()
    aligns_buy = sig in {"BUY", "STRONG BUY"} and buy_force >= sell_force
    aligns_sell = sig in {"SELL", "STRONG SELL"} and sell_force >= buy_force
    confluence_ready = bool((aligns_buy or aligns_sell) and reliability >= 0.55)

    return {
        "buy_force": float(buy_force),
        "sell_force": float(sell_force),
        "conflict_score": float(conflict),
        "reliability_score": float(reliability),
        "confluence_ready": confluence_ready,
    }


def _extract_cycle_context(sub_df):
    if sub_df.empty:
        return {
            "moon_phase_position": 0.0,
            "nakshatra_sequence": 0.0,
            "gann_degree": 0.0,
            "days_to_next_node": 365.0,
            "planetary_active": False,
            "planetary_aspect_active": False,
            "planetary_conjunction_active": False,
            "planetary_square_active": False,
            "planetary_opposition_active": False,
            "retrograde_active": False,
            "nakshatra_transition_active": False,
            "moon_eclipse_active": False,
            "moon_new_active": False,
            "moon_full_active": False,
            "gann_pressure_window": False,
            "gann_station_active": False,
            "gann_synodic_active": False,
            "gann_time_cycle_exact": False,
            "time_cycle_active": False,
        }

    last_row = sub_df.iloc[-1]
    return {
        "moon_phase_position": float(last_row.get("cycle_moon_phase_position", 0.0) or 0.0),
        "nakshatra_sequence": float(last_row.get("cycle_nakshatra_sequence", 0.0) or 0.0),
        "gann_degree": float(last_row.get("cycle_gann_degree", 0.0) or 0.0),
        "days_to_next_node": float(last_row.get("cycle_days_to_next_node", 365.0) or 365.0),
        "planetary_active": bool(last_row.get("cycle_planetary_active", False)),
        "planetary_aspect_active": bool(last_row.get("cycle_planetary_aspect_active", False)),
        "planetary_conjunction_active": bool(last_row.get("cycle_planetary_conjunction_active", False)),
        "planetary_square_active": bool(last_row.get("cycle_planetary_square_active", False)),
        "planetary_opposition_active": bool(last_row.get("cycle_planetary_opposition_active", False)),
        "retrograde_active": bool(last_row.get("cycle_retrograde_active", False)),
        "nakshatra_transition_active": bool(last_row.get("cycle_nakshatra_transition_active", False)),
        "moon_eclipse_active": bool(last_row.get("cycle_moon_eclipse_active", False)),
        "moon_new_active": bool(last_row.get("cycle_moon_new_active", False)),
        "moon_full_active": bool(last_row.get("cycle_moon_full_active", False)),
        "gann_pressure_window": bool(last_row.get("cycle_gann_pressure_window", False)),
        "gann_station_active": bool(last_row.get("cycle_gann_station_active", False)),
        "gann_synodic_active": bool(last_row.get("cycle_gann_synodic_active", False)),
        "gann_time_cycle_exact": bool(last_row.get("cycle_gann_time_cycle_exact", False)),
        "time_cycle_active": bool(last_row.get("cycle_time_cycle_active", False)),
    }


def _extract_time_context(cycle, phase):
    moon_phase_position = float((cycle or {}).get("moon_phase_position", 0.0) or 0.0)
    gann_degree = float((cycle or {}).get("gann_degree", 0.0) or 0.0) % 360.0
    days_to_next_node = float((cycle or {}).get("days_to_next_node", 365.0) or 365.0)

    planetary_aspects_active = bool((cycle or {}).get("planetary_aspect_active", False))
    planetary_conjunction_active = bool((cycle or {}).get("planetary_conjunction_active", False))
    planetary_square_active = bool((cycle or {}).get("planetary_square_active", False))
    planetary_opposition_active = bool((cycle or {}).get("planetary_opposition_active", False))
    retrograde_active = bool((cycle or {}).get("retrograde_active", False))
    nakshatra_transition_active = bool((cycle or {}).get("nakshatra_transition_active", False))
    moon_eclipse_active = bool((cycle or {}).get("moon_eclipse_active", False))
    moon_new_active = bool((cycle or {}).get("moon_new_active", False))
    moon_full_active = bool((cycle or {}).get("moon_full_active", False))
    gann_pressure_window = bool((cycle or {}).get("gann_pressure_window", False))
    gann_station_active = bool((cycle or {}).get("gann_station_active", False))
    gann_synodic_active = bool((cycle or {}).get("gann_synodic_active", False))
    gann_time_cycle_exact = bool((cycle or {}).get("gann_time_cycle_exact", False))

    moon_key = min(abs(moon_phase_position - key) for key in (0.0, 0.25, 0.5, 0.75, 1.0)) <= 0.08
    gann_45 = min(abs(gann_degree - 45.0), abs(gann_degree - 135.0), abs(gann_degree - 225.0), abs(gann_degree - 315.0)) <= 12.0
    gann_90 = min(abs(gann_degree - 0.0), abs(gann_degree - 90.0), abs(gann_degree - 180.0), abs(gann_degree - 270.0), abs(gann_degree - 360.0)) <= 12.0
    gann_180 = min(abs(gann_degree - 180.0), abs(gann_degree - 0.0), abs(gann_degree - 360.0)) <= 16.0
    sq9_level_near = bool(gann_45 or gann_90 or gann_180)
    time_cycle_window = bool((cycle or {}).get("time_cycle_active", False) or days_to_next_node <= 3.0)

    score = 0.0
    score += 0.1 if planetary_aspects_active else 0.0
    score += 0.06 if planetary_conjunction_active else 0.0
    score += 0.08 if planetary_square_active else 0.0
    score += 0.08 if planetary_opposition_active else 0.0
    score += 0.15 if moon_key else 0.0
    score += 0.12 if moon_eclipse_active else 0.0
    score += 0.05 if moon_new_active else 0.0
    score += 0.05 if moon_full_active else 0.0
    score += 0.1 if retrograde_active else 0.0
    score += 0.15 if nakshatra_transition_active else 0.0
    score += 0.15 if sq9_level_near else 0.0
    score += 0.1 if gann_pressure_window else 0.0
    score += 0.08 if gann_station_active else 0.0
    score += 0.08 if gann_synodic_active else 0.0
    score += 0.08 if gann_time_cycle_exact else 0.0
    score += 0.15 if time_cycle_window else 0.0
    score += 0.1 if str(phase or "").upper() == "EXPANSION" else 0.0
    score = max(0.0, min(1.0, score))

    reasons = []
    if planetary_aspects_active:
        reasons.append("planetary aspects active")
    if planetary_conjunction_active:
        reasons.append("planetary conjunction")
    if planetary_square_active:
        reasons.append("planetary square")
    if planetary_opposition_active:
        reasons.append("planetary opposition")
    if moon_key:
        reasons.append("moon phase window")
    if moon_eclipse_active:
        reasons.append("eclipse window")
    if moon_new_active:
        reasons.append("new moon")
    if moon_full_active:
        reasons.append("full moon")
    if retrograde_active:
        reasons.append("retrograde/station window")
    if nakshatra_transition_active:
        reasons.append("nakshatra transition")
    if sq9_level_near:
        reasons.append("SQ9/Gann angle proximity")
    if gann_pressure_window:
        reasons.append("Gann pressure window")
    if gann_station_active:
        reasons.append("Gann station node")
    if gann_synodic_active:
        reasons.append("Gann synodic cycle")
    if gann_time_cycle_exact:
        reasons.append("exact Gann time cycle")
    if time_cycle_window:
        reasons.append("Gann time cycle active")
    if not reasons:
        reasons.append("no major astro/Gann timing window")

    return {
        "planetary_aspects_active": planetary_aspects_active,
        "planetary_conjunction_active": planetary_conjunction_active,
        "planetary_square_active": planetary_square_active,
        "planetary_opposition_active": planetary_opposition_active,
        "moon_phase_active": moon_key,
        "retrograde_active": retrograde_active,
        "nakshatra_transition_active": nakshatra_transition_active,
        "moon_eclipse_active": moon_eclipse_active,
        "moon_new_active": moon_new_active,
        "moon_full_active": moon_full_active,
        "sq9_level_active": sq9_level_near,
        "gann_45_cycle_active": gann_45,
        "gann_90_cycle_active": gann_90,
        "gann_180_cycle_active": gann_180,
        "gann_pressure_window": gann_pressure_window,
        "gann_station_active": gann_station_active,
        "gann_synodic_active": gann_synodic_active,
        "gann_time_cycle_exact": gann_time_cycle_exact,
        "time_cycle_active": time_cycle_window,
        "time_window_score": score,
        "timing_text": "; ".join(reasons),
    }


def _extract_location_context(sub_df):
    if sub_df.empty or len(sub_df) < 5:
        return {
            "bullish_fvg_near": False,
            "bearish_fvg_near": False,
            "bullish_order_block_near": False,
            "bearish_order_block_near": False,
            "equal_highs_near": False,
            "equal_lows_near": False,
            "session_high_near": False,
            "session_low_near": False,
            "at_key_level": False,
            "zone_score": 0.0,
            "high_probability_zones": [],
        }

    last = sub_df.iloc[-1]
    close = float(last["close"])
    highs = sub_df["high"].astype(float)
    lows = sub_df["low"].astype(float)
    opens = sub_df["open"].astype(float)
    times = sub_df.get("time")
    avg_range = float((highs - lows).tail(20).mean() or 0.0)
    tolerance = max(1e-9, avg_range * 0.2)

    bullish_fvg = bool(float(lows.iloc[-1]) > float(highs.iloc[-3]))
    bearish_fvg = bool(float(highs.iloc[-1]) < float(lows.iloc[-3]))
    bullish_fvg_level = float(highs.iloc[-3]) if bullish_fvg else None
    bearish_fvg_level = float(lows.iloc[-3]) if bearish_fvg else None

    bullish_ob_level = None
    bearish_ob_level = None
    lookback = min(len(sub_df), 20)
    for idx in range(len(sub_df) - lookback, len(sub_df) - 1):
        if idx < 0 or idx + 1 >= len(sub_df):
            continue
        candle_open = float(opens.iloc[idx])
        candle_close = float(sub_df["close"].astype(float).iloc[idx])
        next_close = float(sub_df["close"].astype(float).iloc[idx + 1])
        prev_high = float(highs.iloc[max(0, idx - 1):idx + 1].max())
        prev_low = float(lows.iloc[max(0, idx - 1):idx + 1].min())
        if candle_close < candle_open and next_close > prev_high:
            bullish_ob_level = candle_open
        if candle_close > candle_open and next_close < prev_low:
            bearish_ob_level = candle_open

    recent_highs = sorted(float(x) for x in highs.tail(20).tolist())
    recent_lows = sorted(float(x) for x in lows.tail(20).tolist())
    equal_highs = len(recent_highs) >= 2 and abs(recent_highs[-1] - recent_highs[-2]) <= tolerance
    equal_lows = len(recent_lows) >= 2 and abs(recent_lows[0] - recent_lows[1]) <= tolerance
    equal_high_level = recent_highs[-1] if equal_highs else None
    equal_low_level = recent_lows[0] if equal_lows else None

    session_high = None
    session_low = None
    if times is not None:
        time_series = times.iloc[-min(len(sub_df), 24):]
        time_series = getattr(time_series, "dt", None)
        if time_series is not None:
            hour_mask = sub_df.iloc[-min(len(sub_df), 24):]["time"].dt.hour.isin([7, 8, 9, 13, 14, 15])
            session_df = sub_df.iloc[-min(len(sub_df), 24):][hour_mask]
            if not session_df.empty:
                session_high = float(session_df["high"].max())
                session_low = float(session_df["low"].min())

    session_high_near = bool(session_high is not None and abs(close - session_high) <= tolerance)
    session_low_near = bool(session_low is not None and abs(close - session_low) <= tolerance)
    bullish_fvg_near = bool(bullish_fvg_level is not None and abs(close - bullish_fvg_level) <= tolerance * 1.5)
    bearish_fvg_near = bool(bearish_fvg_level is not None and abs(close - bearish_fvg_level) <= tolerance * 1.5)
    bullish_order_block_near = bool(bullish_ob_level is not None and abs(close - bullish_ob_level) <= tolerance * 1.5)
    bearish_order_block_near = bool(bearish_ob_level is not None and abs(close - bearish_ob_level) <= tolerance * 1.5)
    equal_highs_near = bool(equal_high_level is not None and abs(close - equal_high_level) <= tolerance)
    equal_lows_near = bool(equal_low_level is not None and abs(close - equal_low_level) <= tolerance)

    proximity_hits = [
        bullish_fvg_near,
        bearish_fvg_near,
        bullish_order_block_near,
        bearish_order_block_near,
        equal_highs_near,
        equal_lows_near,
        session_high_near,
        session_low_near,
    ]
    zone_score = float(sum(1.0 for hit in proximity_hits if hit) / max(1, len(proximity_hits)))
    high_probability_zones = []
    if bullish_fvg_near:
        high_probability_zones.append("bullish_fvg")
    if bearish_fvg_near:
        high_probability_zones.append("bearish_fvg")
    if bullish_order_block_near:
        high_probability_zones.append("bullish_order_block")
    if bearish_order_block_near:
        high_probability_zones.append("bearish_order_block")
    if equal_highs_near:
        high_probability_zones.append("equal_highs")
    if equal_lows_near:
        high_probability_zones.append("equal_lows")
    if session_high_near:
        high_probability_zones.append("session_high")
    if session_low_near:
        high_probability_zones.append("session_low")

    return {
        "bullish_fvg_near": bullish_fvg_near,
        "bearish_fvg_near": bearish_fvg_near,
        "bullish_order_block_near": bullish_order_block_near,
        "bearish_order_block_near": bearish_order_block_near,
        "equal_highs_near": equal_highs_near,
        "equal_lows_near": equal_lows_near,
        "session_high_near": session_high_near,
        "session_low_near": session_low_near,
        "at_key_level": bool(any(proximity_hits)),
        "zone_score": zone_score,
        "high_probability_zones": high_probability_zones,
    }


def _extract_trigger_context(sub_df, liquidity, structure):
    if sub_df.empty or len(sub_df) < 5:
        return {
            "sweep_buy_side": False,
            "sweep_sell_side": False,
            "mss_bullish": False,
            "mss_bearish": False,
            "bos_bullish": False,
            "bos_bearish": False,
            "displacement_bullish": False,
            "displacement_bearish": False,
            "trigger_confirmed": False,
            "trigger_direction": "WAIT",
        }

    opens = sub_df["open"].astype(float)
    closes = sub_df["close"].astype(float)
    highs = sub_df["high"].astype(float)
    lows = sub_df["low"].astype(float)
    bodies = (closes - opens).abs()
    body_mean = float(bodies.tail(20).mean() or 0.0)
    range_mean = float((highs - lows).tail(20).mean() or 0.0)

    def _bar_displacement(idx: int) -> tuple[bool, bool]:
        bar_open = float(opens.iloc[idx])
        bar_close = float(closes.iloc[idx])
        bar_high = float(highs.iloc[idx])
        bar_low = float(lows.iloc[idx])
        bar_body = abs(bar_close - bar_open)
        is_displacement = bool(
            bar_body >= max(1e-9, body_mean * 1.2)
            and (bar_high - bar_low) >= max(1e-9, range_mean * 1.1)
        )
        bullish = bool(is_displacement and bar_close > bar_open and (bar_high - bar_close) <= bar_body * 0.45)
        bearish = bool(is_displacement and bar_close < bar_open and (bar_close - bar_low) <= bar_body * 0.45)
        return bullish, bearish

    recent_start = max(10, len(sub_df) - 4)
    recent_sell_side_sweeps = 0
    recent_buy_side_sweeps = 0
    recent_disp_bullish = False
    recent_disp_bearish = False
    for idx in range(recent_start, len(sub_df)):
        prev_window_start = max(0, idx - 10)
        prev_high = float(highs.iloc[prev_window_start:idx].max()) if idx > prev_window_start else float(highs.iloc[idx])
        prev_low = float(lows.iloc[prev_window_start:idx].min()) if idx > prev_window_start else float(lows.iloc[idx])
        close_i = float(closes.iloc[idx])
        if close_i > prev_high:
            recent_buy_side_sweeps += 1
        if close_i < prev_low:
            recent_sell_side_sweeps += 1
        disp_bull, disp_bear = _bar_displacement(idx)
        recent_disp_bullish = recent_disp_bullish or disp_bull
        recent_disp_bearish = recent_disp_bearish or disp_bear

    sweep_buy_side = bool(str(liquidity.get("type") or "") == "BUY_SIDE_SWEEP" or recent_buy_side_sweeps > 0)
    sweep_sell_side = bool(str(liquidity.get("type") or "") == "SELL_SIDE_SWEEP" or recent_sell_side_sweeps > 0)
    bos_bullish = bool(structure.get("bos_up", False))
    bos_bearish = bool(structure.get("bos_down", False))
    mss_bullish = bool(structure.get("choch_up", False))
    mss_bearish = bool(structure.get("choch_down", False))

    displacement_bullish = recent_disp_bullish
    displacement_bearish = recent_disp_bearish

    long_trigger = bool(sweep_sell_side and (mss_bullish or bos_bullish) and displacement_bullish)
    short_trigger = bool(sweep_buy_side and (mss_bearish or bos_bearish) and displacement_bearish)
    trigger_direction = "BUY" if long_trigger and not short_trigger else "SELL" if short_trigger and not long_trigger else "WAIT"

    return {
        "sweep_buy_side": sweep_buy_side,
        "sweep_sell_side": sweep_sell_side,
        "mss_bullish": mss_bullish,
        "mss_bearish": mss_bearish,
        "bos_bullish": bos_bullish,
        "bos_bearish": bos_bearish,
        "displacement_bullish": displacement_bullish,
        "displacement_bearish": displacement_bearish,
        "trigger_confirmed": bool(trigger_direction in {"BUY", "SELL"}),
        "trigger_direction": trigger_direction,
    }


def _extract_participation_context(sub_df, news, state):
    if sub_df.empty:
        return {
            "news_active": False,
            "volume_spike": False,
            "london_open": False,
            "london_session": False,
            "newyork_open": False,
            "newyork_session": False,
            "participation_strength": "weak",
            "participation_score": 0.0,
        }

    last = sub_df.iloc[-1]
    current_time = last.get("time")
    hour = int(current_time.hour) if current_time is not None and hasattr(current_time, "hour") else -1
    london_open = hour in {7, 8, 9}
    london_session = hour in {6, 7, 8, 9, 10, 11}
    newyork_open = hour in {13, 14, 15}
    newyork_session = hour in {12, 13, 14, 15, 16}

    volume_spike = False
    if "volume" in sub_df.columns:
        volume = sub_df["volume"].astype(float)
        volume_spike = bool(float(volume.iloc[-1] or 0.0) >= max(1e-9, float(volume.tail(20).mean() or 0.0) * 1.5))

    news_active = bool((news or {}).get("high_impact_active", False) or (news or {}).get("event_active", False))
    impact_score = float((news or {}).get("impact_score", 0.0) or 0.0)
    volatility = float((state or {}).get("volatility", 0.0) or 0.0)

    participation_score = 0.0
    participation_score += min(1.0, impact_score / 6.0) * 0.35
    participation_score += 0.25 if volume_spike else 0.0
    participation_score += 0.15 if london_session else 0.0
    participation_score += 0.05 if london_open else 0.0
    participation_score += 0.15 if newyork_session else 0.0
    participation_score += 0.05 if newyork_open else 0.0
    participation_score += min(0.2, volatility / 100.0)
    participation_score = max(0.0, min(1.0, participation_score))

    if participation_score >= 0.7:
        strength = "strong"
    elif participation_score >= 0.4:
        strength = "medium"
    else:
        strength = "weak"

    return {
        "news_active": news_active,
        "volume_spike": volume_spike,
        "london_open": london_open,
        "london_session": london_session,
        "newyork_open": newyork_open,
        "newyork_session": newyork_session,
        "participation_strength": strength,
        "participation_score": participation_score,
    }


def _extract_decision_context(location, trigger, participation, cycle, phase):
    time_score = float(((cycle or {}).get("time_engine") or {}).get("time_window_score", 0.0) or 0.0)
    time_score += 0.15 if bool((participation or {}).get("news_active", False)) else 0.0
    time_score += 0.1 if bool((participation or {}).get("london_open", False)) else 0.0
    time_score += 0.1 if bool((participation or {}).get("newyork_open", False)) else 0.0
    time_score = max(0.0, min(1.0, time_score))

    price_at_key_level = bool((location or {}).get("at_key_level", False))
    trigger_confirmed = bool((trigger or {}).get("trigger_confirmed", False))
    participation_strong = str((participation or {}).get("participation_strength") or "weak") == "strong"
    execute_trade = bool(time_score > 0.7 and price_at_key_level and trigger_confirmed and participation_strong)

    return {
        "time_score": time_score,
        "price_at_key_level": price_at_key_level,
        "trigger_confirmed": trigger_confirmed,
        "participation_strong": participation_strong,
        "execute_trade": execute_trade,
        "trade_direction": (trigger or {}).get("trigger_direction", "WAIT") if execute_trade else "WAIT",
    }


def _extract_gann_astro_math_context(sub_df, cycle):
    if sub_df.empty or len(sub_df) < 10:
        return {
            "tangent_angle_deg": 0.0,
            "tangent_expansion_strength": 0.0,
            "cosine_retracement": 0.0,
            "circle_projection_deg": 0.0,
            "circle_harmonic_proximity": 0.0,
            "sqrt_rotation_deg": 0.0,
            "degree_projection_active": False,
            "degree_projection_distance": 1.0,
            "time_price_balance_ratio": 0.0,
            "major_turn_window": False,
            "harmonic_angles": [45.0, 72.0, 90.0, 120.0, 144.0, 180.0],
            "harmonic_timing_text": "insufficient bars for gann-astro geometry",
        }

    window = sub_df.tail(min(len(sub_df), 180))
    highs = window["high"].astype(float)
    lows = window["low"].astype(float)
    closes = window["close"].astype(float)

    high = float(highs.max())
    low = float(lows.min())
    close = float(closes.iloc[-1])

    price_range = max(1e-9, high - low)
    bars = max(1, len(window) - 1)
    price_range_pct = price_range / max(1e-9, abs(low))

    tangent_slope = price_range_pct / float(bars)
    tangent_angle_deg = math.degrees(math.atan(tangent_slope))
    tangent_expansion_strength = max(0.0, min(1.0, tangent_angle_deg / 90.0))

    range_position = max(0.0, min(1.0, (close - low) / price_range))
    cosine_retracement = 0.5 * (1.0 + math.cos(math.pi * range_position))
    circle_projection_deg = 360.0 * range_position

    harmonic_angles = [45.0, 72.0, 90.0, 120.0, 144.0, 180.0]

    def _circular_distance(a_deg, b_deg):
        return abs(((a_deg - b_deg + 180.0) % 360.0) - 180.0)

    nearest_circle_harmonic_deg = min(_circular_distance(circle_projection_deg, h) for h in harmonic_angles)
    circle_harmonic_proximity = max(0.0, 1.0 - min(180.0, nearest_circle_harmonic_deg) / 180.0)

    sqrt_low = math.sqrt(max(0.0, low))
    sqrt_high = math.sqrt(max(0.0, high))
    sqrt_close = math.sqrt(max(0.0, close))
    sqrt_span = max(1e-9, sqrt_high - sqrt_low)
    sqrt_norm = max(0.0, min(1.0, (sqrt_close - sqrt_low) / sqrt_span))
    sqrt_rotation_deg = 360.0 * sqrt_norm

    projected_levels = [low + (price_range * (h / 360.0)) for h in harmonic_angles]
    nearest_projection_distance = min(abs(close - level) for level in projected_levels)
    degree_projection_distance = max(0.0, min(1.0, nearest_projection_distance / max(1e-9, price_range)))
    degree_projection_active = degree_projection_distance <= 0.08

    gann_degree = float((cycle or {}).get("gann_degree", 0.0) or 0.0) % 360.0
    nearest_gann_harmonic_deg = min(_circular_distance(gann_degree, h) for h in harmonic_angles)

    expected_time_progress = min(1.0, float(bars) / 180.0)
    time_price_balance_ratio = max(0.0, min(2.0, range_position / max(1e-9, expected_time_progress)))

    major_turn_window = bool(
        degree_projection_active
        or circle_harmonic_proximity >= 0.88
        or nearest_gann_harmonic_deg <= 10.0
    )

    reasons = []
    if degree_projection_active:
        reasons.append("price near harmonic degree projection")
    if circle_harmonic_proximity >= 0.88:
        reasons.append("circle harmonic proximity high")
    if nearest_gann_harmonic_deg <= 10.0:
        reasons.append("cycle degree near major harmonic")
    if not reasons:
        reasons.append("no major harmonic geometry cluster")

    return {
        "tangent_angle_deg": float(tangent_angle_deg),
        "tangent_expansion_strength": float(tangent_expansion_strength),
        "cosine_retracement": float(cosine_retracement),
        "circle_projection_deg": float(circle_projection_deg),
        "circle_harmonic_proximity": float(circle_harmonic_proximity),
        "sqrt_rotation_deg": float(sqrt_rotation_deg),
        "degree_projection_active": bool(degree_projection_active),
        "degree_projection_distance": float(degree_projection_distance),
        "time_price_balance_ratio": float(time_price_balance_ratio),
        "major_turn_window": bool(major_turn_window),
        "harmonic_angles": harmonic_angles,
        "harmonic_timing_text": "; ".join(reasons),
    }


def _extract_elliott_wave_context(sub_df, cycle, gann_astro_math, phase):
    default_context = {
        "wave_phase": "UNDEFINED",
        "wave_label": "UNDEFINED",
        "wave_confidence": 0.0,
        "wave_direction_up": False,
        "wave_position_norm": 0.0,
        "wave_progress": 0.0,
        "adjacent_wave_alignment": 0.0,
        "cycle_alignment_score": 0.0,
        "angle_alignment_score": 0.0,
        "astro_alignment_score": 0.0,
        "market_phase_alignment_score": 0.0,
        "wave_span_bars": 0.0,
        "wave_amplitude_norm": 0.0,
        "initial_point_price": 0.0,
        "ending_point_price": 0.0,
        "initial_to_current_norm": 0.0,
        "current_to_ending_norm": 0.0,
    }

    if sub_df.empty or len(sub_df) < 40:
        return default_context

    closes = sub_df["close"].astype(float).reset_index(drop=True)
    highs = sub_df["high"].astype(float).reset_index(drop=True)
    lows = sub_df["low"].astype(float).reset_index(drop=True)
    lookback = min(len(closes), 220)

    local_closes = closes.tail(lookback).reset_index(drop=True)
    local_highs = highs.tail(lookback).reset_index(drop=True)
    local_lows = lows.tail(lookback).reset_index(drop=True)

    pivot_indexes = []
    for idx in range(2, len(local_closes) - 2):
        c = float(local_closes.iloc[idx])
        left = local_closes.iloc[idx - 2:idx]
        right = local_closes.iloc[idx + 1:idx + 3]
        if c >= float(left.max()) and c >= float(right.max()):
            pivot_indexes.append((idx, "H"))
        elif c <= float(left.min()) and c <= float(right.min()):
            pivot_indexes.append((idx, "L"))

    if len(pivot_indexes) < 4:
        return default_context

    # Compress consecutive same-type pivots, keeping the most extreme point.
    compressed = []
    for idx, ptype in pivot_indexes:
        if not compressed or compressed[-1][1] != ptype:
            compressed.append((idx, ptype))
            continue
        prev_idx, prev_type = compressed[-1]
        if prev_type == "H" and float(local_closes.iloc[idx]) >= float(local_closes.iloc[prev_idx]):
            compressed[-1] = (idx, ptype)
        if prev_type == "L" and float(local_closes.iloc[idx]) <= float(local_closes.iloc[prev_idx]):
            compressed[-1] = (idx, ptype)

    if len(compressed) < 4:
        return default_context

    pivots = compressed[-8:]
    pivot_prices = [float(local_closes.iloc[idx]) for idx, _ in pivots]
    swing_changes = [pivot_prices[i] - pivot_prices[i - 1] for i in range(1, len(pivot_prices))]
    swing_abs = [abs(v) for v in swing_changes]
    swing_dirs = [1 if v > 0 else -1 for v in swing_changes if abs(v) > 1e-12]

    if not swing_abs or not swing_dirs:
        return default_context

    current_price = float(local_closes.iloc[-1])
    initial_idx = int(pivots[-2][0])
    ending_idx = int(pivots[-1][0])
    initial_price = float(local_closes.iloc[initial_idx])
    ending_price = float(local_closes.iloc[ending_idx])

    span_bars = max(1, ending_idx - initial_idx)
    amplitude = abs(ending_price - initial_price)
    recent_range = max(1e-9, float(local_highs.max()) - float(local_lows.min()))
    wave_amplitude_norm = max(0.0, min(1.0, amplitude / recent_range))

    wave_progress = 0.0
    if amplitude > 1e-9:
        wave_progress = max(0.0, min(1.0, abs(current_price - initial_price) / amplitude))

    net_direction = 1 if sum(swing_changes[-5:]) >= 0 else -1
    dominant_count = sum(1 for d in swing_dirs[-5:] if d == net_direction)
    adjacent_wave_alignment = float(dominant_count) / float(max(1, len(swing_dirs[-5:])))

    trend_strength = float(adjacent_wave_alignment)
    wave_phase = "IMPULSE" if trend_strength >= 0.6 else "CORRECTIVE"
    wave_position_norm = float((len(swing_changes) % 5) / 5.0)

    if wave_phase == "IMPULSE":
        wave_number = int((len(swing_changes) % 5) + 1)
        label_prefix = "UP" if net_direction > 0 else "DOWN"
        wave_label = f"{label_prefix}_WAVE_{wave_number}"
    else:
        corrective_labels = ["A", "B", "C"]
        wave_label = f"CORRECTIVE_{corrective_labels[len(swing_changes) % 3]}"

    cycle_time = bool((cycle or {}).get("time_cycle_active", False))
    gann_degree = float((cycle or {}).get("gann_degree", 0.0) or 0.0) % 360.0
    harmonic_angles = [45.0, 72.0, 90.0, 120.0, 144.0, 180.0]
    nearest_harmonic = min(abs(((gann_degree - h + 180.0) % 360.0) - 180.0) for h in harmonic_angles)
    cycle_alignment_score = max(0.0, min(1.0, (1.0 - nearest_harmonic / 180.0) * (1.0 if cycle_time else 0.8)))

    tangent_angle_deg = float((gann_astro_math or {}).get("tangent_angle_deg", 0.0) or 0.0)
    angle_targets = [26.565, 45.0, 63.435]
    nearest_angle = min(abs(tangent_angle_deg - a) for a in angle_targets)
    angle_alignment_score = max(0.0, min(1.0, 1.0 - nearest_angle / 90.0))

    astro_flags = [
        bool((cycle or {}).get("planetary_aspect_active", False)),
        bool((cycle or {}).get("planetary_conjunction_active", False)),
        bool((cycle or {}).get("planetary_square_active", False)),
        bool((cycle or {}).get("planetary_opposition_active", False)),
        bool((cycle or {}).get("moon_new_active", False)),
        bool((cycle or {}).get("moon_full_active", False)),
        bool((cycle or {}).get("moon_eclipse_active", False)),
    ]
    astro_alignment_score = float(sum(1 for flag in astro_flags if flag)) / float(len(astro_flags))

    phase_upper = str(phase or "NEUTRAL").upper()
    if wave_phase == "IMPULSE":
        market_phase_alignment_score = 1.0 if phase_upper in {"EXPANSION", "ACCUMULATION"} else 0.35
    else:
        market_phase_alignment_score = 1.0 if phase_upper in {"DISTRIBUTION", "MANIPULATION", "NEUTRAL"} else 0.35

    wave_confidence = max(
        0.0,
        min(
            1.0,
            0.35 * adjacent_wave_alignment
            + 0.2 * wave_amplitude_norm
            + 0.15 * cycle_alignment_score
            + 0.15 * angle_alignment_score
            + 0.1 * astro_alignment_score
            + 0.05 * market_phase_alignment_score,
        ),
    )

    return {
        "wave_phase": wave_phase,
        "wave_label": wave_label,
        "wave_confidence": float(wave_confidence),
        "wave_direction_up": bool(net_direction > 0),
        "wave_position_norm": float(wave_position_norm),
        "wave_progress": float(wave_progress),
        "adjacent_wave_alignment": float(adjacent_wave_alignment),
        "cycle_alignment_score": float(cycle_alignment_score),
        "angle_alignment_score": float(angle_alignment_score),
        "astro_alignment_score": float(astro_alignment_score),
        "market_phase_alignment_score": float(market_phase_alignment_score),
        "wave_span_bars": float(span_bars),
        "wave_amplitude_norm": float(wave_amplitude_norm),
        "initial_point_price": float(initial_price),
        "ending_point_price": float(ending_price),
        "initial_to_current_norm": max(0.0, min(1.0, abs(current_price - initial_price) / max(1e-9, recent_range))),
        "current_to_ending_norm": max(0.0, min(1.0, abs(ending_price - current_price) / max(1e-9, recent_range))),
    }


def _extract_bar_context(sub_df):
    if sub_df.empty:
        return {
            "index": None,
            "time": None,
            "open": None,
            "high": None,
            "low": None,
            "close": None,
        }

    last_row = sub_df.iloc[-1]
    raw_time = last_row.get("time") if "time" in sub_df.columns else sub_df.index[-1]
    if hasattr(raw_time, "to_pydatetime"):
        raw_time = raw_time.to_pydatetime()
    if hasattr(raw_time, "isoformat"):
        time_value = raw_time.isoformat(sep=" ")
    elif raw_time is None:
        time_value = None
    else:
        time_value = str(raw_time)

    def _float_or_none(value):
        try:
            return float(value)
        except Exception:
            return None

    return {
        "index": int(sub_df.index[-1]),
        "time": time_value,
        "open": _float_or_none(last_row.get("open")),
        "high": _float_or_none(last_row.get("high")),
        "low": _float_or_none(last_row.get("low")),
        "close": _float_or_none(last_row.get("close")),
    }


def _extract_turtle_soup_context(sub_df):
    """
    Detect Turtle Soup reversal pattern.
    Turtle Soup Sell: price sweeps equal highs (liquidity above old highs) then
                      closes back below — trap for breakout buyers.
    Turtle Soup Buy : price sweeps equal lows  then closes back above — trap for
                      breakout sellers.
    """
    empty = {
        "turtle_soup_buy": False,
        "turtle_soup_sell": False,
        "sweep_level": None,
        "sweep_direction": None,
        "rejection_confirmed": False,
    }
    if sub_df.empty or len(sub_df) < 6:
        return empty

    highs = sub_df["high"].astype(float)
    lows = sub_df["low"].astype(float)
    closes = sub_df["close"].astype(float)
    opens = sub_df["open"].astype(float)

    # Equal-highs window (last 20 bars, excluding current)
    lookback = min(len(sub_df) - 1, 20)
    prior_highs = highs.iloc[-(lookback + 1):-1]
    prior_lows = lows.iloc[-(lookback + 1):-1]
    recent_high = float(prior_highs.max())
    recent_low = float(prior_lows.min())

    current_high = float(highs.iloc[-1])
    current_low = float(lows.iloc[-1])
    current_close = float(closes.iloc[-1])
    current_open = float(opens.iloc[-1])

    avg_range = float((highs - lows).tail(20).mean() or 1.0)
    tolerance = avg_range * 0.15

    # --- Turtle Soup Sell ---
    # Current bar swept above prior highs AND closed back below → trap
    swept_high = current_high > recent_high + tolerance
    closed_below_sweep = current_close < recent_high
    bearish_bar = current_close < current_open
    turtle_soup_sell = bool(swept_high and closed_below_sweep and bearish_bar)

    # --- Turtle Soup Buy ---
    swept_low = current_low < recent_low - tolerance
    closed_above_sweep = current_close > recent_low
    bullish_bar = current_close > current_open
    turtle_soup_buy = bool(swept_low and closed_above_sweep and bullish_bar)

    sweep_level = None
    sweep_direction = None
    if turtle_soup_sell:
        sweep_level = round(current_high, 4)
        sweep_direction = "SELL"
    elif turtle_soup_buy:
        sweep_level = round(current_low, 4)
        sweep_direction = "BUY"

    return {
        "turtle_soup_buy": turtle_soup_buy,
        "turtle_soup_sell": turtle_soup_sell,
        "sweep_level": sweep_level,
        "sweep_direction": sweep_direction,
        "rejection_confirmed": bool(turtle_soup_sell or turtle_soup_buy),
    }


def _extract_amd_ifvg_context(sub_df):
    """Run AMD+IFVG engine on current sub-df, return latest bar signal dict."""
    empty = {
        "amd_bull_entry": False,
        "amd_bear_entry": False,
        "amd_phase": "NONE",
        "amd_sl": None,
        "amd_tp": None,
        "amd_entry_top": None,
        "amd_entry_bot": None,
        "amd_rr_ratio": None,
    }
    if sub_df.empty or len(sub_df) < 25:
        return empty
    try:
        result = amd_ifvg_latest(sub_df)
        signal = result.get("signal", "NONE")
        return {
            "amd_bull_entry": signal == "BULL",
            "amd_bear_entry": signal == "BEAR",
            "amd_phase": str(result.get("phase") or "NONE"),
            "amd_sl": result.get("sl"),
            "amd_tp": result.get("tp"),
            "amd_entry_top": result.get("entry_top"),
            "amd_entry_bot": result.get("entry_bot"),
            "amd_rr_ratio": result.get("rr_ratio"),
        }
    except Exception:
        return empty


def _build_scan_points(total_rows, start_idx, max_records=None, recent_window=250):
    end_idx = int(total_rows)
    start_idx = int(max(1, start_idx))
    recent_window = int(max(1, recent_window))

    full_points = list(range(start_idx, end_idx + 1))
    if max_records is None:
        return full_points

    max_records = int(max(1, max_records))
    if len(full_points) <= max_records:
        return full_points

    dense_start = max(start_idx, end_idx - recent_window + 1)
    dense_points = list(range(dense_start, end_idx + 1))

    historical_end = dense_start - 1
    if historical_end < start_idx:
        points = dense_points
    else:
        historical_slots = max(1, max_records - len(dense_points))
        historical_points_all = list(range(start_idx, historical_end + 1))
        step = max(1, (len(historical_points_all) + historical_slots - 1) // historical_slots)
        historical_points = historical_points_all[::step]
        if historical_points and historical_points[-1] != historical_end:
            historical_points.append(historical_end)
        points = historical_points + dense_points

    deduped = sorted(set(int(point) for point in points if start_idx <= int(point) <= end_idx))
    if deduped[-1] != end_idx:
        deduped.append(end_idx)
    return deduped


def scan_market(df, max_records=None, recent_window=250):
    memory = []

    # Start after enough data; fallback for shorter datasets.
    start_idx = 50 if len(df) > 50 else 10
    scan_points = _build_scan_points(
        total_rows=len(df),
        start_idx=start_idx,
        max_records=max_records,
        recent_window=recent_window,
    )

    # range includes len(df) so the final iteration uses the complete df,
    # ensuring current_record[-1] reflects the ACTUAL last bar (not N-1).
    for i in scan_points:
        sub_df = df.iloc[:i]
        bar = _extract_bar_context(sub_df)

        state = build_state(sub_df)

        physics = physics_engine(state)
        gann = gann_engine(state)
        liquidity = liquidity_engine(sub_df)
        phase = phase_engine(state, liquidity)
        signal = sync_engine(state, physics, gann, liquidity, phase)
        news = _extract_news_context(sub_df)
        structure = _extract_structure_context(sub_df)
        trap = trap_engine(state, liquidity, phase)
        compression = time_compression_engine(sub_df)
        cycle = _extract_cycle_context(sub_df)
        time_engine = _extract_time_context(cycle, phase)
        cycle["time_engine"] = time_engine
        gann_astro_math = _extract_gann_astro_math_context(sub_df, cycle)
        elliott_wave = _extract_elliott_wave_context(sub_df, cycle, gann_astro_math, phase)
        location = _extract_location_context(sub_df)
        trigger = _extract_trigger_context(sub_df, liquidity, structure)
        participation = _extract_participation_context(sub_df, news, state)
        order_flow = order_flow_engine(sub_df, liquidity=liquidity)
        decision_context = _extract_decision_context(location, trigger, participation, cycle, phase)
        turtle_soup = _extract_turtle_soup_context(sub_df)
        amd_ifvg = _extract_amd_ifvg_context(sub_df)
        reliability = _extract_reliability_context(
            state=state,
            gann=gann,
            liquidity=liquidity,
            phase=phase,
            signal=signal,
            trap=trap,
            compression=compression,
            structure=structure,
        )

        record = {
            "time": bar.get("time"),
            "bar_time": bar.get("time"),
            "bar": bar,
            "state": state,
            "physics": physics,
            "gann": gann,
            "liquidity": liquidity,
            "phase": phase,
            "signal": signal,
            "news": news,
            "structure": structure,
            "trap": trap,
            "compression": compression,
            "cycle": cycle,
            "time_engine": time_engine,
            "gann_astro_math": gann_astro_math,
            "elliott_wave": elliott_wave,
            "location": location,
            "trigger": trigger,
            "participation": participation,
            "order_flow": order_flow,
            "decision_context": decision_context,
            "turtle_soup": turtle_soup,
            "amd_ifvg": amd_ifvg,
            "reliability": reliability,
        }

        memory.append(record)

    return memory