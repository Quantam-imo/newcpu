"""
Astrology engine: event detection, planetary transits, nakshatra cycles, market impact.
Integrates Gann analysis, numerology, market structure, and physics observations.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from backend.astro.astro_event_mappings import get_astro_impact, format_astro_display
from backend.astro.astro_event_narration import generate_astro_narration, format_astro_event_briefing
from backend.astro.astro_event_impact_analyzer import analyze_astro_event_impact


# ─── Pure-math Moon Phase Calculator ─────────────────────────────────────────
# Reference new moon: 2000-01-06 18:14 UTC (J2000.0)
_KNOWN_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
_SYNODIC_MONTH  = 29.530588853   # days

_PHASE_NAMES = [
    (0.0,   1.85,  "New Moon",        "NEW_MOON"),
    (1.85,  7.38,  "Waxing Crescent", "WAXING_CRESCENT"),
    (7.38,  9.22,  "First Quarter",   "FIRST_QUARTER"),
    (9.22,  14.75, "Waxing Gibbous",  "WAXING_GIBBOUS"),
    (14.75, 16.61, "Full Moon",       "FULL_MOON"),
    (16.61, 22.15, "Waning Gibbous",  "WANING_GIBBOUS"),
    (22.15, 24.46, "Last Quarter",    "LAST_QUARTER"),
    (24.46, 29.53, "Waning Crescent", "WANING_CRESCENT"),
]

# Market bias by moon phase (Gann: New Moon = accumulation, Full Moon = distribution/reversal)
_MOON_MARKET_BIAS = {
    "NEW_MOON":       ("ACCUMULATION",  "BUY_ZONE",    "Gann: seeds planted — new cycle starting"),
    "WAXING_CRESCENT":("MARKUP",        "BUY",         "Gann: energy building — continuation"),
    "FIRST_QUARTER":  ("DECISION",      "WATCH",       "Gann: mid-cycle test — key resistance"),
    "WAXING_GIBBOUS": ("MARKUP",        "BUY_STRONG",  "Gann: momentum peak approaching"),
    "FULL_MOON":      ("DISTRIBUTION",  "REVERSAL",    "Gann: cycle peak — watch for reversal"),
    "WANING_GIBBOUS": ("DISTRIBUTION",  "SELL",        "Gann: energy dispersing — distribution"),
    "LAST_QUARTER":   ("DECISION",      "WATCH",       "Gann: mid-decline test — key support"),
    "WANING_CRESCENT":("MARKDOWN",      "SELL_END",    "Gann: final drain — approaching next seed"),
}


def moon_phase(dt: datetime) -> dict:
    """
    Compute the moon phase for a given datetime using pure math.
    No external astronomy library required.
    Returns:
        {
          "phase_name": str,           # "Waxing Gibbous" etc.
          "phase_key": str,            # "WAXING_GIBBOUS" etc.
          "cycle_pct": float,          # 0–100 (where in the 29.5-day cycle)
          "age_days": float,           # days since last new moon
          "days_to_full": float,       # days until next full moon
          "days_to_new": float,        # days until next new moon
          "market_phase": str,         # "MARKUP" / "DISTRIBUTION" etc.
          "market_bias": str,          # "BUY" / "SELL" / "WATCH"
          "gann_narration": str,
          "cycle_started": bool,       # True if within 2 days of a new moon
          "full_moon_peaked": bool,    # True if within 1.5 days of a full moon
        }
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    elapsed_days = (dt - _KNOWN_NEW_MOON).total_seconds() / 86400.0
    age_days = elapsed_days % _SYNODIC_MONTH  # 0..29.53

    # Phase identification
    phase_name, phase_key = "Waning Crescent", "WANING_CRESCENT"
    for lo, hi, name, key in _PHASE_NAMES:
        if lo <= age_days < hi:
            phase_name, phase_key = name, key
            break

    cycle_pct = (age_days / _SYNODIC_MONTH) * 100.0

    # Days to next full moon (14.75 days into cycle)
    full_moon_age = 14.765  # exact synodic mid-point
    days_to_full = (full_moon_age - age_days) % _SYNODIC_MONTH

    # Days to next new moon
    days_to_new = (_SYNODIC_MONTH - age_days) % _SYNODIC_MONTH
    if days_to_new < 0.01:
        days_to_new = _SYNODIC_MONTH

    market_phase, market_bias, gann_narration = _MOON_MARKET_BIAS.get(
        phase_key, ("NEUTRAL", "WATCH", "Moon phase neutral — monitor other signals")
    )

    return {
        "phase_name": phase_name,
        "phase_key": phase_key,
        "cycle_pct": round(cycle_pct, 2),
        "age_days": round(age_days, 2),
        "days_to_full": round(days_to_full, 2),
        "days_to_new": round(days_to_new, 2),
        "market_phase": market_phase,
        "market_bias": market_bias,
        "gann_narration": gann_narration,
        "cycle_started": age_days < 2.0,
        "full_moon_peaked": abs(age_days - full_moon_age) < 1.5,
    }


