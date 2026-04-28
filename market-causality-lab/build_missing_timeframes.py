"""
Build missing/sparse timeframe CSVs by resampling existing complete data files.

  1w     <- daily      (resample W-FRI: weekly open/high/low/close)
  15m    <- 5m         (resample 15min)
  1month <- daily      (resample MS: monthly open/high/low/close)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"

# ─── helpers ──────────────────────────────────────────────────────────────────

def _load_semicolon_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip().lower() for c in df.columns]
    if "date" in df.columns and "time" not in df.columns:
        df = df.rename(columns={"date": "time"})
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time", "open", "high", "low", "close"])
    # Drop the placeholder rows (price == 1.25) that fill early years with no real data
    df = df[~((df["close"] == 1.25) & (df["open"] == 1.25))]
    return df.sort_values("time").reset_index(drop=True)


def _save_csv(df: pd.DataFrame, path: Path) -> None:
    out = df[["time", "open", "high", "low", "close"]].copy()
    out["time"] = out["time"].dt.strftime("%Y-%m-%d %H:%M")
    out.to_csv(path, index=False)
    print(f"  saved {len(out):,} rows → {path.name}")


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    df = df.set_index("time")
    agg = df.resample(rule).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    ).dropna()
    return agg.reset_index()


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    print("Loading source data...")

    daily_path = DATA_DIR / "XAU_1d_data.csv"
    fivemin_path = DATA_DIR / "XAU_5m_data.csv"

    if not daily_path.exists():
        print(f"ERROR: {daily_path} missing — cannot build 1w / 1month", file=sys.stderr)
        return 1
    if not fivemin_path.exists():
        print(f"ERROR: {fivemin_path} missing — cannot build 15m", file=sys.stderr)
        return 1

    # ── 1w ────────────────────────────────────────────────────────────────────
    print("\n[1/3] Building weekly (1w) from daily data...")
    daily_df = _load_semicolon_csv(daily_path)
    print(f"  daily rows loaded: {len(daily_df):,}  ({daily_df['time'].min().date()} → {daily_df['time'].max().date()})")

    weekly_df = _resample_ohlcv(daily_df, "W-FRI")
    _save_csv(weekly_df, DATA_DIR / "XAU_1w_data.csv")

    # ── 1month ────────────────────────────────────────────────────────────────
    print("\n[2/3] Building monthly (1month) from daily data...")
    monthly_df = _resample_ohlcv(daily_df, "MS")
    _save_csv(monthly_df, DATA_DIR / "XAU_1Month_data.csv")

    # ── 15m ───────────────────────────────────────────────────────────────────
    print("\n[3/3] Building 15m from 5m data...")
    fivemin_df = _load_semicolon_csv(fivemin_path)
    print(f"  5m rows loaded: {len(fivemin_df):,}  ({fivemin_df['time'].min().date()} → {fivemin_df['time'].max().date()})")

    fifteenmin_df = _resample_ohlcv(fivemin_df, "15min")
    _save_csv(fifteenmin_df, DATA_DIR / "XAU_15m_data.csv")

    print("\nAll missing timeframes built successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
