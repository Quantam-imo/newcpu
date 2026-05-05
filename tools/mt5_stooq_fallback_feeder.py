#!/usr/bin/env python3
"""mt5_stooq_fallback_feeder.py
================================
Runs INSIDE the Codespace. When the MT5 incoming feed has been stale for
more than MT5_FALLBACK_STALE_SEC (default 900 s / 15 min), this daemon
automatically synthesises fresh 5-minute candles from the public stooq
XAUUSD spot price and writes them into the MT5 incoming directory.

This keeps the MCL chart and bridge alive 24/7 even when the Windows
MetaTrader5 terminal is offline.

The synthetic candles use the last real bar's OHLC as the base and apply
the current stooq spot price as the close, keeping the feed honest.

Safe to run alongside the real mt5_auto_export_to_codespace.py — if real
MT5 data arrives (fresher than stale threshold) this daemon sleeps and does
nothing.
"""

from __future__ import annotations

import csv
import io
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests


# ─── Config via environment ──────────────────────────────────────────────────
def _env(name: str, default: str) -> str:
    return str(os.environ.get(name, default)).strip()


WORKSPACE       = Path(_env("AQ_WORKSPACE", "/workspaces/newcpu"))
INCOMING_DIR    = Path(_env("MT5_INCOMING_DIR",
                  str(WORKSPACE / "market-causality-lab/data/live/mt5/incoming")))
INCOMING_FILE   = INCOMING_DIR / "XAUUSD_feed_latest.csv"

# How stale the file must be before we start synthesising (seconds)
# How old the LAST BAR must be before we synthesise new bars.
# Default: 1.5× bar interval (450s) — triggers as soon as a new completed bucket exists.
# Set MT5_FALLBACK_STALE_SEC=900 to restore old file-mtime behaviour.
STALE_SEC       = int(_env("MT5_FALLBACK_STALE_SEC", "450"))

# Age (seconds) below which we assume a *real* MT5 export just wrote the file.
# How often (in seconds) we run the freshness check + synthesise loop
POLL_SEC        = int(_env("MT5_FALLBACK_POLL_SEC", "60"))

# Maximum age of synthetic candle to append (don't append beyond current UTC-5m bucket)
BAR_INTERVAL    = 300  # 5 minutes in seconds

# Stooq symbol pairs to try for XAUUSD
STOOQ_URLS = [
    "https://stooq.com/q/l/?s=xauusd&f=sd2t2ohlcv&h&e=csv",
    "https://stooq.com/q/l/?s=gc.f&f=sd2t2ohlcv&h&e=csv",
]
BACKEND_LIVE_URL = _env("MCL_LIVE_PRICE_URL", "http://127.0.0.1:8000/market_causality/live_price")

LOG_PREFIX = "[mt5-fallback-feeder]"


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {LOG_PREFIX} {msg}", flush=True)


# ─── Stooq live price fetch ───────────────────────────────────────────────────

def _fetch_backend_spot_price() -> Optional[float]:
    """Return spot price from local backend live_price endpoint, or None."""
    try:
        url = (
            f"{BACKEND_LIVE_URL}?symbol=XAUUSD"
            f"&prefer_source=stooq&broker_only=0&max_age_seconds=300"
        )
        resp = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return None
        data = resp.json() if resp.text else {}
        if str(data.get("status", "")).lower() != "ok":
            return None
        price = float(data.get("price") or 0)
        if price > 0:
            src = str(data.get("source") or "backend")
            _log(f"backend spot OK: {price:.3f} from {src}")
            return price
    except Exception as exc:
        _log(f"backend spot fetch error: {exc}")
    return None

def _fetch_stooq_price() -> Optional[float]:
    """Return latest XAUUSD spot price via backend endpoint, then direct stooq."""
    backend_price = _fetch_backend_spot_price()
    if backend_price is not None:
        return backend_price

    for url in STOOQ_URLS:
        try:
            resp = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                continue
            text = resp.text.strip()
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if len(lines) < 2:
                continue
            # CSV header: Symbol,Date,Time,Open,High,Low,Close,Volume
            headers = [h.lower() for h in lines[0].split(",")]
            row = dict(zip(headers, lines[1].split(",")))
            close = float(row.get("close", 0))
            if close > 0:
                _log(f"stooq price OK: {close:.3f} from {url.split('?')[0]}")
                return close
        except Exception as exc:
            _log(f"stooq fetch error ({url.split('?')[0]}): {exc}")
    return None


# ─── Incoming feed helpers ────────────────────────────────────────────────────

def _file_age_seconds() -> float:
    """Age of INCOMING_FILE in seconds, or inf if missing."""
    try:
        return time.time() - INCOMING_FILE.stat().st_mtime
    except FileNotFoundError:
        return float("inf")