def _generate_lunar_events(start_year: int = 2020, end_year: int = 2027) -> list[dict]:
    """Generate New Moon and Full Moon events between start_year and end_year."""
    events = []
    # Start from the known new moon and step by synodic months
    step = _KNOWN_NEW_MOON
    end_dt = datetime(end_year, 12, 31, tzinfo=timezone.utc)
    start_dt = datetime(start_year, 1, 1, tzinfo=timezone.utc)

    # Fast-forward to first event after start_dt
    months_ahead = (start_dt - step).total_seconds() / 86400.0 / _SYNODIC_MONTH
    step = step + timedelta(days=int(months_ahead) * _SYNODIC_MONTH)

    while step <= end_dt:
        if step >= start_dt:
            events.append({
                "time": step.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "event": "New Moon",
                "impact": "high",
                "category": "lunar",
                "source": "computed",
                "detail": f"New lunar cycle begins — Gann accumulation zone. Age=0 days.",
            })
        # Full moon ≈ 14.765 days later
        full = step + timedelta(days=14.765)
        if start_dt <= full <= end_dt:
            events.append({
                "time": full.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "event": "Full Moon",
                "impact": "high",
                "category": "lunar",
                "source": "computed",
                "detail": f"Full Moon peak — Gann distribution/reversal zone. Cycle at 50%.",
            })
        # First Quarter ≈ 7.4 days
        fq = step + timedelta(days=7.38)
        if start_dt <= fq <= end_dt:
            events.append({
                "time": fq.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "event": "First Quarter Moon",
                "impact": "medium",
                "category": "lunar",
                "source": "computed",
                "detail": "First Quarter — decision point, resistance test.",
            })
        # Last Quarter ≈ 22.15 days
        lq = step + timedelta(days=22.15)
        if start_dt <= lq <= end_dt:
            events.append({
                "time": lq.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "event": "Last Quarter Moon",
                "impact": "medium",
                "category": "lunar",
                "source": "computed",
                "detail": "Last Quarter — decision point, support test.",
            })
        step = step + timedelta(days=_SYNODIC_MONTH)

    return sorted(events, key=lambda e: e["time"])


