#!/usr/bin/env python3
"""Fetch XAUUSD historical candles from Dukascopy BI5 and build daily backfill CSV.

This script targets the missing pre-2004 section and writes semicolon-delimited
CSV compatible with the existing market-causality-lab datasets.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import lzma
import struct
import urllib.error
import urllib.request
from pathlib import Path

URL_TEMPLATE = "https://datafeed.dukascopy.com/datafeed/XAUUSD/{year:04d}/{month:02d}/{day:02d}/BID_candles_min_1.bi5"


def _fmt_num(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def fetch_day(day: dt.date, timeout: int = 20) -> tuple[float, float, float, float, float] | None:
    url = URL_TEMPLATE.format(year=day.year, month=day.month - 1, day=day.day)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    except (urllib.error.URLError, TimeoutError):
        return None

    # Dukascopy may return an HTML error page with HTTP 200; detect and skip it.
    if raw.startswith(b"<!DOCTYPE") or raw.startswith(b"<html"):
        return None

    try:
        data = lzma.decompress(raw, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError:
        return None

    if len(data) % 24 != 0 or not data:
        return None

    o = h = l = c = None
    vol_sum = 0.0

    for i in range(0, len(data), 24):
        _off, opn, cls, low, high, vol = struct.unpack(">5if", data[i : i + 24])
        opn_f = opn / 1000.0
        cls_f = cls / 1000.0
        low_f = low / 1000.0
        high_f = high / 1000.0

        if o is None:
            o = opn_f
            h = high_f
            l = low_f

        c = cls_f
        h = max(h, high_f)
        l = min(l, low_f)
        vol_sum += float(vol)

    if o is None or c is None or h is None or l is None:
        return None

    return o, h, l, c, vol_sum


def date_range(start: dt.date, end: dt.date):
    cur = start
    while cur <= end:
        yield cur
        cur += dt.timedelta(days=1)


def write_csv(rows: list[tuple[str, str, str, str, str, str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill XAU daily candles from Dukascopy")
    parser.add_argument("--start", default="2000-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2004-06-10", help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--output",
        default="market-causality-lab/data/XAU_1d_backfill_2000_2004.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    out_path = Path(args.output)

    rows: list[tuple[str, str, str, str, str, str]] = []
    ok = 0
    missing = 0

    for day in date_range(start, end):
        candle = fetch_day(day)
        if candle is None:
            missing += 1
            continue

        o, h, l, c, vol = candle
        rows.append(
            (
                day.strftime("%Y.%m.%d 00:00"),
                _fmt_num(o),
                _fmt_num(h),
                _fmt_num(l),
                _fmt_num(c),
                _fmt_num(vol),
            )
        )
        ok += 1

    write_csv(rows, out_path)
    print(f"Wrote {len(rows)} rows to {out_path}")
    print(f"Fetched days: {ok}, missing/unavailable days: {missing}")
    if rows:
        print(f"Coverage: {rows[0][0]} -> {rows[-1][0]}")


if __name__ == "__main__":
    main()
