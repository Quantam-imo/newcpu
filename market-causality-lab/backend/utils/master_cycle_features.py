from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def load_master_cycle_events(path: str) -> "pd.DataFrame | None":
    """Convert master cycle rows into timestamped event rows for feature integration."""
    p = Path(path)
    if not p.exists():
        return None

    try:
        df = pd.read_csv(p)
    except Exception:
        return None

    required_cols = {"event_time", "cycle_type", "sub_type", "label", "impact"}
    if df.empty or not required_cols.issubset(df.columns):
        return None

    work = df.copy()
    work["time"] = pd.to_datetime(work["event_time"], errors="coerce", utc=True).dt.tz_convert(None)
    work = work.dropna(subset=["time"])
    if work.empty:
        return None

    work["event"] = (
        work["cycle_type"].astype(str).str.upper()
        + "/" + work["sub_type"].astype(str)
        + ": " + work["label"].astype(str).fillna("")
    )
    work["category"] = "master_cycle_" + work["cycle_type"].astype(str)
    work["source"] = "master_cycles_25y"
    work["detail"] = work["label"].astype(str).fillna("")

    impact = work["impact"].astype(str).str.strip().str.lower()
    impact = impact.where(impact.isin({"low", "medium", "high"}), other="medium")
    work["impact"] = impact

    out = work[["time", "event", "impact", "category", "source", "detail"]].copy()
    return out.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)


