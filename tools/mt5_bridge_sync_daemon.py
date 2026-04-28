#!/usr/bin/env python3
"""Continuously sync MT5 CSV exports into MCL bridge datasets.

This daemon watches an incoming folder for the newest MT5-exported CSV file,
waits for the file to stabilize, then converts it into bridge outputs consumed
by the MCL chart path.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pandas as pd

from mt5_bridge_to_mcl import _load_mt5_csv, _write_outputs

# Timeframes to auto-generate by resampling the base (5m) feed.
# Keys = target TF label, values = pandas resample rule.
_RESAMPLE_TFS: dict[str, str] = {
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}


def _resample_df(df_5m: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample a 5m bridge DataFrame to a coarser timeframe."""
    tmp = df_5m.copy()
    # _load_mt5_csv returns Date as string e.g. "2026.04.23 18:55"
    tmp["time"] = pd.to_datetime(tmp["Date"], utc=True, errors="coerce")
    tmp = tmp.dropna(subset=["time"]).set_index("time")
    resampled = tmp.resample(rule, label="left", closed="left").agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
    ).dropna(subset=["Close"])
    resampled = resampled.reset_index()
    resampled["Date"] = resampled["time"].dt.strftime("%Y.%m.%d %H:%M")
    resampled["Source"] = "mt5-bridge"
    return resampled.drop(columns=["time"])


def _env_str(name: str, default: str) -> str:
    return str(os.environ.get(name, default)).strip()


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, default)).strip()
    try:
        return max(1, int(raw))
    except Exception:
        return default


def _log(message: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [mt5-bridge-sync] {message}", flush=True)


def _find_newest_csv(source_dir: Path, glob_pat: str) -> Path | None:
    if not source_dir.exists() or not source_dir.is_dir():
        return None
    matches = sorted(source_dir.glob(glob_pat), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _file_key(path: Path) -> tuple[str, int, int]:
    st = path.stat()
    return (str(path), int(st.st_mtime_ns), int(st.st_size))


def main() -> int:
    source_dir = Path(_env_str("MT5_BRIDGE_SOURCE_DIR", "/workspaces/newcpu/market-causality-lab/data/live/mt5/incoming")).expanduser().resolve()
    source_glob = _env_str("MT5_BRIDGE_SOURCE_GLOB", "XAUUSD*.csv")
    symbol = _env_str("MT5_BRIDGE_SYMBOL", "XAUUSD").upper()
    timeframe = _env_str("MT5_BRIDGE_TIMEFRAME", "5m").lower()
    out_dir = Path(_env_str("MT5_BRIDGE_OUT_DIR", "/workspaces/newcpu/market-causality-lab/data/live/mt5")).expanduser().resolve()
    poll_sec = _env_int("MT5_BRIDGE_POLL_SEC", 1)
    stable_polls = _env_int("MT5_BRIDGE_STABLE_POLLS", 1)
    lag_alert_sec = _env_int("MT5_BRIDGE_LAG_ALERT_SEC", 15)

    _log(
        "starting"
        f" source_dir={source_dir} glob={source_glob} symbol={symbol}"
        f" timeframe={timeframe} poll_sec={poll_sec} stable_polls={stable_polls}"
        f" lag_alert_sec={lag_alert_sec}"
    )

    last_processed: tuple[str, int, int] | None = None
    pending_key: tuple[str, int, int] | None = None
    pending_hits = 0
    idle_notice_at = 0.0
    lag_notice_at = 0.0

    while True:
        try:
            newest = _find_newest_csv(source_dir=source_dir, glob_pat=source_glob)
            if newest is None:
                now = time.time()
                if now >= idle_notice_at:
                    _log(f"no source file found yet in {source_dir} matching {source_glob}")
                    idle_notice_at = now + 60
                time.sleep(poll_sec)
                continue

            now = time.time()
            lag_sec = max(0.0, now - newest.stat().st_mtime)
            if lag_sec > float(lag_alert_sec) and now >= lag_notice_at:
                _log(
                    f"warning: source lag {lag_sec:.1f}s exceeds MT5_BRIDGE_LAG_ALERT_SEC={lag_alert_sec}"
                )
                lag_notice_at = now + 30

            key = _file_key(newest)
            if pending_key == key:
                pending_hits += 1
            else:
                pending_key = key
                pending_hits = 1

            if pending_hits < stable_polls:
                time.sleep(poll_sec)
                continue

            if last_processed == key:
                time.sleep(poll_sec)
                continue

            _log(f"processing source={newest}")
            df = _load_mt5_csv(newest)
            intraday, export_copy = _write_outputs(df=df, symbol=symbol, timeframe=timeframe, out_dir=out_dir)
            last_processed = key

            # Auto-generate higher timeframes by resampling the base feed
            for tf_label, resample_rule in _RESAMPLE_TFS.items():
                try:
                    df_rs = _resample_df(df, resample_rule)
                    _write_outputs(df=df_rs, symbol=symbol, timeframe=tf_label, out_dir=out_dir)
                except Exception as exc:
                    _log(f"warning: failed to resample {tf_label}: {exc}")

            _log(
                f"bridge updated rows={len(df)} tfs={timeframe}+"
                + ",".join(_RESAMPLE_TFS.keys())
                + f" intraday={intraday} export={export_copy}"
            )
        except KeyboardInterrupt:
            _log("stopped by keyboard interrupt")
            return 0
        except Exception as exc:
            _log(f"error: {exc}")

        time.sleep(poll_sec)


if __name__ == "__main__":
    raise SystemExit(main())
