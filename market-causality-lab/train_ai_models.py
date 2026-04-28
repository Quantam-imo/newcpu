from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backend.utils.data_loader import load_data, load_news_data, integrate_news_features
from backend.utils.master_cycle_features import add_master_cycle_state_features as _add_master_cycle_state_features
from backend.utils.master_cycle_features import load_master_cycle_events as _load_master_cycle_events
from backend.memory.scanner import scan_market
from backend.ai.modeling.trainer import train_and_register_from_memory
from backend.utils.timeframe_loader import TIMEFRAME_FILES


def _load_and_merge_events(*paths: str) -> "pd.DataFrame | None":
    """Load and merge one or more CSV event files (news, astro, etc.) into a single DataFrame."""
    frames = []
    for p in paths:
        if not p:
            continue
        try:
            df = load_news_data(p)
            if "time" in df.columns:
                # Normalize both tz-aware and naive inputs to a common naive UTC timeline.
                ts = pd.to_datetime(df["time"], errors="coerce", utc=True)
                df = df.copy()
                df["time"] = ts.dt.tz_convert(None)
                df = df.dropna(subset=["time"]).reset_index(drop=True)
            frames.append(df)
            print(f"  [events] loaded {len(df):,} rows from {p}")
        except Exception as exc:
            print(f"  [events] skipped {p}: {exc}")
    if not frames:
        return None
    if len(frames) == 1:
        return frames[0]
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    print(f"  [events] merged total: {len(merged):,} rows")
    return merged


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


def _load_direct_table_events(path: str) -> "pd.DataFrame | None":
    """Convert direct 25Y Gann training table rows into event rows for feature integration."""
    p = Path(path)
    if not p.exists():
        print(f"  [direct-table] skipped missing file: {path}")
        return None

    try:
        df = pd.read_csv(p)
    except Exception as exc:
        print(f"  [direct-table] failed to read {path}: {exc}")
        return None

    if df.empty or "trade_date" not in df.columns:
        print(f"  [direct-table] skipped empty/invalid table: {path}")
        return None

    work = df.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce", utc=True)
    work = work.dropna(subset=["trade_date"])
    if work.empty:
        return None

    work["time"] = work["trade_date"]
    work["signal"] = work.get("trade_label", "WAIT").astype(str).str.upper()
    work["confluence_score"] = pd.to_numeric(work.get("confluence_score", 0), errors="coerce").fillna(0)
    work["ai_confidence"] = pd.to_numeric(work.get("ai_confidence", 50), errors="coerce").fillna(50)

    work = work[work["signal"].isin(["BUY", "SELL", "STRONG BUY", "STRONG SELL"])].copy()
    if work.empty:
        return None

    def _impact_from_conf(v: float) -> str:
        if v >= 80:
            return "high"
        if v >= 60:
            return "medium"
        return "low"

    work["impact"] = work["ai_confidence"].apply(_impact_from_conf)
    work["event"] = work["signal"].map(lambda s: f"GannDirect25Y {s}")
    work["category"] = "gann_direct_training_signal"
    work["source"] = "gann_direct_table"
    work["detail"] = work.get("gann_direct_narration", "")

    out = work[["time", "event", "impact", "category", "source", "detail"]].copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce", utc=True).dt.tz_convert(None)
    out = out.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

    print(f"  [direct-table] loaded {len(out):,} rows from {path}")
    return out


