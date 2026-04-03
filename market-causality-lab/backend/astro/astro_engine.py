"""
Astrology engine: event detection, planetary transits, nakshatra cycles, market impact.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from backend.astro.astro_event_mappings import get_astro_impact, format_astro_display


def load_astro_events(cache: dict | None = None) -> pd.DataFrame:
    """
    Load pre-generated astrology event dataset (ingresses + nakshatra transitions).
    Caches in memory to avoid repeated disk reads.
    """
    if cache is None:
        cache = {}

    if "astro_events_df" in cache:
        return cache["astro_events_df"]

    astro_file = Path("market-causality-lab/data/astro_nakshatra_events_2000_2026.csv")
    if not astro_file.exists():
        # Return empty frame if file doesn't exist
        empty = pd.DataFrame({
            "time": pd.Series([], dtype="datetime64[ns]"),
            "event": pd.Series([], dtype=str),
            "impact": pd.Series([], dtype=str),
            "category": pd.Series([], dtype=str),
            "source": pd.Series([], dtype=str),
            "detail": pd.Series([], dtype=str),
        })
        cache["astro_events_df"] = empty
        return empty

    try:
        df = pd.read_csv(astro_file)
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        cache["astro_events_df"] = df
        return df
    except Exception:
        # Return empty frame on read error
        empty = pd.DataFrame({
            "time": pd.Series([], dtype="datetime64[ns]"),
            "event": pd.Series([], dtype=str),
            "impact": pd.Series([], dtype=str),
            "category": pd.Series([], dtype=str),
            "source": pd.Series([], dtype=str),
            "detail": pd.Series([], dtype=str),
        })
        cache["astro_events_df"] = empty
        return empty


def find_nearby_astro_event(df: pd.DataFrame, ts: pd.Timestamp, hours_window: int = 12) -> dict | None:
    """
    Find astrological event(s) within ±hours_window of the given timestamp.
    Returns the nearest event (if multiple, closest wins).
    """
    if df.empty:
        return None

    # Ensure timestamp has UTC timezone
    if isinstance(ts, pd.Timestamp):
        ts_utc = ts.tz_convert("UTC") if ts.tz is not None else ts.tz_localize("UTC")
    else:
        ts_utc = pd.Timestamp(ts, tz="UTC")

    window_start = ts_utc - timedelta(hours=hours_window)
    window_end = ts_utc + timedelta(hours=hours_window)

    # Filter events in time window
    mask = (df["time"] >= window_start) & (df["time"] <= window_end)
    nearby = df[mask].copy()

    if nearby.empty:
        return None

    # Find closest event by time distance
    nearby["time_delta"] = (nearby["time"] - ts_utc).abs().dt.total_seconds()
    closest = nearby.loc[nearby["time_delta"].idxmin()]

    return {
        "event_name": str(closest["event"]),
        "detail": str(closest["detail"]),
        "impact_raw": str(closest["impact"]),
        "category": str(closest["category"]),
        "time": closest["time"],
        "time_delta_hours": float(closest["time_delta"]) / 3600.0,
    }


def astro_engine(df, cache: dict | None = None):
    """
    Astrology analysis: nakshatra cycle, event detection, market impact mapping.

    Returns:
        {
            "nakshatra_cycle": int (0-26),
            "strength": "HIGH" | "NORMAL",
            "nearby_event": {
                "event_name": str,
                "event_short": str (display-friendly),
                "impact_level": "HIGH" | "MEDIUM" | "LOW",
                "market_outcome": str,
                "volatility_signal": str,
                "expected_direction": str,
                "time_delta_hours": float,
            } | None,
        }
    """
    if cache is None:
        cache = {}

    # Base: nakshatra cycle
    cycle = len(df) % 27  # 27 nakshatra cycle
    if cycle in [0, 9, 18]:
        strength = "HIGH"
    else:
        strength = "NORMAL"

    # Event detection: find nearby astro event within ±12 hours
    astro_events_df = load_astro_events(cache)
    current_bar_ts = df["time"].iloc[-1] if "time" in df.columns and not df.empty else pd.Timestamp.now("UTC")

    event_info = None
    if not astro_events_df.empty:
        event_found = find_nearby_astro_event(astro_events_df, current_bar_ts, hours_window=12)
        if event_found:
            impact_detail = get_astro_impact(event_found["event_name"], event_found["category"])
            event_info = {
                "event_name": event_found["event_name"],
                "event_short": format_astro_display(event_found["event_name"], impact_detail["impact_level"]),
                "impact_level": impact_detail["impact_level"],
                "market_outcome": impact_detail["market_outcome"],
                "volatility_signal": impact_detail.get("volatility", "MEDIUM"),
                "expected_direction": impact_detail.get("expected_direction", "UNKNOWN"),
                "time_delta_hours": round(event_found["time_delta_hours"], 2),
                "detail": event_found["detail"],
            }

    return {
        "nakshatra_cycle": cycle,
        "strength": strength,
        "nearby_event": event_info,
    }