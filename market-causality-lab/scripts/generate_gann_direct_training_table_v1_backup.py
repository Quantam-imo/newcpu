from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class Paths:
    prices: Path
    gann_cycles: Path
    gann_moon: Path
    astro_nakshatra: Path
    out_csv: Path
    out_md: Path


def _load_prices(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    df.columns = [c.strip() for c in df.columns]

    df["time"] = pd.to_datetime(df["Date"], format="%Y.%m.%d %H:%M", errors="coerce", utc=True)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        df[col.lower()] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["time", "close"]).sort_values("time").reset_index(drop=True)

    # Remove known malformed placeholder era and impossible spikes so rows are training-grade.
    df = df[(df["close"] >= 200.0) & (df["close"] <= 5000.0)].copy()
    day_ret = df["close"].pct_change().abs()
    df = df[(day_ret.isna()) | (day_ret <= 0.20)].copy()

    max_ts = df["time"].max()
    start_ts = max_ts - pd.DateOffset(years=25)
    return df[df["time"] >= start_ts].copy()


def _load_events(path: Path, tag: str) -> pd.DataFrame:
    ev = pd.read_csv(path)
    ev.columns = [c.strip() for c in ev.columns]
    ev["time"] = pd.to_datetime(ev["time"], errors="coerce", utc=True)
    ev = ev.dropna(subset=["time"]).copy()
    ev["date"] = ev["time"].dt.floor("D")
    ev["impact"] = ev.get("impact", "low").astype(str).str.lower()
    ev["event"] = ev.get("event", "").astype(str)
    ev["category"] = ev.get("category", "").astype(str)
    ev["tag"] = tag
    return ev


def _build_daily_event_features(gann_cycles: pd.DataFrame, gann_moon: pd.DataFrame, astro_nak: pd.DataFrame) -> pd.DataFrame:
    all_ev = pd.concat([gann_cycles, gann_moon, astro_nak], ignore_index=True)

    by_day = all_ev.groupby("date", as_index=False).agg(
        total_events=("event", "count"),
        high_impact_events=("impact", lambda x: int((x == "high").sum())),
    )

    gann_day = gann_cycles.groupby("date", as_index=False).agg(gann_events=("event", "count"))
    moon_day = gann_moon.groupby("date", as_index=False).agg(moon_events=("event", "count"))
    astro_day = astro_nak.groupby("date", as_index=False).agg(astro_events=("event", "count"))

    gann_nodes = gann_cycles.copy()
    gann_nodes["gann_node_hit"] = gann_nodes["event"].str.contains(
        "Node|Square-of-9|Station|Cycle", case=False, regex=True
    )
    node_day = gann_nodes.groupby("date", as_index=False).agg(gann_node_hit=("gann_node_hit", "max"))

    nak_only = astro_nak[astro_nak["event"].str.contains("nakshatra enters", case=False, regex=False)].copy()
    nak_only["nakshatra"] = nak_only["event"].str.extract(r"enters\s+(.+)$", expand=False).fillna("")
    nak_day = nak_only.groupby("date", as_index=False).agg(nakshatra=("nakshatra", "last"))

    moon_phase = gann_moon[gann_moon["category"].str.contains("moon_phase", case=False, regex=False)].copy()
    moon_phase["moon_phase_event"] = moon_phase["event"]
    moon_day_phase = moon_phase.groupby("date", as_index=False).agg(moon_phase=("moon_phase_event", "last"))

    # Extract key planetary events for narration
    planets = gann_moon[gann_moon["event"].str.contains("ingress|retrograde", case=False, regex=True)].copy()
    planets["planet_signature"] = planets["event"]
    planet_day = planets.groupby("date", as_index=False).agg(planet_signature=("planet_signature", lambda x: "|".join(x.head(3))))

    out = by_day.merge(gann_day, on="date", how="left")
    out = out.merge(moon_day, on="date", how="left")
    out = out.merge(astro_day, on="date", how="left")
    out = out.merge(node_day, on="date", how="left")
    out = out.merge(nak_day, on="date", how="left")
    out = out.merge(moon_day_phase, on="date", how="left")
    out = out.merge(planet_day, on="date", how="left")

    for col in ("gann_events", "moon_events", "astro_events"):
        out[col] = out[col].fillna(0).astype(int)

    out["gann_node_hit"] = out["gann_node_hit"].eq(True)
    out["nakshatra"] = out["nakshatra"].fillna("Unknown")
    out["moon_phase"] = out["moon_phase"].fillna("None")
    out["planet_signature"] = out["planet_signature"].fillna("")

    return out


