import pandas as pd
import numpy as np


def load_data(path):
    # Auto-detect delimiter so both comma and semicolon CSV exports work.
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip().lower() for c in df.columns]

    # Normalize common timestamp column names to `time`.
    if "date" in df.columns and "time" not in df.columns:
        df = df.rename(columns={"date": "time"})

    # Convert time column when present.
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")

    # Ensure numeric OHLCV columns are numeric when present.
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Remove rows where critical price fields cannot be parsed.
    required = [c for c in ("open", "high", "low", "close") if c in df.columns]
    if required:
        df = df.dropna(subset=required)

    return df


def load_news_data(path):
    """Load economic news CSV and normalize timestamp/impact fields."""
    news = pd.read_csv(path, sep=None, engine="python")
    news.columns = [c.strip().lower() for c in news.columns]

    if "date" in news.columns and "time" in news.columns:
        news["time"] = news["date"].astype(str) + " " + news["time"].astype(str)
    elif "time" not in news.columns and "date" in news.columns:
        if "hour" in news.columns:
            news["time"] = news["date"].astype(str) + " " + news["hour"].astype(str)
        elif "clock" in news.columns:
            news["time"] = news["date"].astype(str) + " " + news["clock"].astype(str)
        elif "event_time" in news.columns:
            news["time"] = news["date"].astype(str) + " " + news["event_time"].astype(str)
        elif "date_time" in news.columns:
            news["time"] = news["date_time"]
        elif "datetime" in news.columns:
            news["time"] = news["datetime"]
        else:
            news = news.rename(columns={"date": "time"})

    if "time" not in news.columns:
        raise ValueError("News dataset must include a timestamp column ('time' or 'date'+time fields)")

    news["time"] = pd.to_datetime(news["time"], errors="coerce")
    news = news.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

    if "impact" not in news.columns:
        news["impact"] = "medium"
    news["impact"] = news["impact"].astype(str).str.strip().str.lower()
    news.loc[~news["impact"].isin({"low", "medium", "high"}), "impact"] = "medium"

    if "event" not in news.columns:
        if "title" in news.columns:
            news = news.rename(columns={"title": "event"})
        elif "name" in news.columns:
            news = news.rename(columns={"name": "event"})
        else:
            news["event"] = "UNKNOWN_EVENT"

    return news


