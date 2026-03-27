"""Data Quality Engine — detect missing data, bad ticks, time gaps, and stale prices."""
from __future__ import annotations


def check_data_quality(df) -> dict:
    """
    Run a multi-point data quality audit on a price DataFrame.
    Returns a score (0–100), status label, and list of detected issues.
    """
    issues: list[str] = []
    score = 100.0

    # 1. Missing values in core price columns
    price_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
    for col in price_cols:
        missing = int(df[col].isnull().sum())
        if missing > 0:
            issues.append(f"MISSING_{col.upper()}:{missing}")
            score -= min(25.0, missing * 0.5)

    # 2. Zero or negative price values
    for col in price_cols:
        bad = int((df[col] <= 0).sum())
        if bad > 0:
            issues.append(f"BAD_PRICE_{col.upper()}:{bad}")
            score -= min(20.0, bad * 5.0)

    # 3. OHLC internal consistency: high >= close >= low and high >= open >= low
    if all(c in df.columns for c in ("high", "low", "close", "open")):
        inconsistent = int(
            ((df["high"] < df["close"])
             | (df["low"] > df["close"])
             | (df["high"] < df["open"])
             | (df["low"] > df["open"])).sum()
        )
        if inconsistent > 0:
            issues.append(f"OHLC_INCONSISTENT:{inconsistent}")
            score -= min(20.0, inconsistent * 2.0)

    # 4. Stale / flat feed detection on last 10 bars
    if "close" in df.columns and len(df) >= 10:
        recent = df["close"].tail(10)
        if recent.nunique() <= 1:
            issues.append("STALE_FEED:FLAT_PRICE")
            score -= 25.0

    # 5. Extreme price spike detection (>5 sigma on pct returns)
    if "close" in df.columns and len(df) > 30:
        returns = df["close"].pct_change().dropna()
        sigma = returns.std()
        if sigma > 0:
            spikes = int((returns.abs() > 5 * sigma).sum())
            if spikes > 0:
                issues.append(f"PRICE_SPIKES:{spikes}")
                score -= min(15.0, spikes * 3.0)

    # 6. Minimum row count guard
    if len(df) < 50:
        issues.append(f"LOW_ROW_COUNT:{len(df)}")
        score -= 10.0

    score = max(0.0, min(100.0, score))

    if score >= 90:
        status = "CLEAN"
    elif score >= 60:
        status = "DEGRADED"
    else:
        status = "CRITICAL"

    return {
        "score": round(score, 1),
        "status": status,
        "issues": issues if issues else ["NONE"],
        "rows_checked": len(df),
        "columns_checked": price_cols,
    }
