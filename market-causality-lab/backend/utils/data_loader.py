import pandas as pd


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

    if "time" not in out.columns or out.empty or news_df is None or news_df.empty:
        out["news_impact_score"] = 0
        out["news_event_active"] = False
        return out

    pre_delta = pd.Timedelta(minutes=pre_event_minutes)
    post_delta = pd.Timedelta(minutes=post_event_minutes)

    for _, event in news_df.iterrows():
        event_time = event["time"]
        impact = event.get("impact", "medium")
        window_start = event_time - pre_delta
        window_end = event_time + post_delta

        mask = (out["time"] >= window_start) & (out["time"] <= window_end)
        if not mask.any():
            continue

        out.loc[mask, "news_event_count"] += 1
        if impact == "high":
            out.loc[mask, "news_high_impact_count"] += 1
        elif impact == "low":
            out.loc[mask, "news_low_impact_count"] += 1
        else:
            out.loc[mask, "news_medium_impact_count"] += 1

    out["news_impact_score"] = (
        out["news_low_impact_count"]
        + 2 * out["news_medium_impact_count"]
        + 3 * out["news_high_impact_count"]
    )
    out["news_event_active"] = out["news_event_count"] > 0

    return out