def integrate_news_features(df, news_df, pre_event_minutes=60, post_event_minutes=30):
    """Annotate price bars with nearby economic news context windows."""
    out = df.copy()
    out["news_event_count"] = 0
    out["news_high_impact_count"] = 0
    out["news_medium_impact_count"] = 0
    out["news_low_impact_count"] = 0
    out["news_aspect_event_count"] = 0
    out["news_conjunction_count"] = 0
    out["news_square_count"] = 0
    out["news_opposition_count"] = 0
    out["news_trine_count"] = 0
    out["news_sextile_count"] = 0
    out["news_ingress_event_count"] = 0
    out["news_nakshatra_event_count"] = 0
    out["news_gann_event_count"] = 0
    out["news_eclipse_event_count"] = 0

    if "time" not in out.columns or out.empty or news_df is None or news_df.empty:
        out["news_impact_score"] = 0
        out["news_event_active"] = False
        return out

    # Fast interval accumulation: O((rows+events) log rows) instead of
    # O(rows*events) repeated masking for large historical datasets.
    time_series = pd.to_datetime(out["time"], errors="coerce")
    valid_time_mask = time_series.notna()
    if not bool(valid_time_mask.any()):
        out["news_impact_score"] = 0
        out["news_event_active"] = False
        return out

    valid_idx = np.flatnonzero(valid_time_mask.to_numpy())
    base_ns = time_series.iloc[valid_idx].astype("int64", copy=False).to_numpy()

    order = np.argsort(base_ns)
    inv_order = np.empty_like(order)
    inv_order[order] = np.arange(len(order))
    sorted_ns = base_ns[order]

    events_local = news_df.copy()
    events_local["time"] = pd.to_datetime(events_local["time"], errors="coerce")
    events_local = events_local.dropna(subset=["time"])
    if events_local.empty:
        out["news_impact_score"] = 0
        out["news_event_active"] = False
        return out

    # Concept extraction for astrology/Gann named-aspect signals.
    event_text = events_local.get("event", "").astype(str)
    category_text = events_local.get("category", "").astype(str)
    detail_text = events_local.get("detail", "").astype(str)
    combined_text = (
        event_text.str.lower()
        + " "
        + category_text.str.lower()
        + " "
        + detail_text.str.lower()
    )

    impact = events_local.get("impact", "medium")
    impact = pd.Series(impact).astype(str).str.strip().str.lower().to_numpy()
    event_ns = events_local["time"].astype("int64", copy=False).to_numpy()

    pre_ns = int(pd.Timedelta(minutes=pre_event_minutes).value)
    post_ns = int(pd.Timedelta(minutes=post_event_minutes).value)

    start_ns = event_ns - pre_ns
    end_ns = event_ns + post_ns

    left = np.searchsorted(sorted_ns, start_ns, side="left")
    right = np.searchsorted(sorted_ns, end_ns, side="right")

    def _accumulate_interval_counts(mask_arr: np.ndarray | None = None) -> np.ndarray:
        diff = np.zeros(len(sorted_ns) + 1, dtype=np.int32)
        if mask_arr is None:
            np.add.at(diff, left, 1)
            np.add.at(diff, right, -1)
        else:
            np.add.at(diff, left[mask_arr], 1)
            np.add.at(diff, right[mask_arr], -1)
        counts_sorted = np.cumsum(diff[:-1])
        return counts_sorted[inv_order]

    total_counts = _accumulate_interval_counts()
    high_counts = _accumulate_interval_counts(mask_arr=(impact == "high"))
    low_counts = _accumulate_interval_counts(mask_arr=(impact == "low"))
    medium_counts = _accumulate_interval_counts(mask_arr=(impact != "high") & (impact != "low"))

    aspect_mask = combined_text.str.contains(
        r"\b(?:conjunction|sextile|square|trine|opposition)\b",
        regex=True,
        na=False,
    ).to_numpy()
    conjunction_mask = combined_text.str.contains(r"\bconjunction\b", regex=True, na=False).to_numpy()
    square_mask = combined_text.str.contains(r"\bsquare\b", regex=True, na=False).to_numpy()
    opposition_mask = combined_text.str.contains(r"\bopposition\b", regex=True, na=False).to_numpy()
    trine_mask = combined_text.str.contains(r"\btrine\b", regex=True, na=False).to_numpy()
    sextile_mask = combined_text.str.contains(r"\bsextile\b", regex=True, na=False).to_numpy()
    ingress_mask = combined_text.str.contains(r"\bingress\b", regex=True, na=False).to_numpy()
    nakshatra_mask = combined_text.str.contains(r"\bnakshatra\b", regex=True, na=False).to_numpy()
    gann_mask = combined_text.str.contains(r"\bgann\b", regex=True, na=False).to_numpy()
    eclipse_mask = combined_text.str.contains(r"\beclipse\b", regex=True, na=False).to_numpy()

    aspect_counts = _accumulate_interval_counts(mask_arr=aspect_mask)
    conjunction_counts = _accumulate_interval_counts(mask_arr=conjunction_mask)
    square_counts = _accumulate_interval_counts(mask_arr=square_mask)
    opposition_counts = _accumulate_interval_counts(mask_arr=opposition_mask)
    trine_counts = _accumulate_interval_counts(mask_arr=trine_mask)
    sextile_counts = _accumulate_interval_counts(mask_arr=sextile_mask)
    ingress_counts = _accumulate_interval_counts(mask_arr=ingress_mask)
    nakshatra_counts = _accumulate_interval_counts(mask_arr=nakshatra_mask)
    gann_counts = _accumulate_interval_counts(mask_arr=gann_mask)
    eclipse_counts = _accumulate_interval_counts(mask_arr=eclipse_mask)

    out_vals = out[[
        "news_event_count",
        "news_high_impact_count",
        "news_medium_impact_count",
        "news_low_impact_count",
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
    ]].to_numpy(copy=True)
    out_vals[valid_idx, 0] = total_counts
    out_vals[valid_idx, 1] = high_counts
    out_vals[valid_idx, 2] = medium_counts
    out_vals[valid_idx, 3] = low_counts
    out_vals[valid_idx, 4] = aspect_counts
    out_vals[valid_idx, 5] = conjunction_counts
    out_vals[valid_idx, 6] = square_counts
    out_vals[valid_idx, 7] = opposition_counts
    out_vals[valid_idx, 8] = trine_counts
    out_vals[valid_idx, 9] = sextile_counts
    out_vals[valid_idx, 10] = ingress_counts
    out_vals[valid_idx, 11] = nakshatra_counts
    out_vals[valid_idx, 12] = gann_counts
    out_vals[valid_idx, 13] = eclipse_counts
    out[[
        "news_event_count",
        "news_high_impact_count",
        "news_medium_impact_count",
        "news_low_impact_count",
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
    ]] = out_vals

    out["news_impact_score"] = (
        out["news_low_impact_count"]
        + 2 * out["news_medium_impact_count"]
        + 3 * out["news_high_impact_count"]
    )
    out["news_event_active"] = out["news_event_count"] > 0

    return out


