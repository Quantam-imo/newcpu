#!/usr/bin/env python3
"""Normalize MT5-exported XAUUSD CSV into MCL live bridge files.

This utility is intended for environments where MetaTrader5 Python API is not
available (for example Linux containers). Export bars from MT5 terminal into a
CSV file and run this script to produce the live CSV format consumed by the
MCL chart routes.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


_TF_TO_FILE = {
    "1m": "XAU_1m_data.csv",
    "5m": "XAU_5m_data.csv",
    "15m": "XAU_15m_data.csv",
    "30m": "XAU_30m_data.csv",
    "1h": "XAU_1h_data.csv",
    "4h": "XAU_4h_data.csv",
    "1d": "XAU_1d_data.csv",
    "1w": "XAU_1w_data.csv",
    "1month": "XAU_1Month_data.csv",
}


def _normalize_bridge_frame(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["Date", "Open", "High", "Low", "Close", "Volume", "Source"]
    out = pd.DataFrame(columns=cols)
    if df is None or df.empty:
        return out

    for col in cols:
        if col in df.columns:
            out[col] = df[col]
        else:
            out[col] = "" if col in ("Date", "Source") else 0.0

    for col in ("Open", "High", "Low", "Close", "Volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["Date"] = out["Date"].astype(str).str.strip()
    out["Source"] = out["Source"].astype(str).str.strip().replace("", "mt5-bridge")
    return out.dropna(subset=["Date", "Close"])


def _load_any_ohlc(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    frame = pd.read_csv(path, sep=None, engine="python")
    if len(frame.columns) == 1:
        only_col = str(frame.columns[0] or "")
        if "," in only_col:
            frame = pd.read_csv(path, sep=",", engine="python")

    frame.columns = [str(c).strip().lower() for c in frame.columns]
    if "date" in frame.columns and "time" not in frame.columns:
        frame = frame.rename(columns={"date": "time"})

    if "time" not in frame.columns:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    out = pd.DataFrame()
    out["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        if col in frame.columns:
            out[col] = pd.to_numeric(frame[col], errors="coerce")
        else:
            out[col] = 0.0

    out = out.dropna(subset=["time", "close"]).copy()
    out["open"] = out["open"].fillna(out["close"])
    out["high"] = out["high"].fillna(out["close"])
    out["low"] = out["low"].fillna(out["close"])
    out["volume"] = out["volume"].fillna(0.0)
    return out.sort_values("time").drop_duplicates(subset=["time"], keep="last")


def _bridge_to_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    incoming = _normalize_bridge_frame(df)
    out = pd.DataFrame()
    out["time"] = pd.to_datetime(incoming["Date"], utc=True, errors="coerce")
    out["open"] = pd.to_numeric(incoming["Open"], errors="coerce")
    out["high"] = pd.to_numeric(incoming["High"], errors="coerce")
    out["low"] = pd.to_numeric(incoming["Low"], errors="coerce")
    out["close"] = pd.to_numeric(incoming["Close"], errors="coerce")
    out["volume"] = pd.to_numeric(incoming["Volume"], errors="coerce").fillna(0.0)
    out = out.dropna(subset=["time", "close"]).copy()
    out["open"] = out["open"].fillna(out["close"])
    out["high"] = out["high"].fillna(out["close"])
    out["low"] = out["low"].fillna(out["close"])
    return out.sort_values("time").drop_duplicates(subset=["time"], keep="last")


def _write_canonical_ohlc(path: Path, df: pd.DataFrame) -> None:
    payload = df[["time", "open", "high", "low", "close", "volume"]].copy()
    payload["Date"] = payload["time"].dt.strftime("%Y.%m.%d %H:%M")
    payload[["Date", "open", "high", "low", "close", "volume"]].rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    ).to_csv(path, sep=";", index=False)


def persist_history_from_bridge_frame(
    df: pd.DataFrame,
    timeframe: str,
    data_dir: Path,
    max_rows: int = 2_500_000,
) -> Path | None:
    tf = str(timeframe or "").strip().lower()
    filename = _TF_TO_FILE.get(tf)
    if not filename:
        return None

    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / filename

    incoming = _bridge_to_ohlc(df)
    if incoming.empty:
        return target

    existing = _load_any_ohlc(target)
    merged = pd.concat([existing, incoming], ignore_index=True)
    merged = merged.dropna(subset=["time", "close"])
    merged = merged.sort_values("time").drop_duplicates(subset=["time"], keep="last")
    merged = merged.tail(max_rows)
    _write_canonical_ohlc(target, merged)
    return target


def refresh_derived_from_daily(data_dir: Path) -> list[Path]:
    daily_path = data_dir / _TF_TO_FILE["1d"]
    daily = _load_any_ohlc(daily_path)
    if daily.empty:
        return []

    by_day = daily.set_index("time")
    updates: list[Path] = []

    weekly = (
        by_day.resample("W-FRI", closed="right", label="right")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .dropna(subset=["close"])
        .reset_index()
    )
    if not weekly.empty:
        out_w = data_dir / _TF_TO_FILE["1w"]
        _write_canonical_ohlc(out_w, weekly)
        updates.append(out_w)

    monthly = (
        by_day.resample("MS", closed="left", label="left")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .dropna(subset=["close"])
        .reset_index()
    )
    if not monthly.empty:
        out_m = data_dir / _TF_TO_FILE["1month"]
        _write_canonical_ohlc(out_m, monthly)
        updates.append(out_m)

    return updates


def _load_mt5_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"input file not found: {path}")

    frame = None
    for sep in ("\t", ";", ","):
        try:
            trial = pd.read_csv(path, sep=sep)
            if trial is not None and not trial.empty and len(trial.columns) >= 2:
                frame = trial
                break
        except Exception:
            continue

    if frame is None or frame.empty:
        raise ValueError("unable to parse MT5 csv (empty or unsupported format)")

    frame = frame.rename(
        columns={
            "<DATE>": "Date",
            "<TIME>": "Time",
            "<OPEN>": "Open",
            "<HIGH>": "High",
            "<LOW>": "Low",
            "<CLOSE>": "Close",
            "<TICKVOL>": "Volume",
            "<VOL>": "Volume",
            "<VOLUME>": "Volume",
            "date": "Date",
            "time": "Time",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
            "tick_volume": "Volume",
        }
    )

    if "Date" in frame.columns and "Time" in frame.columns:
        dt = frame["Date"].astype(str).str.strip() + " " + frame["Time"].astype(str).str.strip()
    elif "Date" in frame.columns:
        dt = frame["Date"].astype(str).str.strip()
    else:
        raise ValueError("csv must contain Date (or <DATE>) column")

    parsed = pd.to_datetime(dt, utc=True, errors="coerce")
    if parsed.isna().all():
        parsed = pd.to_datetime(dt, format="%Y.%m.%d %H:%M", utc=True, errors="coerce")

    out = pd.DataFrame({"time": parsed})
    for src, dst in (("Open", "Open"), ("High", "High"), ("Low", "Low"), ("Close", "Close"), ("Volume", "Volume")):
        if src in frame.columns:
            out[dst] = pd.to_numeric(frame[src], errors="coerce")
        else:
            out[dst] = 0.0

    out = out.dropna(subset=["time", "Close"]).copy()
    if out.empty:
        raise ValueError("parsed MT5 csv has no valid rows")

    out["Open"] = out["Open"].fillna(out["Close"])
    out["High"] = out["High"].fillna(out["Close"])
    out["Low"] = out["Low"].fillna(out["Close"])
    out["Volume"] = out["Volume"].fillna(0.0)
    out["Date"] = out["time"].dt.strftime("%Y.%m.%d %H:%M")
    out["Source"] = "mt5-bridge"

    return out[["Date", "Open", "High", "Low", "Close", "Volume", "Source"]].sort_values("Date")


def _write_outputs(df: pd.DataFrame, symbol: str, timeframe: str, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)

    intraday = out_dir / f"{symbol}_live_{timeframe}_intraday.csv"
    export_copy = out_dir / f"{symbol}_{timeframe}.csv"

    incoming = _normalize_bridge_frame(df)
    existing = pd.DataFrame(columns=incoming.columns)
    if intraday.exists():
        try:
            existing_raw = pd.read_csv(intraday, sep=";")
            existing = _normalize_bridge_frame(existing_raw)
        except Exception:
            existing = pd.DataFrame(columns=incoming.columns)

    merged = pd.concat([existing, incoming], ignore_index=True)
    if not merged.empty:
        merged["_dt"] = pd.to_datetime(merged["Date"], utc=True, errors="coerce")
        merged = merged.dropna(subset=["_dt"])
        merged = merged.sort_values("_dt")
        merged = merged.drop_duplicates(subset=["Date"], keep="last")
        merged = merged.tail(10000)
        merged = merged.drop(columns=["_dt"])

    merged.to_csv(intraday, sep=";", index=False)
    merged.to_csv(export_copy, sep=";", index=False)
    return intraday, export_copy


def main() -> int:
    parser = argparse.ArgumentParser(description="Bridge MT5 CSV exports into MCL chart live datasets")
    parser.add_argument("--input", required=True, help="Path to MT5-exported CSV file")
    parser.add_argument("--symbol", default="XAUUSD", help="Symbol name (default: XAUUSD)")
    parser.add_argument("--timeframe", default="5m", help="Timeframe label: 1m/5m/15m/30m/1h/4h/1d")
    parser.add_argument(
        "--out-dir",
        default="/workspaces/newcpu/market-causality-lab/data/live/mt5",
        help="Output bridge directory",
    )
    parser.add_argument(
        "--persist-history",
        action="store_true",
        help="Also append bars into market-causality-lab/data/XAU_*_data.csv",
    )
    parser.add_argument(
        "--data-dir",
        default="/workspaces/newcpu/market-causality-lab/data",
        help="Canonical timeframe data directory used when --persist-history is enabled",
    )

    args = parser.parse_args()
    symbol = str(args.symbol or "XAUUSD").strip().upper()
    timeframe = str(args.timeframe or "5m").strip().lower()
    in_path = Path(args.input).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    data_dir = Path(args.data_dir).expanduser().resolve()

    df = _load_mt5_csv(in_path)
    intraday, export_copy = _write_outputs(df, symbol=symbol, timeframe=timeframe, out_dir=out_dir)
    history_target = None
    derived_paths: list[Path] = []
    if bool(args.persist_history):
        history_target = persist_history_from_bridge_frame(df=df, timeframe=timeframe, data_dir=data_dir)
        if timeframe == "1d":
            derived_paths = refresh_derived_from_daily(data_dir=data_dir)

    print(
        f"mt5 bridge updated | symbol={symbol} timeframe={timeframe} rows={len(df)} "
        f"intraday={intraday} export={export_copy} history={history_target}"
    )
    if derived_paths:
        print("derived refreshed | " + ", ".join(str(p) for p in derived_paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