def _train_for_dataframe(
    df: pd.DataFrame,
    horizon: int,
    timeframe: str,
    dataset_path: str,
    lookback_years: int,
    label_mode: str,
    target_return_pct: float,
    stop_return_pct: float,
    feature_version: str,
    setup_mode: str,
) -> dict:
    memory = scan_market(df)
    result = train_and_register_from_memory(
        memory,
        horizon=max(1, int(horizon)),
        timeframe=timeframe,
        dataset_path=dataset_path,
        lookback_years=lookback_years,
        label_mode=label_mode,
        target_return_pct=target_return_pct,
        stop_return_pct=stop_return_pct,
        feature_version=feature_version,
        setup_mode=setup_mode,
    )
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
    parser.add_argument(
        "--astro-file",
        nargs="*",
        default=[
            "data/astro_nakshatra_events_2000_2026.csv",
            "data/gann_moon_aspects_2000_2026.csv",
            "data/gann_cycles_nodes_2000_2026.csv",
            "data/astro_planetary_ingress_2000_2026.csv",
            "data/nakshatra_transitions_2000_2026.csv",
            "data/akshaya_tritiya_events_2000_2026.csv",
        ],
        help="Astro event CSV(s) to merge with news features (same schema, repeatable)",
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--all-timeframes", action="store_true")
    parser.add_argument("--lookback-years", type=int, default=25)
    parser.add_argument("--horizon", type=int, default=1)
    parser.add_argument(
        "--label-mode",
        default="trend_up",
        choices=["trend_up", "first_touch_buy", "first_touch_sell"],
        help="Supervised label contract. 'trend_up' keeps the legacy next-state label; 'first_touch_buy' and 'first_touch_sell' train on realized directional follow-through.",
    )
    parser.add_argument(
        "--target-return-pct",
        type=float,
        default=0.002,
        help="Target return threshold for 'first_touch_buy' labels, expressed as decimal return.",
    )
    parser.add_argument(
        "--stop-return-pct",
        type=float,
        default=0.001,
        help="Stop threshold for 'first_touch_buy' labels, expressed as decimal return.",
    )
    parser.add_argument(
        "--feature-version",
        default="v3_amd_cycle_state",
        choices=["v3_amd_cycle_state", "v4_layered_execution", "v5_elliott_unified"],
        help="Feature schema to train. v4_layered_execution adds layered execution context; v5_elliott_unified adds Elliott-wave and unified cycle/angle/astro/phase alignment features.",
    )
    parser.add_argument(
        "--setup-mode",
        default="all_bars",
            choices=["all_bars", "triggered_trade", "london_sweep_mss_buy", "buy_trigger_candidate", "sell_trigger_candidate"],
        help="Filter training rows to a specific setup instead of learning from every bar.",
    )
    parser.add_argument(
        "--direct-table",
        default="data/reports/gann_astro_25y_ai_training_table.csv",
        help="Optional direct 25Y Gann/Astro training table to inject as event features",
    )
    parser.add_argument(
        "--master-cycles",
        default="data/reports/master_cycles_25y.csv",
        help="Master 25Y ordered cycle ledger (moon/nakshatra/planetary/gann) to inject as cycle events",
    )
    args = parser.parse_args()

    news_df = _load_and_merge_events(args.news_file, *(args.astro_file or []))
    direct_df = _load_direct_table_events(args.direct_table)
    if direct_df is not None:
        if news_df is None:
            news_df = direct_df
        else:
            news_df = pd.concat([news_df, direct_df], ignore_index=True)
            news_df = news_df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
        print(f"  [events] merged with direct-table: {len(news_df):,} rows total")

    mc_df = _load_master_cycle_events(args.master_cycles)
    if mc_df is not None:
        if news_df is None:
            news_df = mc_df
        else:
            news_df = pd.concat([news_df, mc_df], ignore_index=True)
            news_df = news_df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
        print(f"  [events] merged with master-cycles: {len(news_df):,} rows total")

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
            df = _add_master_cycle_state_features(df, args.master_cycles)

            train_result = _train_for_dataframe(
                df,
                args.horizon,
                timeframe=tf,
                dataset_path=str(path),
                lookback_years=int(args.lookback_years),
                label_mode=str(args.label_mode),
                target_return_pct=float(args.target_return_pct),
                stop_return_pct=float(args.stop_return_pct),
                feature_version=str(args.feature_version),
                setup_mode=str(args.setup_mode),
            )
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
            "label_mode": str(args.label_mode),
            "target_return_pct": float(args.target_return_pct),
            "stop_return_pct": float(args.stop_return_pct),
            "feature_version": str(args.feature_version),
            "setup_mode": str(args.setup_mode),
            "timeframes": selected_tfs,
            "results": report,
        },
        indent=2,
    ))

    return 0 if trained_any else 1


if __name__ == "__main__":
    raise SystemExit(main())