def integrate_event_features(
    df,
    events_df,
    pre_event_minutes=60,
    post_event_minutes=30,
    prefix="event",
):
    """Generic event integration helper for historical global-events datasets.

    This mirrors integrate_news_features but writes into a configurable prefix,
    e.g. `global_event_count`, `global_high_impact_count`, etc.
    """
    out = df.copy()
    prefix = str(prefix or "event").strip().lower() or "event"

    out[f"{prefix}_count"] = 0
    out[f"{prefix}_high_impact_count"] = 0
    out[f"{prefix}_medium_impact_count"] = 0
    out[f"{prefix}_low_impact_count"] = 0

    if "time" not in out.columns or out.empty or events_df is None or events_df.empty:
        out[f"{prefix}_impact_score"] = 0
        out[f"{prefix}_active"] = False
        return out

    time_series = pd.to_datetime(out["time"], errors="coerce")
    valid_time_mask = time_series.notna()
    if not bool(valid_time_mask.any()):
        out[f"{prefix}_impact_score"] = 0
        out[f"{prefix}_active"] = False
        return out

    valid_idx = np.flatnonzero(valid_time_mask.to_numpy())
    base_ns = time_series.iloc[valid_idx].astype("int64", copy=False).to_numpy()

    order = np.argsort(base_ns)
    inv_order = np.empty_like(order)
    inv_order[order] = np.arange(len(order))
    sorted_ns = base_ns[order]

    events_local = events_df.copy()
    events_local["time"] = pd.to_datetime(events_local["time"], errors="coerce")
    events_local = events_local.dropna(subset=["time"])
    if events_local.empty:
        out[f"{prefix}_impact_score"] = 0
        out[f"{prefix}_active"] = False
        return out

    impact = events_local.get("impact", "medium")
    impact = pd.Series(impact).astype(str).str.strip().str.lower().to_numpy()
    impact = np.where(np.isin(impact, ["low", "medium", "high"]), impact, "medium")
    event_ns = events_local["time"].astype("int64", copy=False).to_numpy()

    pre_ns = int(pd.Timedelta(minutes=pre_event_minutes).value)
    post_ns = int(pd.Timedelta(minutes=post_event_minutes).value)

    start_ns = event_ns - pre_ns
    end_ns = event_ns + post_ns

    left = np.searchsorted(sorted_ns, start_ns, side="left")
    right = np.searchsorted(sorted_ns, end_ns, side="right")

    def _accumulate_interval_counts(mask_arr: np.ndarray | None = None) -> np.ndarray:
        diff = np.zeros(len(sorted_ns) + 1, dtype=np.int32)
        if mask_arr is None:
            np.add.at(diff, left, 1)
            np.add.at(diff, right, -1)
        else:
            np.add.at(diff, left[mask_arr], 1)
            np.add.at(diff, right[mask_arr], -1)
        counts_sorted = np.cumsum(diff[:-1])
        return counts_sorted[inv_order]

    total_counts = _accumulate_interval_counts()
    high_counts = _accumulate_interval_counts(mask_arr=(impact == "high"))
    low_counts = _accumulate_interval_counts(mask_arr=(impact == "low"))
    medium_counts = _accumulate_interval_counts(mask_arr=(impact == "medium"))

    cols = [
        f"{prefix}_count",
        f"{prefix}_high_impact_count",
        f"{prefix}_medium_impact_count",
        f"{prefix}_low_impact_count",
    ]
    out_vals = out[cols].to_numpy(copy=True)
    out_vals[valid_idx, 0] = total_counts
    out_vals[valid_idx, 1] = high_counts
    out_vals[valid_idx, 2] = medium_counts
    out_vals[valid_idx, 3] = low_counts
    out[cols] = out_vals

    out[f"{prefix}_impact_score"] = (
        out[f"{prefix}_low_impact_count"]
        + 2 * out[f"{prefix}_medium_impact_count"]
        + 3 * out[f"{prefix}_high_impact_count"]
    )
    out[f"{prefix}_active"] = out[f"{prefix}_count"] > 0

    return out