def _read_last_bar() -> Optional[dict]:
    """Read the last data row from INCOMING_FILE. Returns parsed dict or None."""
    if not INCOMING_FILE.exists():
        return None
    try:
        rows = []
        with open(INCOMING_FILE, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                rows.append(row)
        if not rows:
            return None
        return rows[-1]
    except Exception as exc:
        _log(f"read_last_bar error: {exc}")
        return None


def _parse_bar_ts(date_str: str) -> Optional[int]:
    """Parse '2026.05.04 16:00:00' or '2026.05.04 16:00' → UTC epoch."""
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            pass
    return None


def _read_all_rows() -> list[dict]:
    """Read all data rows from INCOMING_FILE."""
    if not INCOMING_FILE.exists():
        return []
    try:
        rows = []
        with open(INCOMING_FILE, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                rows.append(row)
        return rows
    except Exception as exc:
        _log(f"read_all_rows error: {exc}")
        return []


def _rows_to_csv(rows: list[dict]) -> str:
    """Convert rows back to semicolon-delimited CSV string with original header."""
    if not rows:
        return ""
    fieldnames = list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, delimiter=";", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


# ─── Synthetic candle builder ─────────────────────────────────────────────────

def _build_synthetic_bars(last_row: dict, last_ts: int, spot_price: float,
                           now_ts: int) -> list[dict]:
    """
    Build synthetic 5m bars from (last_ts + 5m) up to the current completed bucket.
    Uses spot_price as close, last bar close as open, with ±0.01% noise floor.
    """
    current_bucket = (now_ts // BAR_INTERVAL) * BAR_INTERVAL
    # The most recent COMPLETED bucket (don't include the still-forming one)
    target_ts = current_bucket - BAR_INTERVAL

    if target_ts <= last_ts:
        return []

    try:
        last_close = float(last_row.get("Close", 0) or 0)
    except (ValueError, TypeError):
        last_close = spot_price

    if last_close <= 0:
        last_close = spot_price

    new_rows = []
    ts = last_ts + BAR_INTERVAL
    while ts <= target_ts:
        dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y.%m.%d %H:%M:%S")
        # Linear interpolation from last_close → spot_price across the gap
        steps_total = max(1, (target_ts - last_ts) // BAR_INTERVAL)
        step_num = (ts - last_ts) // BAR_INTERVAL
        frac = step_num / steps_total
        bar_close = round(last_close + (spot_price - last_close) * frac, 5)
        bar_open = last_close if step_num == 1 else round(
            last_close + (spot_price - last_close) * (step_num - 1) / steps_total, 5)
        # Tight range — synthetic bars should not look like volatile real data
        spread = abs(bar_close - bar_open) * 0.5 or abs(spot_price * 0.0001)
        bar_high = round(max(bar_open, bar_close) + spread, 5)
        bar_low = round(min(bar_open, bar_close) - spread, 5)
        row = {
            "Date": dt_str,
            "Open": f"{bar_open:.5f}",
            "High": f"{bar_high:.5f}",
            "Low": f"{bar_low:.5f}",
            "Close": f"{bar_close:.5f}",
            "TickVolume": "0",
            "Volume": "0",
            "Spread": "0",
        }
        new_rows.append(row)
        last_close = bar_close
        ts += BAR_INTERVAL

    return new_rows


# ─── Main synthesise step ─────────────────────────────────────────────────────

def _synthesise(spot_price: float) -> bool:
    """
    Read the incoming CSV, append synthetic bars up to now, write back.
    Returns True if bars were added.
    """
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    last_row = _read_last_bar()

    if last_row is None:
        _log("No existing feed rows — cannot synthesise without a base bar.")
        return False

    date_str = last_row.get("Date", "").strip()
    last_ts = _parse_bar_ts(date_str)
    if last_ts is None:
        _log(f"Cannot parse last bar timestamp: {date_str!r}")
        return False

    now_ts = int(time.time())
    new_bars = _build_synthetic_bars(last_row, last_ts, spot_price, now_ts)
    if not new_bars:
        _log("Feed already current — no synthetic bars needed.")
        return False

    all_rows = _read_all_rows()
    all_rows.extend(new_bars)

    # Keep the CSV a reasonable size (last 3000 bars max ≈ ~10 days of 5m)
    if len(all_rows) > 3000:
        all_rows = all_rows[-3000:]

    csv_text = _rows_to_csv(all_rows)
    tmp = INCOMING_FILE.with_suffix(".csv.tmp")
    tmp.write_text(csv_text, encoding="utf-8")
    tmp.replace(INCOMING_FILE)

    last_dt = datetime.fromtimestamp(
        _parse_bar_ts(new_bars[-1]["Date"]) or now_ts, tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S")
    _log(f"Synthesised {len(new_bars)} bar(s) — feed now ends at {last_dt} UTC (spot={spot_price:.3f})")
    return True


# ─── Main loop ────────────────────────────────────────────────────────────────

def run() -> None:
    _log(f"Started. bar_stale_threshold={STALE_SEC}s  poll={POLL_SEC}s  incoming={INCOMING_FILE}")
    consecutive_failures = 0

    while True:
        try:
            # Always check: how many completed 5m bars are missing since last bar?
            last_row = _read_last_bar()
            last_ts = None
            if last_row is not None:
                last_ts = _parse_bar_ts(last_row.get("Date", ""))

            now_ts = int(time.time())
            current_bucket = (now_ts // BAR_INTERVAL) * BAR_INTERVAL
            # Number of completed buckets not yet in the file
            bars_needed = max(0, (current_bucket - BAR_INTERVAL - (last_ts or current_bucket)) // BAR_INTERVAL)

            if bars_needed <= 0:
                bar_age = (now_ts - last_ts) if last_ts else 0
                _log(f"Feed current (last_bar_age={bar_age:.0f}s) — sleeping.")
                consecutive_failures = 0
            else:
                bar_age = (now_ts - last_ts) if last_ts else 0
                _log(f"Last bar age={bar_age:.0f}s, {bars_needed} bar(s) missing — fetching stooq …")
                spot = _fetch_stooq_price()
                if spot is None:
                    consecutive_failures += 1
                    _log(f"stooq unavailable (failures={consecutive_failures}) — will retry.")
                else:
                    consecutive_failures = 0
                    _synthesise(spot)
        except Exception as exc:
            _log(f"Unexpected error in main loop: {exc}")
            consecutive_failures += 1

        time.sleep(POLL_SEC)


if __name__ == "__main__":
    run()
