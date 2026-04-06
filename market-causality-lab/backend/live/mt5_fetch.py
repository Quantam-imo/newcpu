from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

import pandas as pd

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover - depends on local MT5 environment
    mt5 = None


def _fetch_via_databento(count: int) -> pd.DataFrame:
    """Fallback: fetch recent GC/XAUUSD proxy candles from Databento when MT5 is unavailable."""
    api_key = str(os.getenv("DATABENTO_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError(
            "MetaTrader5 is unavailable and DATABENTO_API_KEY is not configured"
        )
    try:
        import databento as db  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "Neither MetaTrader5 nor databento package is installed"
        ) from exc

    minutes_needed = max(120, count * 2)
    start_dt = (datetime.now(timezone.utc) - timedelta(minutes=minutes_needed)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    client = db.Historical(api_key)
    data = client.timeseries.get_range(
        dataset="GLBX.MDP3",
        symbols=["GC.c.0"],
        stype_in="continuous",
        schema="ohlcv-1m",
        start=start_dt,
    )
    df = data.to_df()
    if df.empty:
        raise RuntimeError("Databento returned empty GC candle data")

    # Reset DatetimeIndex to a column if needed.
    if df.index.name in ("ts_event", "ts_recv") or isinstance(
        df.index, pd.DatetimeIndex
    ):
        df = df.reset_index()

    # Identify and normalise the time column.
    for ts_col in ("ts_event", "ts_recv", "timestamp"):
        if ts_col in df.columns and "time" not in df.columns:
            df["time"] = pd.to_datetime(df[ts_col], utc=True)
            break

    if "time" not in df.columns:
        raise RuntimeError("Cannot identify time column in Databento OHLCV response")

    # Normalise volume column name.
    for vol_col in ("size", "tick_volume", "qty", "quantity"):
        if vol_col in df.columns and "volume" not in df.columns:
            df = df.rename(columns={vol_col: "volume"})
            break
    if "volume" not in df.columns:
        df["volume"] = 0

    for required in ("open", "high", "low", "close"):
        if required not in df.columns:
            raise RuntimeError(
                f"Missing required price column '{required}' in Databento response"
            )

    return (
        df[["time", "open", "high", "low", "close", "volume"]]
        .tail(count)
        .reset_index(drop=True)
    )


def fetch_xauusd(count: int = 500, timeframe=None) -> pd.DataFrame:
    if mt5 is None:
        return _fetch_via_databento(count)

    tf = timeframe if timeframe is not None else mt5.TIMEFRAME_M5

    if not mt5.initialize():
        raise RuntimeError("Failed to initialize MetaTrader5 terminal")

    rates = mt5.copy_rates_from_pos("XAUUSD", tf, 0, count)
    if rates is None:
        raise RuntimeError("MetaTrader5 returned no rates for XAUUSD")

    df = pd.DataFrame(rates)
    if df.empty:
        raise RuntimeError("No XAUUSD rows returned from MetaTrader5")

    df["time"] = pd.to_datetime(df["time"], unit="s")

    # Normalize to the internal naming used by the rest of the pipeline.
    if "tick_volume" in df.columns and "volume" not in df.columns:
        df = df.rename(columns={"tick_volume": "volume"})

    return df
