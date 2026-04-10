from __future__ import annotations

import math
import uuid
from pathlib import Path

import pandas as pd


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_iso(ts) -> str | None:
    if ts is None:
        return None
    parsed = pd.to_datetime(ts, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.isoformat()


def _event_label(event_row: pd.Series | None) -> str | None:
    if event_row is None:
        return None
    for key in ("event", "title", "name", "category", "type"):
        val = event_row.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _find_neighbor_events(events_df: pd.DataFrame | None, reference_time: pd.Timestamp) -> dict:
    empty_payload = {
        "news_previous_time": None,
        "news_previous_event": None,
        "news_previous_impact": None,
        "news_previous_minutes_ago": None,
        "news_next_time": None,
        "news_next_event": None,
        "news_next_impact": None,
        "news_next_minutes_ahead": None,
    }
    if events_df is None or events_df.empty or pd.isna(reference_time):
        return empty_payload

    if "time" not in events_df.columns:
        return empty_payload

    ev = events_df.copy()
    ev["time"] = pd.to_datetime(ev["time"], errors="coerce")
    ev = ev.dropna(subset=["time"]).sort_values("time")
    if ev.empty:
        return empty_payload

    previous = ev[ev["time"] <= reference_time].tail(1)
    upcoming = ev[ev["time"] > reference_time].head(1)

    payload = dict(empty_payload)

    if not previous.empty:
        row = previous.iloc[0]
        minutes = (reference_time - row["time"]).total_seconds() / 60.0
        payload.update(
            {
                "news_previous_time": _to_iso(row["time"]),
                "news_previous_event": _event_label(row),
                "news_previous_impact": str(row.get("impact", "")).strip().lower() or None,
                "news_previous_minutes_ago": round(float(minutes), 2),
            }
        )

    if not upcoming.empty:
        row = upcoming.iloc[0]
        minutes = (row["time"] - reference_time).total_seconds() / 60.0
        payload.update(
            {
                "news_next_time": _to_iso(row["time"]),
                "news_next_event": _event_label(row),
                "news_next_impact": str(row.get("impact", "")).strip().lower() or None,
                "news_next_minutes_ahead": round(float(minutes), 2),
            }
        )

    return payload


def _trend_window(df: pd.DataFrame) -> dict:
    payload = {
        "trend_start_time": None,
        "trend_start_price": None,
        "trend_duration_hours": 0.0,
        "trend_direction_runtime": "FLAT",
        "latest_time": None,
        "latest_price": None,
    }
    if df.empty or "close" not in df.columns:
        return payload

    frame = df.copy()
    if "time" in frame.columns:
        frame["time"] = pd.to_datetime(frame["time"], errors="coerce")
        frame = frame.dropna(subset=["time"])
    if frame.empty:
        return payload

    closes = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.assign(close=closes).dropna(subset=["close"])
    if len(frame) < 2:
        latest_t = frame["time"].iloc[-1] if "time" in frame.columns else None
        latest_p = float(frame["close"].iloc[-1]) if not frame.empty else None
        payload.update(
            {
                "latest_time": _to_iso(latest_t),
                "latest_price": latest_p,
                "trend_start_time": _to_iso(latest_t),
                "trend_start_price": latest_p,
            }
        )
        return payload

    diff = frame["close"].diff().fillna(0.0)
    signs = diff.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0)).tolist()

    current_sign = 0
    for idx in range(len(signs) - 1, -1, -1):
        if signs[idx] != 0:
            current_sign = signs[idx]
            break

    start_idx = 1
    if current_sign != 0:
        start_idx = len(signs) - 1
        while start_idx > 1:
            sign_val = signs[start_idx]
            if sign_val == 0 or sign_val == current_sign:
                start_idx -= 1
                continue
            start_idx += 1
            break

    latest_idx = len(frame) - 1
    trend_start_t = frame["time"].iloc[start_idx] if "time" in frame.columns else None
    latest_t = frame["time"].iloc[latest_idx] if "time" in frame.columns else None
    trend_start_p = _safe_float(frame["close"].iloc[start_idx])
    latest_p = _safe_float(frame["close"].iloc[latest_idx])

    duration_hours = 0.0
    if trend_start_t is not None and latest_t is not None and not pd.isna(trend_start_t) and not pd.isna(latest_t):
        duration_hours = max(0.0, (latest_t - trend_start_t).total_seconds() / 3600.0)

    payload.update(
        {
            "trend_start_time": _to_iso(trend_start_t),
            "trend_start_price": round(trend_start_p, 6),
            "trend_duration_hours": round(float(duration_hours), 4),
            "trend_direction_runtime": "UP" if current_sign > 0 else ("DOWN" if current_sign < 0 else "FLAT"),
            "latest_time": _to_iso(latest_t),
            "latest_price": round(latest_p, 6),
        }
    )
    return payload


