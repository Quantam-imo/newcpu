from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from backend.engines.liquidity_engine import liquidity_engine
from backend.engines.order_flow_engine import order_flow_engine
from backend.utils.data_loader import load_data
from backend.utils.timeframe_loader import TIMEFRAME_FILES


def _resolve_files(data_dir: Path, timeframe: str | None) -> list[tuple[str, Path]]:
    if timeframe:
        tf = str(timeframe).strip().lower()
        if tf not in TIMEFRAME_FILES:
            raise ValueError(f"Unsupported timeframe '{timeframe}'. Supported: {sorted(TIMEFRAME_FILES.keys())}")
        p = data_dir / TIMEFRAME_FILES[tf]
        return [(tf, p)] if p.exists() else []

    files: list[tuple[str, Path]] = []
    for tf, fname in TIMEFRAME_FILES.items():
        p = data_dir / fname
        if p.exists():
            files.append((tf, p))
    return files


def _compute_flow_rows(df: pd.DataFrame) -> pd.DataFrame:
    if "time" not in df.columns:
        df = df.copy()
        df["time"] = pd.RangeIndex(start=0, stop=len(df), step=1)

    rows = []
    start = 50 if len(df) > 50 else 10
    for i in range(start, len(df) + 1):
        sub = df.iloc[:i]
        liq = liquidity_engine(sub)
        of = order_flow_engine(sub, liquidity=liq)
        last = sub.iloc[-1]
        ts = last.get("time")
        year = None
        try:
            year = int(pd.to_datetime(ts, errors="coerce").year)
        except Exception:
            year = None

        rows.append(
            {
                "time": ts,
                "year": year,
                "close": float(last.get("close") or 0.0),
                "liquidity_type": str(liq.get("type") or "NONE"),
                **of,
            }
        )

    return pd.DataFrame(rows)


def _summarize(flow_df: pd.DataFrame) -> dict:
    if flow_df.empty:
        return {"rows": 0}

    n = len(flow_df)
    buy_agg = int((flow_df["aggressive_side"] == "BUY").sum())
    sell_agg = int((flow_df["aggressive_side"] == "SELL").sum())
    iceberg_n = int(flow_df["iceberg_detected"].astype(bool).sum())

    out = {
        "rows": n,
        "aggressive_buy_rate": round(buy_agg / n, 4),
        "aggressive_sell_rate": round(sell_agg / n, 4),
        "iceberg_rate": round(iceberg_n / n, 4),
        "mean_flow_imbalance": round(float(flow_df["flow_imbalance"].mean() or 0.0), 6),
        "mean_volume_zscore": round(float(flow_df["volume_zscore"].mean() or 0.0), 6),
    }

    by_year = (
        flow_df.dropna(subset=["year"])
        .groupby("year", dropna=True)
        .agg(
            rows=("flow_imbalance", "size"),
            mean_flow_imbalance=("flow_imbalance", "mean"),
            iceberg_rate=("iceberg_detected", "mean"),
            buy_aggressive_rate=("aggressive_side", lambda s: (s == "BUY").mean()),
            sell_aggressive_rate=("aggressive_side", lambda s: (s == "SELL").mean()),
        )
        .reset_index()
    )
    if not by_year.empty:
        out["year_start"] = int(by_year["year"].min())
        out["year_end"] = int(by_year["year"].max())

    by_liq = (
        flow_df.groupby("liquidity_type", dropna=False)
        .agg(
            rows=("flow_imbalance", "size"),
            mean_flow_imbalance=("flow_imbalance", "mean"),
            iceberg_rate=("iceberg_detected", "mean"),
        )
        .reset_index()
    )

    out["liquidity_breakdown"] = [
        {
            "liquidity_type": str(r["liquidity_type"]),
            "rows": int(r["rows"]),
            "mean_flow_imbalance": round(float(r["mean_flow_imbalance"] or 0.0), 6),
            "iceberg_rate": round(float(r["iceberg_rate"] or 0.0), 6),
        }
        for _, r in by_liq.iterrows()
    ]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze 25Y buy/sell flow and iceberg absorption from OHLCV.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--timeframe", default=None, help="single timeframe (e.g., 1h). Default: all available")
    parser.add_argument("--out-dir", default="data/reports")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = _resolve_files(data_dir, args.timeframe)
    if not files:
        raise SystemExit("No matching datasets found.")

    report = {}
    for tf, path in files:
        df = load_data(str(path))
        flow_df = _compute_flow_rows(df)

        csv_path = out_dir / f"order_flow_{tf}_detailed.csv"
        flow_df.to_csv(csv_path, index=False)

        yearly_path = out_dir / f"order_flow_{tf}_yearly.csv"
        (
            flow_df.dropna(subset=["year"])
            .groupby("year", dropna=True)
            .agg(
                rows=("flow_imbalance", "size"),
                mean_flow_imbalance=("flow_imbalance", "mean"),
                iceberg_rate=("iceberg_detected", "mean"),
                buy_aggressive_rate=("aggressive_side", lambda s: (s == "BUY").mean()),
                sell_aggressive_rate=("aggressive_side", lambda s: (s == "SELL").mean()),
            )
            .reset_index()
            .to_csv(yearly_path, index=False)
        )

        report[tf] = {
            **_summarize(flow_df),
            "detailed_csv": str(csv_path),
            "yearly_csv": str(yearly_path),
            "source": str(path),
        }

    summary_path = out_dir / "order_flow_25y_summary.json"
    summary_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps({"status": "ok", "summary": str(summary_path), "timeframes": list(report.keys())}, indent=2))


if __name__ == "__main__":
    main()
