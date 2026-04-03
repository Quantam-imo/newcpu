#!/usr/bin/env python3
"""Prune market observation logs by retention window and max row count."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def prune_observation_frame(df: pd.DataFrame, keep_days: int, max_rows: int) -> pd.DataFrame:
    frame = df.copy()

    if "recorded_at_utc" in frame.columns:
        frame["recorded_at_utc"] = pd.to_datetime(frame["recorded_at_utc"], errors="coerce", utc=True)
        frame = frame.dropna(subset=["recorded_at_utc"])
        if not frame.empty:
            cutoff = pd.Timestamp.now("UTC") - pd.Timedelta(days=max(1, int(keep_days)))
            frame = frame[frame["recorded_at_utc"] >= cutoff]

    frame = frame.sort_values("recorded_at_utc") if "recorded_at_utc" in frame.columns else frame
    if max_rows > 0 and len(frame) > max_rows:
        frame = frame.tail(max_rows)

    return frame.reset_index(drop=True)


def prune_observation_csv(csv_path: Path, keep_days: int, max_rows: int, dry_run: bool = False) -> tuple[int, int]:
    if not csv_path.exists():
        return 0, 0

    original = pd.read_csv(csv_path)
    before = len(original)
    pruned = prune_observation_frame(original, keep_days=keep_days, max_rows=max_rows)
    after = len(pruned)

    if not dry_run:
        pruned.to_csv(csv_path, index=False)

    return before, after


def main() -> None:
    parser = argparse.ArgumentParser(description="Prune market observation logs")
    parser.add_argument(
        "--path",
        default="data/observation_logs/market_observations.csv",
        help="Path to observation CSV",
    )
    parser.add_argument("--keep-days", type=int, default=180, help="Keep observations newer than this many days")
    parser.add_argument("--max-rows", type=int, default=200000, help="Maximum rows to keep after time pruning")
    parser.add_argument("--dry-run", action="store_true", help="Calculate pruning without writing changes")
    args = parser.parse_args()

    csv_path = Path(args.path)
    before, after = prune_observation_csv(
        csv_path=csv_path,
        keep_days=args.keep_days,
        max_rows=args.max_rows,
        dry_run=bool(args.dry_run),
    )

    if before == 0 and not csv_path.exists():
        print(f"No file found at {csv_path}")
        return

    print(f"Observation rows before: {before}")
    print(f"Observation rows after:  {after}")
    print(f"Rows removed:            {max(0, before - after)}")
    print("Mode: dry-run" if args.dry_run else "Mode: applied")


if __name__ == "__main__":
    main()
