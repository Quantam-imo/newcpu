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
    }

    csv_path = out_dir / "market_observations.csv"
    row_df = pd.DataFrame([row])
    row_df.to_csv(csv_path, mode="a", index=False, header=not csv_path.exists())

    return {
        "observation_id": obs_id,
        "observation_log_path": str(csv_path),
        "observation": row,
    }
