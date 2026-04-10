from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

import pandas as pd

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover - depends on local MT5 environment
    mt5 = None


def _fetch_via_redis(symbol: str = "XAUUSD", timeframe: int = 5, count: int = 500) -> pd.DataFrame:
    """
    Fetch OHLCV candles from Redis — populated by the AstroQuant LiveSyncEngine
    (Databento → CandleEngine → Redis keys: candle:{symbol}:{tf}:{epoch}).

    This is the PRIMARY live-data path when the system is running with
    astroquant_livesync.service active. Falls back to RuntimeError so the
    caller can try the next source.
    """
    try:
        import redis  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("redis package not installed") from exc

    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", 6379))
    db_num = int(os.environ.get("REDIS_DB", 0))

    try:
        r = redis.Redis(host=host, port=port, db=db_num, socket_connect_timeout=2)
        r.ping()
    except Exception as exc:
        raise RuntimeError(f"Redis unavailable: {exc}") from exc

    # Scan timestamped candle keys: candle:{symbol}:{tf}:*
    pattern = f"candle:{symbol}:{timeframe}:*"
    keys = r.keys(pattern)
    if not keys:
        raise RuntimeError(
            f"No Redis candle keys found for pattern '{pattern}'. "
            "Is astroquant_livesync.service running?"
        )

    rows = []
    for key in keys:
        raw = r.get(key)
        if not raw:
            continue
        try:
            candle = json.loads(raw)
            rows.append(candle)
        except (json.JSONDecodeError, TypeError):
            continue

    if not rows:
        raise RuntimeError(f"Redis returned {len(keys)} keys but all were empty/invalid")

    df = pd.DataFrame(rows)

    # Normalise time column
    if "timestamp" in df.columns and "time" not in df.columns:
        df["time"] = pd.to_datetime(df["timestamp"], utc=True)
    elif "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)

    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["time", "open", "high", "low", "close"])
    df = df.sort_values("time").reset_index(drop=True)

    if df.empty:
        raise RuntimeError("Redis candle data parsed to empty DataFrame")

    return df[["time", "open", "high", "low", "close", "volume"]].tail(count).reset_index(drop=True)


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
    """
    Fetch recent XAUUSD/GC candles for the MCL analysis pipeline.

    Source priority (first success wins):
      1. Redis  — AstroQuant LiveSyncEngine candles (zero-latency, always fresh)
      2. MT5    — MetaTrader5 terminal (requires local MT5 running)
      3. Databento Historical REST — fallback when both above are unavailable

    The Redis path is populated by astroquant_livesync.service which subscribes
    to the Databento GLBX.MDP3 live feed and aggregates ticks into 1m/5m/15m OHLCV.
    """
    # ── 1. Redis (live candles from AstroQuant LiveSyncEngine) ──────────────
    tf_minutes = 5
    if timeframe is not None and mt5 is not None:
        _tf_map = {
            mt5.TIMEFRAME_M1: 1, mt5.TIMEFRAME_M5: 5,
            mt5.TIMEFRAME_M15: 15, mt5.TIMEFRAME_M30: 30,
            mt5.TIMEFRAME_H1: 60,
        }
        tf_minutes = _tf_map.get(timeframe, 5)

    try:
        return _fetch_via_redis(symbol="XAUUSD", timeframe=tf_minutes, count=count)
    except RuntimeError:
        pass  # Redis unavailable or no data yet — try next source

    # ── 2. MetaTrader5 ───────────────────────────────────────────────────────
    if mt5 is not None:
        tf = timeframe if timeframe is not None else mt5.TIMEFRAME_M5
        if mt5.initialize():
            rates = mt5.copy_rates_from_pos("XAUUSD", tf, 0, count)
            if rates is not None:
                df = pd.DataFrame(rates)
                if not df.empty:
                    df["time"] = pd.to_datetime(df["time"], unit="s")
                    if "tick_volume" in df.columns and "volume" not in df.columns:
                        df = df.rename(columns={"tick_volume": "volume"})
                    return df

    # ── 3. Databento Historical REST (last resort) ───────────────────────────
    return _fetch_via_databento(count)
