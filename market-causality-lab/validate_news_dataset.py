from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = [
    "Date",
    "Time",
    "Event",
    "Impact",
    "Currency",
    "Category",
    "Source",
]

OPTIONAL_COLUMNS = [
    "Actual",
    "Forecast",
    "Previous",
    "Surprise",
    "Unit",
    "Revised",
]

ALLOWED_IMPACTS = {"low", "medium", "high"}


def _combine_time(df: pd.DataFrame) -> pd.Series:
    if "Date" not in df.columns:
        raise ValueError("Missing required Date column")
    if "Time" in df.columns:
        raw = df["Date"].astype(str).str.strip() + " " + df["Time"].astype(str).str.strip()
    else:
        raw = df["Date"].astype(str).str.strip()
    return pd.to_datetime(raw, errors="coerce")


def validate_news_csv(path: Path, min_years: int = 20) -> int:
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        return 2

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        print(f"ERROR: failed to read CSV: {exc}")
        return 2

    missing_required = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    missing_optional = [c for c in OPTIONAL_COLUMNS if c not in df.columns]

    if missing_required:
        print(f"ERROR: missing required columns: {missing_required}")
        return 2

    ts = _combine_time(df)
    invalid_ts = int(ts.isna().sum())

    dedupe_key = (
        df["Date"].astype(str).str.strip()
        + "|"
        + df["Time"].astype(str).str.strip()
        + "|"
        + df["Event"].astype(str).str.strip()
    )
    duplicates = int(dedupe_key.duplicated().sum())

    impacts = df["Impact"].astype(str).str.strip().str.lower()
    bad_impacts = sorted(set(impacts.dropna()) - ALLOWED_IMPACTS)

    valid_ts = ts.dropna()
    if len(valid_ts) == 0:
        print("ERROR: no parseable timestamps in dataset")
        return 2

    start = valid_ts.min()
    end = valid_ts.max()
    coverage_days = (end - start).days
    coverage_years = coverage_days / 365.2425

    print("NEWS DATASET VALIDATION")
    print("=" * 36)
    print(f"File: {path}")
    print(f"Rows: {len(df)}")
    print(f"Start: {start}")
    print(f"End:   {end}")
    print(f"Coverage (years): {coverage_years:.2f}")
    print(f"Invalid timestamps: {invalid_ts}")
    print(f"Duplicate (Date+Time+Event): {duplicates}")
    print(f"Impact values: {sorted(set(impacts))}")
    print(f"Missing optional columns: {missing_optional if missing_optional else 'none'}")

    status = 0
    if coverage_years < min_years:
        print(f"FAIL: coverage is below {min_years} years")
        status = 1
    else:
        print(f"PASS: coverage >= {min_years} years")

    if invalid_ts > 0:
        print("WARN: invalid timestamps detected")
        status = max(status, 1)

    if duplicates > 0:
        print("WARN: duplicate events detected")
        status = max(status, 1)

    if bad_impacts:
        print(f"WARN: unknown impact values: {bad_impacts}")
        status = max(status, 1)

    if status == 0:
        print("PASS: dataset quality checks passed")

    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate economic news CSV coverage and quality")
    parser.add_argument(
        "--file",
        default="data/news_data_v2.csv",
        help="Path to news CSV file",
    )
    parser.add_argument(
        "--min-years",
        type=int,
        default=20,
        help="Minimum required years of coverage",
    )
    args = parser.parse_args()

    return validate_news_csv(Path(args.file), min_years=args.min_years)


if __name__ == "__main__":
    sys.exit(main())