def _label_trades(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["fwd_3d_return_pct"] = (d["close"].shift(-3) / d["close"] - 1.0) * 100.0
    d["fwd_5d_return_pct"] = (d["close"].shift(-5) / d["close"] - 1.0) * 100.0

    cond_buy = (d["fwd_3d_return_pct"] >= 0.8) | (d["fwd_5d_return_pct"] >= 1.2)
    cond_sell = (d["fwd_3d_return_pct"] <= -0.8) | (d["fwd_5d_return_pct"] <= -1.2)

    d["trade_label"] = np.where(cond_buy, "BUY", np.where(cond_sell, "SELL", "WAIT"))
    return d


def _confluence_score(row: pd.Series) -> int:
    score = 0
    score += 2 if row["gann_events"] > 0 else 0
    score += 1 if row["astro_events"] > 0 else 0
    score += 1 if row["moon_events"] > 0 else 0
    score += 1 if row["high_impact_events"] > 0 else 0
    score += 1 if bool(row["gann_node_hit"]) else 0
    return int(score)


def _signal_confidence(row: pd.Series) -> float:
    score = row["confluence_score"]
    move = max(abs(row["fwd_3d_return_pct"]), abs(row["fwd_5d_return_pct"]))
    conf = 45.0 + (score * 7.0) + min(20.0, move * 2.5)
    return round(float(min(99.0, max(1.0, conf))), 2)


def _calculate_moon_cycle_position(trade_date: pd.Timestamp) -> tuple:
    """
    Calculate position within lunar cycle (waxing/waning phase and energy stage).
    Approximates lunar phase as days since last New Moon (~29.5 day cycle).
    Returns: (days_from_new_moon, phase_name, energy_stage)
    """
    # Historical New Moon reference: 2000-01-06 (known New Moon)
    ref_new_moon = pd.Timestamp("2000-01-06", tz="UTC")
    days_since_ref = (trade_date - ref_new_moon).days
    cycle_position = days_since_ref % 29.5
    
    if cycle_position < 1.5:
        phase_name = "New Moon"
        energy_stage = "Silent Pressure"
    elif cycle_position < 7.5:
        phase_name = "Waxing Crescent"
        energy_stage = "Build (Days 3-7)"
    elif cycle_position < 8.5:
        phase_name = "First Quarter"
        energy_stage = "Confirmation (Days 7-9)"
    elif cycle_position < 14.5:
        phase_name = "Waxing Gibbous"
        energy_stage = "Expansion (Days 9-14)"
    elif cycle_position < 15.5:
        phase_name = "Full Moon"
        energy_stage = "Exhaustion Point"
    elif cycle_position < 22:
        phase_name = "Waning Gibbous"
        energy_stage = "Release (Days 15-22)"
    else:
        phase_name = "Waning Crescent"
        energy_stage = "Decay (Days 22-29)"
    
    return int(cycle_position), phase_name, energy_stage


def _calculate_geometric_time_markers(trade_date: pd.Timestamp, price_dates: pd.Series) -> dict:
    """
    Find nearest 90, 180, 360 day markers backwards from trade date.
    Returns dict with days_to_marker and marker_type.
    """
    markers = {}
    for interval in [90, 180, 360]:
        target_date = trade_date - pd.DateOffset(days=interval)
        # Find closest price date to target
        closest_idx = (price_dates - target_date).abs().argmin()
        closest_date = price_dates.iloc[closest_idx]
        exact_days = (trade_date - closest_date).days
        markers[f"marker_{interval}d"] = exact_days
    return markers


def _detect_price_phase(open_p, high_p, low_p, close_p) -> str:
    """
    Classify price action phase: Time Expansion (rising), Time Balance (sideways), Time Release (falling).
    """
    body = close_p - open_p
    range_size = high_p - low_p
    
    if range_size == 0:
        return "Time Balance"
    
    body_ratio = abs(body) / range_size
    
    if body > range_size * 0.4:  # Strong close above open
        return "Time Expansion"
    elif body < -range_size * 0.4:  # Strong close below open
        return "Time Release"
    else:
        return "Time Balance"


def _gann_narration(row: pd.Series, all_price_dates: pd.Series = None) -> str:
    """
    TIME-FIRST narration emphasizing geometric cycles, moon phases, and planetary hits.
    Mechanical execution language replacing emotional confirmation-waiting.
    """
    direction = row["trade_label"]
    if direction == "WAIT":
        return (
            f"Gann Desk: Time cycle not mature on {row['trade_date']}. "
            f"Nodes present but planetary hit not synchronized. Wait for the pressure point."
        )

    # Calculate time-based features
    trade_ts = pd.Timestamp(row["trade_date"], tz="UTC")
    cycle_pos, phase_name, energy_stage = _calculate_moon_cycle_position(trade_ts)
    price_phase = _detect_price_phase(row["open"], row["high"], row["low"], row["close"])
    
    # Determine time phase type
    if price_phase == "Time Expansion":
        time_phase_type = "Rise = Time Expansion Phase"
    elif price_phase == "Time Release":
        time_phase_type = "Fall = Time Release Phase"
    else:
        time_phase_type = "Sideways = Time Balance Phase"
    
    move_5d = row["fwd_5d_return_pct"]
    move_3d = row["fwd_3d_return_pct"]
    validated_move = max(abs(move_3d), abs(move_5d))
    
    # Extract planet signature if present
    planet_str = str(row.get("planet_signature", ""))
    planets_active = planet_str.split("|")[0] if planet_str else "Planetary alignment"
    
    # Build TIME-FIRST narration
    narration = (
        f"Time Entry {row['trade_date']}: {time_phase_type}. "
        f"Cycle position: {energy_stage} (Moon day {cycle_pos}). "
        f"{planets_active}. "
        f"Gann nodes hit: {int(row['gann_events'])} pressure points synchronized. "
        f"Astro triggers: {int(row['astro_events'])} (Nakshatra: {row['nakshatra']}). "
        f"When time matured, price responded {validated_move:+.2f}%. "
        f"Mechanical execution: {direction} at pressure point. "
        f"Logic established before bar opened; hesitation removed."
    )
    
    return narration


def build_dataset(paths: Paths) -> pd.DataFrame:
    px = _load_prices(paths.prices)
    px["date"] = px["time"].dt.floor("D")

    gann_cycles = _load_events(paths.gann_cycles, "gann_cycles")
    gann_moon = _load_events(paths.gann_moon, "gann_moon")
    astro_nak = _load_events(paths.astro_nakshatra, "astro_nakshatra")

    ev_daily = _build_daily_event_features(gann_cycles, gann_moon, astro_nak)

    df = px.merge(ev_daily, on="date", how="left")
    for col in ["total_events", "high_impact_events", "gann_events", "moon_events", "astro_events"]:
        df[col] = df[col].fillna(0).astype(int)
    df["gann_node_hit"] = df["gann_node_hit"].eq(True)
    df["nakshatra"] = df["nakshatra"].fillna("Unknown")
    df["moon_phase"] = df["moon_phase"].fillna("None")

    df = _label_trades(df)
    df["confluence_score"] = df.apply(_confluence_score, axis=1)
    df["ai_confidence"] = df.apply(_signal_confidence, axis=1)

    # Keep directional rows and stronger confluence so training rows remain high quality.
    df = df[(df["trade_label"] != "WAIT") & (df["confluence_score"] >= 3)].copy()

    df["trade_date"] = df["date"].dt.strftime("%Y-%m-%d")
    df["timeframe"] = "1d"
    df["model_target"] = df["trade_label"]
    
    # Enhanced TIME-FIRST narration with moon cycles and geometric markers
    df["gann_direct_narration"] = df.apply(
        lambda row: _gann_narration(row, all_price_dates=px["date"]),
        axis=1
    )

    ordered = [
        "trade_date",
        "timeframe",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trade_label",
        "model_target",
        "ai_confidence",
        "confluence_score",
        "gann_events",
        "astro_events",
        "moon_events",
        "high_impact_events",
        "gann_node_hit",
        "nakshatra",
        "moon_phase",
        "fwd_3d_return_pct",
        "fwd_5d_return_pct",
        "gann_direct_narration",
    ]

    df = df[ordered].sort_values("trade_date").reset_index(drop=True)
    return df


def write_outputs(df: pd.DataFrame, paths: Paths) -> None:
    paths.out_csv.parent.mkdir(parents=True, exist_ok=True)
    paths.out_md.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(paths.out_csv, index=False)

    top = df.sort_values(["confluence_score", "ai_confidence"], ascending=[False, False]).head(80)

    lines = [
        "# Gann Direct AI Training Table (Past 25 Years)",
        "",
        "This table is optimized for AI training rows where Gann+Astrology confluence is strong and future price move confirms direction.",
        "",
        f"Total qualifying rows: {len(df)}",
        "",
        "## Table Headings",
        "",
        "| trade_date | timeframe | close | trade_label | ai_confidence | confluence_score | gann_events | astro_events | nakshatra | moon_phase | gann_direct_narration |",
        "|---|---:|---:|---|---:|---:|---:|---:|---|---|---|",
    ]

    for _, r in top.iterrows():
        narration = str(r["gann_direct_narration"]).replace("|", "/")
        lines.append(
            f"| {r['trade_date']} | {r['timeframe']} | {r['close']:.2f} | {r['trade_label']} | {r['ai_confidence']:.2f} | "
            f"{int(r['confluence_score'])} | {int(r['gann_events'])} | {int(r['astro_events'])} | {r['nakshatra']} | "
            f"{r['moon_phase']} | {narration} |"
        )

    paths.out_md.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    base = Path(__file__).resolve().parents[1]
    paths = Paths(
        prices=base / "data" / "XAU_1d_data.csv",
        gann_cycles=base / "data" / "gann_cycles_nodes_2000_2026.csv",
        gann_moon=base / "data" / "gann_moon_aspects_2000_2026.csv",
        astro_nakshatra=base / "data" / "astro_nakshatra_events_2000_2026.csv",
        out_csv=base / "data" / "reports" / "gann_astro_25y_ai_training_table.csv",
        out_md=base / "data" / "reports" / "gann_astro_25y_ai_training_table.md",
    )

    df = build_dataset(paths)
    write_outputs(df, paths)

    print(f"[ok] wrote {len(df)} rows to {paths.out_csv}")
    print(f"[ok] wrote markdown table to {paths.out_md}")


if __name__ == "__main__":
    main()