def _geometry_physics(frame: pd.DataFrame, points: int = 24) -> dict:
    payload = {
        "geometry_slope_price_per_hour": 0.0,
        "geometry_angle_deg": 0.0,
        "physics_velocity_price_per_hour": 0.0,
        "physics_acceleration_price_per_hour2": 0.0,
    }
    if frame.empty or "close" not in frame.columns or "time" not in frame.columns:
        return payload

    df = frame.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["time", "close"]).tail(max(4, points))
    if len(df) < 4:
        return payload

    first = df.iloc[0]
    mid = df.iloc[len(df) // 2]
    last = df.iloc[-1]

    h_total = max(1e-9, (last["time"] - first["time"]).total_seconds() / 3600.0)
    h1 = max(1e-9, (mid["time"] - first["time"]).total_seconds() / 3600.0)
    h2 = max(1e-9, (last["time"] - mid["time"]).total_seconds() / 3600.0)

    velocity = (float(last["close"]) - float(first["close"])) / h_total
    v1 = (float(mid["close"]) - float(first["close"])) / h1
    v2 = (float(last["close"]) - float(mid["close"])) / h2
    acceleration = (v2 - v1) / max(1e-9, (h1 + h2) / 2.0)

    payload.update(
        {
            "geometry_slope_price_per_hour": round(float(velocity), 8),
            "geometry_angle_deg": round(math.degrees(math.atan(float(velocity))), 6),
            "physics_velocity_price_per_hour": round(float(velocity), 8),
            "physics_acceleration_price_per_hour2": round(float(acceleration), 10),
        }
    )
    return payload


def _signal_window_from_physics(trend_ctx: dict, gp: dict) -> dict:
    payload = {
        "signal_start_time": trend_ctx.get("trend_start_time"),
        "signal_end_time": trend_ctx.get("latest_time"),
        "signal_start_price": trend_ctx.get("trend_start_price"),
        "signal_end_price": trend_ctx.get("latest_price"),
        "signal_window_hours": trend_ctx.get("trend_duration_hours", 0.0),
        "signal_projected_move": 0.0,
        "signal_projected_move_pct": 0.0,
        "signal_window_basis": "physics_projection",
    }

    start_time = pd.to_datetime(trend_ctx.get("trend_start_time"), errors="coerce")
    latest_time = pd.to_datetime(trend_ctx.get("latest_time"), errors="coerce")
    start_price = _safe_float(trend_ctx.get("trend_start_price"), 0.0)
    latest_price = _safe_float(trend_ctx.get("latest_price"), 0.0)
    trend_hours = max(0.0, _safe_float(trend_ctx.get("trend_duration_hours"), 0.0))

    velocity = _safe_float(gp.get("physics_velocity_price_per_hour"), 0.0)
    acceleration = _safe_float(gp.get("physics_acceleration_price_per_hour2"), 0.0)

    projected_hours = max(1.0, min(72.0, trend_hours if trend_hours > 0 else 1.0))
    if abs(velocity) > 1e-9 and abs(acceleration) > 1e-9:
        # If acceleration opposes current velocity, use estimated deceleration horizon.
        if velocity * acceleration < 0:
            projected_hours = max(0.5, min(72.0, abs(velocity / acceleration)))
        else:
            projected_hours = max(1.0, min(72.0, projected_hours * 1.25))

    end_price = latest_price + (velocity * projected_hours) + (0.5 * acceleration * (projected_hours**2))
    projected_move = end_price - latest_price
    projected_move_pct = (projected_move / latest_price * 100.0) if latest_price else 0.0

    if pd.isna(latest_time):
        signal_end_iso = trend_ctx.get("latest_time")
    else:
        signal_end_iso = _to_iso(latest_time + pd.to_timedelta(projected_hours, unit="h"))

    payload.update(
        {
            "signal_start_time": trend_ctx.get("trend_start_time") or _to_iso(start_time),
            "signal_end_time": signal_end_iso,
            "signal_start_price": round(float(start_price), 6),
            "signal_end_price": round(float(end_price), 6),
            "signal_window_hours": round(float(projected_hours), 4),
            "signal_projected_move": round(float(projected_move), 6),
            "signal_projected_move_pct": round(float(projected_move_pct), 6),
        }
    )
    return payload


def _build_gann_mindset_context(result: dict, signal_ctx: dict, gp: dict) -> dict:
    astro = (result or {}).get("astro", {}) or {}
    nearby = astro.get("nearby_event", {}) or {}
    impact = nearby.get("impact_analysis", {}) or {}

    gann = impact.get("gann_analysis", {}) or {}
    numerology = impact.get("numerology_analysis", {}) or {}
    structure = impact.get("structure_analysis", {}) or {}
    physics = impact.get("physics_analysis", {}) or {}

    nearest_angle = gann.get("nearest_key_angle")
    if nearest_angle is None:
        # Compute from universal gann degrees when astro nearby_event is unavailable
        universal = (result or {}).get("universal", {}) or {}
        raw_degree = _safe_float((universal.get("gann", {}) or {}).get("degrees"), 0.0)
        if raw_degree > 0:
            _key_angles = [45, 90, 180, 225, 315]
            nearest_angle = min(_key_angles, key=lambda a: min(abs(raw_degree - a), 360 - abs(raw_degree - a)))
    current_degree = gann.get("current_degree")
    if current_degree is None:
        universal = (result or {}).get("universal", {}) or {}
        current_degree = (universal.get("gann", {}) or {}).get("degrees")
    gann_proximity = str(gann.get("gann_angle_proximity") or "NONE")
    # If proximity is still NONE but we have real angle data, compute it
    if gann_proximity == "NONE" and nearest_angle is not None and current_degree is not None:
        _deg = _safe_float(current_degree, 0.0)
        if _deg > 0:
            _diff = min(abs(_deg - nearest_angle), 360 - abs(_deg - nearest_angle))
            gann_proximity = "EXACT" if _diff < 5 else "NEAR" if _diff < 15 else "NONE"

    cycle = str(numerology.get("numerology_cycle") or "NEUTRAL")
    harmonious = bool(numerology.get("harmonious_alignment", False))

    # ── Fallback: derive numerology cycle from top-level result numerology ────
    if cycle == "NEUTRAL":
        _num_result = (result or {}).get("numerology") or {}
        _meaning = str(_num_result.get("meaning") or "").upper()
        # Map numerology meaning → Gann cycle phase name
        _meaning_to_cycle = {
            "START":      "EXPANSION",
            "EXPANSION":  "EXPANSION",
            "MARKUP":     "EXPANSION",
            "COMPLETION": "COMPLETION",
            "REVERSAL":   "REVERSAL",
            "CHANGE":     "REVERSAL",
            "HARMONY":    "CONSOLIDATION",
            "STRUCTURE":  "CONSOLIDATION",
            "BALANCE":    "CONSOLIDATION",
            "POWER":      "EXPANSION",
        }
        if _meaning in _meaning_to_cycle:
            cycle = _meaning_to_cycle[_meaning]
            harmonious = _meaning in ("HARMONY", "EXPANSION", "STRUCTURE", "COMPLETION")

    time_phase = f"{cycle} ({'harmonious' if harmonious else 'mixed'})"

    bos = bool(structure.get("bos_confirmed", False))
    major_structure = str(structure.get("major_structure") or "CONSOLIDATION")
    structure_text = "broken upward" if bos and "UPTREND" in major_structure else (
        "broken downward" if bos and "DOWNTREND" in major_structure else "not fully confirmed"
    )

    momentum = str(physics.get("momentum_direction") or "NEUTRAL")
    acceleration = physics.get("price_acceleration")
    if acceleration is None:
        acceleration = gp.get("physics_acceleration_price_per_hour2")
    acceleration_val = _safe_float(acceleration, 0.0)

    # ── Fallback: derive momentum from velocity/acceleration in gp ───────────
    if momentum == "NEUTRAL":
        _vel = _safe_float(gp.get("physics_velocity_price_per_hour"), 0.0)
        if abs(_vel) > 20.0:
            momentum = "STRONG_UP" if _vel > 0 else "STRONG_DOWN"
        elif abs(_vel) > 5.0:
            momentum = "MILD_UP" if _vel > 0 else "MILD_DOWN"
        elif abs(_vel) > 0.5:
            # Acceleration opposing velocity = fading momentum
            if _vel * acceleration_val < 0:
                momentum = "FADING_UP" if _vel > 0 else "FADING_DOWN"
            else:
                momentum = "MILD_UP" if _vel > 0 else "MILD_DOWN"

    tape_text = "force is still pushing" if acceleration_val >= 0 else "motion is decaying"

    start_time = signal_ctx.get("signal_start_time") or "--"
    end_time = signal_ctx.get("signal_end_time") or "--"
    start_price = _safe_float(signal_ctx.get("signal_start_price"), 0.0)
    end_price = _safe_float(signal_ctx.get("signal_end_price"), 0.0)

    direction_word = "advance" if end_price >= start_price else "decline"
    angle_part = "--" if nearest_angle is None else f"{nearest_angle}"
    degree_part = "--" if current_degree is None else f"{current_degree}"
    bias = "BUY continuation bias, not blind chase" if direction_word == "advance" else "SELL continuation bias, not blind chase"

    narration = (
        f"Price has reached a cardinal angle near {angle_part}deg (current {degree_part}deg), "
        f"and time is in phase with {cycle.lower()} during active window {start_time} to {end_time}. "
        f"Structure has {structure_text}, and {tape_text} (momentum={momentum}). "
        f"This is not random movement; this is organized {direction_word}. "
        f"Start price {start_price:.4f}, target zone {end_price:.4f}. Therefore: {bias}."
    )

    geometry_ok = gann_proximity in {"EXACT", "NEAR"}
    time_ok = cycle in {"EXPANSION", "CONSOLIDATION", "COMPLETION"}
    structure_ok = bos
    tape_ok = momentum in {"STRONG_UP", "MILD_UP", "STRONG_DOWN", "MILD_DOWN"}

    recommended_signal = "WAIT"
    if geometry_ok and time_ok and (structure_ok or tape_ok):
        recommended_signal = "BUY" if direction_word == "advance" else "SELL"

    return {
        "gann_nearest_key_angle": nearest_angle,
        "gann_angle_proximity": gann_proximity,
        "numerology_cycle": cycle,
        "numerology_harmonious": harmonious,
        "structure_major": major_structure,
        "structure_bos_confirmed": bos,
        "physics_momentum": momentum,
        "physics_acceleration": round(acceleration_val, 6),
        "confirmation_geometry": "YES" if geometry_ok else "NO",
        "confirmation_time": "YES" if time_ok else "NO",
        "confirmation_structure": "YES" if structure_ok else "NO",
        "confirmation_tape_action": "YES" if tape_ok else "NO",
        "gann_mindset_narration": narration,
        "gann_mindset_bias": "BUY_CONTINUATION" if direction_word == "advance" else "SELL_CONTINUATION",
        "gann_time_phase": time_phase,
        "gann_recommended_signal": recommended_signal,
    }


def record_observation(
    df: pd.DataFrame,
    result: dict,
    events_df: pd.DataFrame | None,
    symbol: str,
    requested_timeframe: str,
    applied_timeframe: str,
    lookback_years: int,
    source_mode: str,
    output_dir: str = "data/observation_logs",
) -> dict:
    """Persist one market observation row with trend/time/event/Gann geometry and physics context."""
    obs_id = uuid.uuid4().hex[:16]
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    trend_ctx = _trend_window(df)
    latest_time = pd.to_datetime(trend_ctx.get("latest_time"), errors="coerce")
    event_ctx = _find_neighbor_events(events_df, latest_time)
    gp = _geometry_physics(df)
    signal_ctx = _signal_window_from_physics(trend_ctx, gp)
    gann_ctx = _build_gann_mindset_context(result or {}, signal_ctx, gp)

    universal = (result or {}).get("universal", {}) or {}
    gann = universal.get("gann", {}) or {}
    gann_cycle = gann.get("cycle", {}) or {}
    pte = gann.get("price_time_equality", {}) or {}
    nak = universal.get("nakshatra", {}) or {}

    trend_duration = max(0.0, _safe_float(trend_ctx.get("trend_duration_hours"), 0.0))
    latest_price = _safe_float(trend_ctx.get("latest_price"), 0.0)
    gann_degree = _safe_float(gann.get("degrees"), 0.0)

    row = {
        "observation_id": obs_id,
        "recorded_at_utc": pd.Timestamp.now("UTC").isoformat(),
        "symbol": str(symbol or "XAUUSD").upper(),
        "requested_timeframe": str(requested_timeframe or "1d"),
        "applied_timeframe": str(applied_timeframe or requested_timeframe or "1d"),
        "lookback_years": int(lookback_years) if lookback_years is not None else 25,
        "source_mode": str(source_mode or "historical_first"),
        "signal": (result or {}).get("filtered_signal"),
        "trend_label": ((result or {}).get("final", {}) or {}).get("trend", trend_ctx.get("trend_direction_runtime")),
        "trend_start_time": trend_ctx.get("trend_start_time"),
        "trend_start_price": trend_ctx.get("trend_start_price"),
        "trend_duration_hours": trend_ctx.get("trend_duration_hours"),
        "latest_time": trend_ctx.get("latest_time"),
        "latest_price": trend_ctx.get("latest_price"),
        "signal_start_time": signal_ctx.get("signal_start_time"),
        "signal_end_time": signal_ctx.get("signal_end_time"),
        "signal_start_price": signal_ctx.get("signal_start_price"),
        "signal_end_price": signal_ctx.get("signal_end_price"),
        "signal_window_hours": signal_ctx.get("signal_window_hours"),
        "signal_projected_move": signal_ctx.get("signal_projected_move"),
        "signal_projected_move_pct": signal_ctx.get("signal_projected_move_pct"),
        "signal_window_basis": signal_ctx.get("signal_window_basis"),
        "gann_nearest_key_angle": gann_ctx.get("gann_nearest_key_angle"),
        "gann_angle_proximity": gann_ctx.get("gann_angle_proximity"),
        "numerology_cycle_runtime": gann_ctx.get("numerology_cycle"),
        "numerology_harmonious_runtime": gann_ctx.get("numerology_harmonious"),
        "structure_major_runtime": gann_ctx.get("structure_major"),
        "structure_bos_runtime": gann_ctx.get("structure_bos_confirmed"),
        "physics_momentum_runtime": gann_ctx.get("physics_momentum"),
        "physics_acceleration_runtime": gann_ctx.get("physics_acceleration"),
        "confirmation_geometry": gann_ctx.get("confirmation_geometry"),
        "confirmation_time": gann_ctx.get("confirmation_time"),
        "confirmation_structure": gann_ctx.get("confirmation_structure"),
        "confirmation_tape_action": gann_ctx.get("confirmation_tape_action"),
        "gann_mindset_bias": gann_ctx.get("gann_mindset_bias"),
        "gann_time_phase": gann_ctx.get("gann_time_phase"),
        "gann_recommended_signal": gann_ctx.get("gann_recommended_signal"),
        "gann_mindset_narration": gann_ctx.get("gann_mindset_narration"),
        "news_previous_time": event_ctx.get("news_previous_time"),
        "news_previous_event": event_ctx.get("news_previous_event"),
        "news_previous_impact": event_ctx.get("news_previous_impact"),
        "news_previous_minutes_ago": event_ctx.get("news_previous_minutes_ago"),
        "news_next_time": event_ctx.get("news_next_time"),
        "news_next_event": event_ctx.get("news_next_event"),
        "news_next_impact": event_ctx.get("news_next_impact"),
        "news_next_minutes_ahead": event_ctx.get("news_next_minutes_ahead"),
        "price_degree": universal.get("price_degree"),
        "gann_degree": gann.get("degrees"),
        "gann_cycle_degree": gann_cycle.get("cycle_degree"),
        "gann_cycle_quadrant": gann_cycle.get("quadrant"),
        "gann_cycle_description": gann_cycle.get("description"),
        "gann_nearest_angles": "|".join(gann.get("nearest_angles", []) or []),
        "gann_price_time_status": pte.get("status"),
        "gann_price_time_ratio": pte.get("ratio"),
        "nakshatra": nak.get("nakshatra"),
        "nakshatra_pada": nak.get("pada"),
        "geometry_slope_price_per_hour": gp.get("geometry_slope_price_per_hour"),
        "geometry_angle_deg": gp.get("geometry_angle_deg"),
        "physics_velocity_price_per_hour": gp.get("physics_velocity_price_per_hour"),
        "physics_acceleration_price_per_hour2": gp.get("physics_acceleration_price_per_hour2"),
        # Requested by user: explicit time mappings.
        "price_time_ratio": round(latest_price / max(1.0, trend_duration), 8) if latest_price else 0.0,
        "degree_time_ratio": round(gann_degree / max(1.0, trend_duration), 8) if gann_degree else 0.0,
        "date_time_code": pd.to_datetime(trend_ctx.get("latest_time"), errors="coerce").strftime("%Y%m%d%H%M")
        if trend_ctx.get("latest_time")
        else None,
        # ── NEW: Moon phase + Gann cycle identification ────────────────────────
        "moon_phase": ((result or {}).get("astro") or {}).get("moon", {}) and
                      (result or {}).get("astro", {}).get("moon", {}).get("phase_name"),
        "moon_phase_key": ((result or {}).get("astro") or {}).get("moon", {}) and
                          (result or {}).get("astro", {}).get("moon", {}).get("phase_key"),
        "moon_cycle_pct": ((result or {}).get("astro") or {}).get("moon", {}) and
                          (result or {}).get("astro", {}).get("moon", {}).get("cycle_pct"),
        "moon_age_days": ((result or {}).get("astro") or {}).get("moon", {}) and
                         (result or {}).get("astro", {}).get("moon", {}).get("age_days"),
        "moon_market_phase": ((result or {}).get("astro") or {}).get("moon", {}) and
                              (result or {}).get("astro", {}).get("moon", {}).get("market_phase"),
        "moon_gann_narration": ((result or {}).get("astro") or {}).get("moon", {}) and
                                (result or {}).get("astro", {}).get("moon", {}).get("gann_narration"),
        "moon_cycle_started": bool(((result or {}).get("astro") or {}).get("moon", {}) and
                                   (result or {}).get("astro", {}).get("moon", {}).get("cycle_started")),
        "moon_full_peaked": bool(((result or {}).get("astro") or {}).get("moon", {}) and
                                 (result or {}).get("astro", {}).get("moon", {}).get("full_moon_peaked")),
        "cycle_event": ((result or {}).get("future") or {}).get("cycle_event"),
        "cycle_progress_pct": ((result or {}).get("future") or {}).get("cycle_progress_pct"),
        # ── Gann Node pressure points ─────────────────────────────────────────
        "node_active":       ((result or {}).get("gann_nodes") or {}).get("node_active", False),
        "node_type":         ((result or {}).get("gann_nodes") or {}).get("node_type", "NONE"),
        "node_price":        ((result or {}).get("gann_nodes") or {}).get("node_price", 0),
        "node_degree":       ((result or {}).get("gann_nodes") or {}).get("node_degree", 0),
        "node_time_harmonic":((result or {}).get("gann_nodes") or {}).get("time_harmonic", 0),
        "node_time_label":   ((result or {}).get("gann_nodes") or {}).get("time_label", ""),
        "node_bars_from_swing": ((result or {}).get("gann_nodes") or {}).get("bars_from_swing", 0),
        "node_bars_to_next": ((result or {}).get("gann_nodes") or {}).get("bars_to_next_node", 0),
        "node_signal_quality": ((result or {}).get("gann_nodes") or {}).get("signal_quality", "WATCH"),
        "node_spiral":       ((result or {}).get("gann_nodes") or {}).get("spiral_expansion", ""),
        "node_narration":    ((result or {}).get("gann_nodes") or {}).get("narration", ""),
        # ── Gann Square-of-9 levels + cycle position ──────────────────────────
        "gann_sq9_support": ((result or {}).get("universal") or {}).get("gann", {}).get("support_90"),
        "gann_sq9_resist":  ((result or {}).get("universal") or {}).get("gann", {}).get("resist_90"),
        "gann_sq9_swing":   ((result or {}).get("universal") or {}).get("gann", {}).get("swing_range"),
        "gann_cycle_degree": ((result or {}).get("universal") or {}).get("gann", {}).get("cycle", {}).get("cycle_degree"),
        "gann_cycle_quadrant": ((result or {}).get("universal") or {}).get("gann", {}).get("cycle", {}).get("quadrant"),
        "gann_cycle_description": ((result or {}).get("universal") or {}).get("gann", {}).get("cycle", {}).get("description"),
        "macro_bias": (result or {}).get("institutional", {}).get("macro"),
        "future_direction": ((result or {}).get("future") or {}).get("direction"),
        "liquidity_signal": ((result or {}).get("signals") or {}).get("liquidity"),
    }

    csv_path = out_dir / "market_observations.csv"
    row_df = pd.DataFrame([row])
    row_df.to_csv(csv_path, mode="a", index=False, header=not csv_path.exists())

    return {
        "observation_id": obs_id,
        "observation_log_path": str(csv_path),
        "observation": row,
    }
