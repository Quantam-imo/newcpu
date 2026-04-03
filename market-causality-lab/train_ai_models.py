from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from backend.utils.data_loader import load_data, load_news_data, integrate_news_features
from backend.memory.scanner import scan_market
from backend.ai.modeling.trainer import train_and_register_from_memory
from backend.utils.timeframe_loader import TIMEFRAME_FILES


def _apply_lookback_years(df: pd.DataFrame, years: int) -> pd.DataFrame:
    years_i = max(1, min(100, int(years)))
    if "time" not in df.columns or df.empty:
        return df

    max_ts = pd.to_datetime(df["time"], errors="coerce").max()
    if pd.isna(max_ts):
        return df

    cutoff = max_ts - pd.DateOffset(years=years_i)
    trimmed = df[pd.to_datetime(df["time"], errors="coerce") >= cutoff].copy()
    return trimmed if not trimmed.empty else df


def _train_for_dataframe(df: pd.DataFrame, horizon: int) -> dict:
    memory = scan_market(df)
    result = train_and_register_from_memory(memory, horizon=max(1, int(horizon)))
    return {
        "trained": bool(result.trained),
        "reason": result.reason,
        "summary": result.summary,
        "memory_size": int(len(memory)),
    }


def _timeframe_path(data_dir: str, timeframe: str) -> Path:
    tf = str(timeframe or "1d").strip().lower()
    filename = TIMEFRAME_FILES.get(tf)
    if not filename:
        supported = ", ".join(sorted(TIMEFRAME_FILES.keys()))
        raise ValueError(f"Unsupported timeframe '{timeframe}'. Supported: {supported}")
    return Path(data_dir) / filename


def main() -> int:
    parser = argparse.ArgumentParser(description="Train and register AI baseline models from historical memory")
    parser.add_argument("--price-file", default="data/XAU_1d_data.csv")
    parser.add_argument("--news-file", default="data/news_data_v2.csv")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--all-timeframes", action="store_true")
    parser.add_argument("--lookback-years", type=int, default=25)
    parser.add_argument("--horizon", type=int, default=1)
    args = parser.parse_args()

    try:
        news_df = load_news_data(args.news_file)
    except Exception:
        news_df = None

    if args.all_timeframes:
        selected_tfs = ["1d", "4h", "1h", "30m", "15m", "5m", "1m", "1w", "1month"]
    else:
        selected_tfs = [str(args.timeframe or "1d").strip().lower()]

    report = []
    trained_any = False
    for tf in selected_tfs:
        try:
            path = _timeframe_path(args.data_dir, tf)
            if not path.exists():
                report.append({"timeframe": tf, "trained": False, "reason": f"dataset_missing:{path}"})
                continue

            df = load_data(str(path))
            df = _apply_lookback_years(df, int(args.lookback_years))
            df = integrate_news_features(df, news_df)

            train_result = _train_for_dataframe(df, args.horizon)
            train_result["timeframe"] = tf
            train_result["dataset"] = str(path)
            train_result["rows_used"] = int(len(df))
            report.append(train_result)
            trained_any = trained_any or bool(train_result.get("trained"))
        except Exception as exc:
            report.append({"timeframe": tf, "trained": False, "reason": str(exc)})

    print(json.dumps(
        {
            "trained_any": trained_any,
            "lookback_years": int(args.lookback_years),
            "timeframes": selected_tfs,
            "results": report,
        },
        indent=2,
    ))

    return 0 if trained_any else 1


if __name__ == "__main__":
    raise SystemExit(main())