def add_master_cycle_state_features(df: pd.DataFrame, master_cycles_path: str) -> pd.DataFrame:
    """Annotate price bars with numeric cycle-state features from master_cycles_25y.csv."""
    out = df.copy()
    defaults = {
        "cycle_moon_phase_position": 0.0,
        "cycle_nakshatra_sequence": 0.0,
        "cycle_gann_degree": 0.0,
        "cycle_days_to_next_node": 365.0,
        "cycle_planetary_active": 0.0,
        "cycle_planetary_aspect_active": 0.0,
        "cycle_planetary_conjunction_active": 0.0,
        "cycle_planetary_square_active": 0.0,
        "cycle_planetary_opposition_active": 0.0,
        "cycle_retrograde_active": 0.0,
        "cycle_nakshatra_transition_active": 0.0,
        "cycle_moon_eclipse_active": 0.0,
        "cycle_moon_new_active": 0.0,
        "cycle_moon_full_active": 0.0,
        "cycle_gann_pressure_window": 0.0,
        "cycle_gann_station_active": 0.0,
        "cycle_gann_synodic_active": 0.0,
        "cycle_gann_time_cycle_exact": 0.0,
        "cycle_time_cycle_active": 0.0,
    }
    for col, val in defaults.items():
        if col not in out.columns:
            out[col] = val

    if out.empty or "time" not in out.columns:
        return out

    p = Path(master_cycles_path)
    if not p.exists():
        return out

    try:
        mc = pd.read_csv(p)
    except Exception:
        return out

    required = {"event_time", "cycle_type"}
    if mc.empty or not required.issubset(mc.columns):
        return out

    mc = mc.copy()
    mc["event_time"] = pd.to_datetime(mc["event_time"], errors="coerce", utc=True).dt.tz_convert(None)
    mc = mc.dropna(subset=["event_time"]).sort_values("event_time").reset_index(drop=True)
    if mc.empty:
        return out

    work = pd.DataFrame({"idx": out.index})
    work["time"] = pd.to_datetime(out["time"], errors="coerce").to_numpy()
    valid = work.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    if valid.empty:
        return out

    moon = mc[mc["cycle_type"].astype(str).str.lower() == "moon"].copy()
    if not moon.empty and "sub_type" in moon.columns:
        moon["sub_type_norm"] = moon["sub_type"].astype(str).str.strip().str.lower()
        phase_map = {
            "new moon": 0.0,
            "solar eclipse": 0.0,
            "first quarter": 0.25,
            "full moon": 0.5,
            "lunar eclipse": 0.5,
            "last quarter": 0.75,
        }
        moon["anchor"] = moon["sub_type_norm"].map(phase_map)
        moon = moon.dropna(subset=["anchor"]).sort_values("event_time")
        if not moon.empty:
            mprev = pd.merge_asof(
                valid[["idx", "time"]],
                moon[["event_time", "anchor"]],
                left_on="time",
                right_on="event_time",
                direction="backward",
            )
            mnext = pd.merge_asof(
                valid[["idx", "time"]],
                moon[["event_time", "anchor"]],
                left_on="time",
                right_on="event_time",
                direction="forward",
            )
            pa = mprev["anchor"].fillna(0.0).to_numpy(dtype=float)
            na = mnext["anchor"].to_numpy(dtype=float)
            na = np.where(np.isnan(na), pa, na)
            pt = pd.to_datetime(mprev["event_time"], errors="coerce")
            nt = pd.to_datetime(mnext["event_time"], errors="coerce")
            tt = pd.to_datetime(valid["time"], errors="coerce")

            dt_total = (nt - pt).dt.total_seconds().to_numpy(dtype=float)
            dt_part = (tt - pt).dt.total_seconds().to_numpy(dtype=float)
            dt_total = np.where(np.isfinite(dt_total) & (dt_total > 0), dt_total, np.nan)
            frac = np.divide(dt_part, dt_total, out=np.zeros_like(dt_part, dtype=float), where=np.isfinite(dt_total))
            frac = np.clip(frac, 0.0, 1.0)

            delta = na - pa
            delta = np.where(delta < 0, delta + 1.0, delta)
            phase = np.mod(pa + frac * delta, 1.0)
            out.loc[valid["idx"], "cycle_moon_phase_position"] = phase

            def _moon_window(mask: pd.Series, column: str, hours: float) -> None:
                events = moon.loc[mask, ["event_time"]].dropna().sort_values("event_time")
                if events.empty:
                    return
                prev = pd.merge_asof(
                    valid[["idx", "time"]],
                    events,
                    left_on="time",
                    right_on="event_time",
                    direction="backward",
                )
                event_hours = (pd.to_datetime(valid["time"]) - pd.to_datetime(prev["event_time"])).dt.total_seconds() / 3600.0
                active = (event_hours >= 0.0) & (event_hours <= hours)
                out.loc[valid["idx"], column] = active.fillna(False).astype(float).to_numpy(dtype=float)

            _moon_window(moon["sub_type_norm"].str.contains("eclipse", case=False, regex=True), "cycle_moon_eclipse_active", 72.0)
            _moon_window(moon["sub_type_norm"] == "new moon", "cycle_moon_new_active", 24.0)
            _moon_window(moon["sub_type_norm"] == "full moon", "cycle_moon_full_active", 24.0)

    nak = mc[mc["cycle_type"].astype(str).str.lower() == "nakshatra"].copy()
    if not nak.empty and "nak_sequence" in nak.columns:
        nak["nak_sequence"] = pd.to_numeric(nak["nak_sequence"], errors="coerce")
        nak = nak.dropna(subset=["nak_sequence"]).sort_values("event_time")
        if not nak.empty:
            nprev = pd.merge_asof(
                valid[["idx", "time"]],
                nak[["event_time", "nak_sequence"]],
                left_on="time",
                right_on="event_time",
                direction="backward",
            )
            out.loc[valid["idx"], "cycle_nakshatra_sequence"] = nprev["nak_sequence"].fillna(0.0).to_numpy(dtype=float)
            last_nak_hours = (pd.to_datetime(valid["time"]) - pd.to_datetime(nprev["event_time"])).dt.total_seconds() / 3600.0
            nak_active = (last_nak_hours >= 0.0) & (last_nak_hours <= 24.0)
            out.loc[valid["idx"], "cycle_nakshatra_transition_active"] = nak_active.fillna(False).astype(float).to_numpy(dtype=float)

    gann = mc[mc["cycle_type"].astype(str).str.lower() == "gann"].copy()
    if not gann.empty and "degree_at_event" in gann.columns:
        gann["degree_at_event"] = pd.to_numeric(gann["degree_at_event"], errors="coerce")
        gann = gann.dropna(subset=["degree_at_event"]).sort_values("event_time")
        if not gann.empty:
            gprev = pd.merge_asof(
                valid[["idx", "time"]],
                gann[["event_time", "degree_at_event"]],
                left_on="time",
                right_on="event_time",
                direction="backward",
            )
            out.loc[valid["idx"], "cycle_gann_degree"] = gprev["degree_at_event"].fillna(0.0).to_numpy(dtype=float)

    if not gann.empty and "sub_type" in gann.columns:
        mask = gann["sub_type"].astype(str).str.contains("pressure|station|synodic|node", case=False, regex=True)
        nodes = gann.loc[mask, ["event_time"]].dropna().sort_values("event_time")
        if nodes.empty:
            nodes = gann[["event_time"]].dropna().sort_values("event_time")
        nnext = pd.merge_asof(
            valid[["idx", "time"]],
            nodes,
            left_on="time",
            right_on="event_time",
            direction="forward",
        )
        days = (pd.to_datetime(nnext["event_time"]) - pd.to_datetime(nnext["time"])).dt.total_seconds() / 86400.0
        days = days.fillna(365.0).clip(lower=0.0, upper=365.0)
        out.loc[valid["idx"], "cycle_days_to_next_node"] = days.to_numpy(dtype=float)

        nprev = pd.merge_asof(
            valid[["idx", "time"]],
            nodes,
            left_on="time",
            right_on="event_time",
            direction="backward",
        )
        node_hours = (pd.to_datetime(valid["time"]) - pd.to_datetime(nprev["event_time"])).dt.total_seconds() / 3600.0
        node_active = (node_hours >= 0.0) & (node_hours <= 72.0)
        out.loc[valid["idx"], "cycle_gann_pressure_window"] = node_active.fillna(False).astype(float).to_numpy(dtype=float)

        time_cycles = gann[gann["sub_type"].astype(str).str.contains("time cycle", case=False, regex=True)][["event_time"]].dropna().sort_values("event_time")
        if not time_cycles.empty:
            tc_prev = pd.merge_asof(
                valid[["idx", "time"]],
                time_cycles,
                left_on="time",
                right_on="event_time",
                direction="backward",
            )
            tc_hours = (pd.to_datetime(valid["time"]) - pd.to_datetime(tc_prev["event_time"])).dt.total_seconds() / 3600.0
            tc_active = (tc_hours >= 0.0) & (tc_hours <= 72.0)
            out.loc[valid["idx"], "cycle_time_cycle_active"] = tc_active.fillna(False).astype(float).to_numpy(dtype=float)

            exact_cycles = gann[
                gann["sub_type"].astype(str).str.contains("time cycle", case=False, regex=True)
                & gann.get("gann_quality", pd.Series(index=gann.index, dtype=object)).astype(str).str.strip().str.upper().eq("EXACT")
            ][["event_time"]].dropna().sort_values("event_time")
            if not exact_cycles.empty:
                exact_prev = pd.merge_asof(
                    valid[["idx", "time"]],
                    exact_cycles,
                    left_on="time",
                    right_on="event_time",
                    direction="backward",
                )
                exact_hours = (pd.to_datetime(valid["time"]) - pd.to_datetime(exact_prev["event_time"])).dt.total_seconds() / 3600.0
                exact_active = (exact_hours >= 0.0) & (exact_hours <= 72.0)
                out.loc[valid["idx"], "cycle_gann_time_cycle_exact"] = exact_active.fillna(False).astype(float).to_numpy(dtype=float)

        stations = gann[gann["sub_type"].astype(str).str.contains("planetary station", case=False, regex=True)][["event_time"]].dropna().sort_values("event_time")
        if not stations.empty:
            s_prev = pd.merge_asof(
                valid[["idx", "time"]],
                stations,
                left_on="time",
                right_on="event_time",
                direction="backward",
            )
            s_hours = (pd.to_datetime(valid["time"]) - pd.to_datetime(s_prev["event_time"])).dt.total_seconds() / 3600.0
            s_active = (s_hours >= 0.0) & (s_hours <= 72.0)
            out.loc[valid["idx"], "cycle_gann_station_active"] = s_active.fillna(False).astype(float).to_numpy(dtype=float)

        synodic = gann[gann["sub_type"].astype(str).str.contains("synodic", case=False, regex=True)][["event_time"]].dropna().sort_values("event_time")
        if not synodic.empty:
            sy_prev = pd.merge_asof(
                valid[["idx", "time"]],
                synodic,
                left_on="time",
                right_on="event_time",
                direction="backward",
            )
            sy_hours = (pd.to_datetime(valid["time"]) - pd.to_datetime(sy_prev["event_time"])).dt.total_seconds() / 3600.0
            sy_active = (sy_hours >= 0.0) & (sy_hours <= 72.0)
            out.loc[valid["idx"], "cycle_gann_synodic_active"] = sy_active.fillna(False).astype(float).to_numpy(dtype=float)

    planet = mc[mc["cycle_type"].astype(str).str.lower() == "planetary"]
    if not planet.empty:
        pprev = pd.merge_asof(
            valid[["idx", "time"]],
            planet[["event_time"]].sort_values("event_time"),
            left_on="time",
            right_on="event_time",
            direction="backward",
        )
        hours_since = (pd.to_datetime(pprev["time"]) - pd.to_datetime(pprev["event_time"])).dt.total_seconds() / 3600.0
        active = (hours_since >= 0.0) & (hours_since <= 24.0)
        out.loc[valid["idx"], "cycle_planetary_active"] = active.fillna(False).astype(float).to_numpy(dtype=float)

        if "sub_type" in planet.columns:
            aspects = planet[planet["sub_type"].astype(str).str.contains("aspect|conjunction|square|opposition", case=False, regex=True)][["event_time"]].dropna().sort_values("event_time")
            if not aspects.empty:
                aprev = pd.merge_asof(
                    valid[["idx", "time"]],
                    aspects,
                    left_on="time",
                    right_on="event_time",
                    direction="backward",
                )
                a_hours = (pd.to_datetime(valid["time"]) - pd.to_datetime(aprev["event_time"])).dt.total_seconds() / 3600.0
                a_active = (a_hours >= 0.0) & (a_hours <= 24.0)
                out.loc[valid["idx"], "cycle_planetary_aspect_active"] = a_active.fillna(False).astype(float).to_numpy(dtype=float)

            def _planetary_aspect_window(pattern: str, column: str) -> None:
                events = planet[
                    planet["sub_type"].astype(str).str.contains(pattern, case=False, regex=True)
                    | planet.get("label", pd.Series(index=planet.index, dtype=object)).astype(str).str.contains(pattern, case=False, regex=True)
                    | planet.get("detail", pd.Series(index=planet.index, dtype=object)).astype(str).str.contains(pattern, case=False, regex=True)
                ][["event_time"]].dropna().sort_values("event_time")
                if events.empty:
                    return
                prev = pd.merge_asof(
                    valid[["idx", "time"]],
                    events,
                    left_on="time",
                    right_on="event_time",
                    direction="backward",
                )
                event_hours = (pd.to_datetime(valid["time"]) - pd.to_datetime(prev["event_time"])).dt.total_seconds() / 3600.0
                active = (event_hours >= 0.0) & (event_hours <= 24.0)
                out.loc[valid["idx"], column] = active.fillna(False).astype(float).to_numpy(dtype=float)

            _planetary_aspect_window("conjunction", "cycle_planetary_conjunction_active")
            _planetary_aspect_window("square", "cycle_planetary_square_active")
            _planetary_aspect_window("opposition", "cycle_planetary_opposition_active")

            retro = planet[planet["sub_type"].astype(str).str.contains("retrograde|station", case=False, regex=True)][["event_time"]].dropna().sort_values("event_time")
            if not retro.empty:
                rprev = pd.merge_asof(
                    valid[["idx", "time"]],
                    retro,
                    left_on="time",
                    right_on="event_time",
                    direction="backward",
                )
                r_hours = (pd.to_datetime(valid["time"]) - pd.to_datetime(rprev["event_time"])).dt.total_seconds() / 3600.0
                r_active = (r_hours >= 0.0) & (r_hours <= 72.0)
                out.loc[valid["idx"], "cycle_retrograde_active"] = r_active.fillna(False).astype(float).to_numpy(dtype=float)

    return out