def load_astro_events(cache: dict | None = None) -> pd.DataFrame:
    """
    Load astrology event dataset. Falls back to computed lunar events if CSV is empty.
    """
    if cache is None:
        cache = {}

    if "astro_events_df" in cache:
        return cache["astro_events_df"]

    df = pd.DataFrame()

    # Try all path variants (works from any cwd)
    for candidate in [
        Path("data/astro_nakshatra_events_2000_2026.csv"),
        Path("market-causality-lab/data/astro_nakshatra_events_2000_2026.csv"),
        Path(__file__).parent.parent.parent / "data" / "astro_nakshatra_events_2000_2026.csv",
    ]:
        if candidate.exists():
            try:
                _df = pd.read_csv(candidate)
                _df["time"] = pd.to_datetime(_df["time"], utc=True, errors="coerce")
                _df = _df.dropna(subset=["time"])
                if len(_df) > 0:
                    df = _df
                    break
            except Exception:
                pass

    # If CSV is missing or entirely empty — generate lunar events on-the-fly
    if df.empty:
        rows = _generate_lunar_events(2020, 2027)
        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        # Persist so future calls are fast
        for out_candidate in [
            Path("data/astro_nakshatra_events_2000_2026.csv"),
            Path("market-causality-lab/data/astro_nakshatra_events_2000_2026.csv"),
        ]:
            if out_candidate.parent.exists():
                try:
                    df.to_csv(out_candidate, index=False)
                except Exception:
                    pass
                break

    cache["astro_events_df"] = df
    return df


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
    Integrates Gann, Numerology, Market Structure, and Market Physics analysis.

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
                "detail": str,
                "narration": {
                    "narration": str,
                    "gann_prediction": str,
                    "numerology_alignment": str,
                    "structure_outlook": str,
                    "physics_expectation": str,
                    "news_setup": str,
                    "price_targets": str,
                    "duration": str,
                },
                "impact_analysis": {
                    "gann_analysis": {...},
                    "numerology_analysis": {...},
                    "structure_analysis": {...},
                    "physics_analysis": {...},
                    "event_impact_summary": {...},
                },
            } | None,
        }
    """
    if cache is None:
        cache = {}

    # ── Current bar timestamp ─────────────────────────────────────────────────
    current_bar_ts = df["time"].iloc[-1] if "time" in df.columns and not df.empty else pd.Timestamp.now("UTC")
    if isinstance(current_bar_ts, pd.Timestamp):
        bar_dt = current_bar_ts.to_pydatetime()
        if bar_dt.tzinfo is None:
            bar_dt = bar_dt.replace(tzinfo=timezone.utc)
    else:
        bar_dt = datetime.now(timezone.utc)

    # ── Moon phase ────────────────────────────────────────────────────────────
    moon_info = moon_phase(bar_dt)

    # ── Load CSV events (needed for nakshatra + event detection) ─────────────
    astro_events_df = load_astro_events(cache)

    # ── Nakshatra cycle from CSV (swisseph-computed, not dataframe length) ────
    # BUG FIX: was `len(df) % 27` — bar count % 27 has no astronomical meaning.
    # The Moon moves through 27 nakshatras per sidereal month (~1 per day).
    # We now look up the most recent nakshatra transition from the swisseph CSV.
    from backend.universal_engine.astro_conversion import NAKSHATRAS
    cycle = 0
    nakshatra_name = "Unknown"
    if not astro_events_df.empty:
        nak_df = astro_events_df[astro_events_df["category"] == "nakshatra"]
        # Normalize current_bar_ts timezone to match nak_df["time"] (UTC-aware)
        _cmp_ts = current_bar_ts
        if isinstance(_cmp_ts, pd.Timestamp):
            if _cmp_ts.tzinfo is None:
                _cmp_ts = _cmp_ts.tz_localize("UTC")
        else:
            _cmp_ts = pd.Timestamp(current_bar_ts, tz="UTC")
        nak_past = nak_df[nak_df["time"] <= _cmp_ts]
        if not nak_past.empty:
            last_nak_event = str(nak_past.iloc[-1]["event"])
            for i, name in enumerate(NAKSHATRAS):
                if name.lower() in last_nak_event.lower():
                    cycle = i
                    nakshatra_name = name
                    break

    # Strength: Gann-significant nakshatras at trikona positions (0°, 120°, 240°)
    if cycle in [0, 9, 18]:
        strength = "HIGH"
    else:
        strength = "NORMAL"

    # Override: moon at cardinal phase always triggers HIGH window
    if moon_info["phase_key"] in ("NEW_MOON", "FULL_MOON"):
        strength = "HIGH"

    # Event detection: find nearby astro event within ±12 hours

    event_info = None
    if not astro_events_df.empty:
        event_found = find_nearby_astro_event(astro_events_df, current_bar_ts, hours_window=12)
        if event_found:
            impact_detail = get_astro_impact(event_found["event_name"], event_found["category"])
            
            # Generate narration (Gann, Numerology, Structure, Physics expectations)
            narration = generate_astro_narration(event_found["event_name"], event_found["category"])
            
            # Analyze event impact on current market (Gann, Numerology, Structure, Physics)
            impact_analysis = analyze_astro_event_impact(
                df=df,
                event_name=event_found["event_name"],
                event_time=event_found["time"],
                impact_level=impact_detail["impact_level"],
                market_outcome=impact_detail["market_outcome"],
            )
            
            event_info = {
                "event_name": event_found["event_name"],
                "event_short": format_astro_display(event_found["event_name"], impact_detail["impact_level"]),
                "impact_level": impact_detail["impact_level"],
                "market_outcome": impact_detail["market_outcome"],
                "volatility_signal": impact_detail.get("volatility", "MEDIUM"),
                "expected_direction": impact_detail.get("expected_direction", "UNKNOWN"),
                "time_delta_hours": round(event_found["time_delta_hours"], 2),
                "detail": event_found["detail"],
                "narration": narration,
                "impact_analysis": impact_analysis,
            }

    return {
        "nakshatra_cycle": cycle,
        "nakshatra_name": nakshatra_name,
        "strength": strength,
        "nearby_event": event_info,
        "moon": moon_info,
    }


def _run_astro_engine(df, cache: dict | None = None):
    """Alias kept for back-compat."""
    return astro_engine(df, cache)