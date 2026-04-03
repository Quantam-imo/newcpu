#!/usr/bin/env python3
"""Backfill XAU 5m/30m from Dukascopy and rebuild 4h from 1h history.

Outputs and updates:
- market-causality-lab/data/XAU_5m_backfill_2000_2004.csv
- market-causality-lab/data/XAU_30m_backfill_2000_2004.csv
- merge into XAU_5m_data.csv and XAU_30m_data.csv
- rebuild XAU_4h_data.csv from XAU_1h_data.csv
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import lzma
import struct
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

URL_TEMPLATE = "https://datafeed.dukascopy.com/datafeed/XAUUSD/{year:04d}/{month:02d}/{day:02d}/BID_candles_min_1.bi5"


def _fmt(value: float) -> str:
    s = f"{value:.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _day_iter(start: dt.date, end: dt.date):
    cur = start
    while cur <= end:
        yield cur
        cur += dt.timedelta(days=1)


def _fetch_minute_day(day: dt.date, timeout: int = 20):
    url = URL_TEMPLATE.format(year=day.year, month=day.month - 1, day=day.day)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    except (urllib.error.URLError, TimeoutError):
        return None

    if raw.startswith(b"<!DOCTYPE") or raw.startswith(b"<html"):
        return None

    try:
        data = lzma.decompress(raw, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError:
        return None

    if not data or len(data) % 24 != 0:
        return None

    out = []
    day_start = dt.datetime.combine(day, dt.time())
    for i in range(0, len(data), 24):
        off, o, c, l, h, v = struct.unpack(">5if", data[i : i + 24])
        ts = day_start + dt.timedelta(seconds=int(off))
        out.append((ts, o / 1000.0, h / 1000.0, l / 1000.0, c / 1000.0, float(v)))
    return out


def _aggregate(rows, step_minutes: int):
    buckets = {}
    for ts, o, h, l, c, v in rows:
        minute = (ts.minute // step_minutes) * step_minutes
        key = ts.replace(minute=minute, second=0, microsecond=0)

        if key not in buckets:
            buckets[key] = [o, h, l, c, v, ts]
        else:
            b = buckets[key]
            if ts < b[5]:
                b[0] = o
                b[5] = ts
            b[1] = max(b[1], h)
            b[2] = min(b[2], l)
            b[3] = c
            b[4] += v

    out = []
    for key in sorted(buckets.keys()):
        o, h, l, c, v, _ = buckets[key]
        out.append([
            key.strftime("%Y.%m.%d %H:%M"),
            _fmt(o),
            _fmt(h),
            _fmt(l),
            _fmt(c),
            _fmt(v),
        ])
    return out


def _write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
        w.writerows(rows)


def _load_rows(path: Path):
    rows = {}
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.reader(f, delimiter=";")
        next(r, None)
        for row in r:
            if len(row) >= 6 and row[0].strip():
                rows[row[0].strip()] = row[:6]
    return rows


def _merge_into(main_path: Path, backfill_path: Path):
    all_rows = {}
    if main_path.exists():
        all_rows.update(_load_rows(main_path))
    if backfill_path.exists():
        # Backfill should be authoritative for overlapping early timestamps.
        all_rows.update(_load_rows(backfill_path))

    keys = sorted(all_rows.keys())
    _write_csv(main_path, [all_rows[k] for k in keys])
    return len(keys), keys[0], keys[-1]


def _rebuild_4h_from_1h(h1_path: Path, out_path: Path):
    buckets = {}
    with h1_path.open(newline="", encoding="utf-8") as f:
        r = csv.reader(f, delimiter=";")
        next(r, None)
        for row in r:
            if len(row) < 6:
                continue
            try:
                ts = dt.datetime.strptime(row[0].strip(), "%Y.%m.%d %H:%M")
            except ValueError:
                continue
            key_hour = (ts.hour // 4) * 4
            key = ts.replace(hour=key_hour, minute=0, second=0, microsecond=0)
            o, h, l, c, v = map(float, row[1:6])

            if key not in buckets:
                buckets[key] = [o, h, l, c, v, ts]
            else:
                b = buckets[key]
                if ts < b[5]:
                    b[0] = o
                    b[5] = ts
                b[1] = max(b[1], h)
                b[2] = min(b[2], l)
                b[3] = c
                b[4] += v

    rows = []
    for key in sorted(buckets.keys()):
        o, h, l, c, v, _ = buckets[key]
        rows.append([
            key.strftime("%Y.%m.%d %H:%M"),
            _fmt(o),
            _fmt(h),
            _fmt(l),
            _fmt(c),
            _fmt(v),
        ])

    _write_csv(out_path, rows)
    return len(rows), rows[0][0], rows[-1][0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2000-01-01")
    parser.add_argument("--end", default="2004-06-10")
    parser.add_argument("--data-dir", default="market-causality-lab/data")
    args = parser.parse_args()

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    data_dir = Path(args.data_dir)

    rows_5m = []
    rows_30m = []
    ok_days = 0
    missing_days = 0

    for i, day in enumerate(_day_iter(start, end), start=1):
        minute_rows = _fetch_minute_day(day)
        if not minute_rows:
            missing_days += 1
            continue

        rows_5m.extend(_aggregate(minute_rows, 5))
        rows_30m.extend(_aggregate(minute_rows, 30))
        ok_days += 1

        if i % 200 == 0:
            print(f"processed_days={i} ok={ok_days} missing={missing_days}")

    back_5m = data_dir / "XAU_5m_backfill_2000_2004.csv"
    back_30m = data_dir / "XAU_30m_backfill_2000_2004.csv"
    _write_csv(back_5m, rows_5m)
    _write_csv(back_30m, rows_30m)
    print(f"wrote {len(rows_5m)} rows -> {back_5m}")
    print(f"wrote {len(rows_30m)} rows -> {back_30m}")

    main_5m = data_dir / "XAU_5m_data.csv"
    main_30m = data_dir / "XAU_30m_data.csv"
    cnt5, lo5, hi5 = _merge_into(main_5m, back_5m)
    cnt30, lo30, hi30 = _merge_into(main_30m, back_30m)
    print(f"merged 5m rows={cnt5} coverage={lo5} -> {hi5}")
    print(f"merged 30m rows={cnt30} coverage={lo30} -> {hi30}")

    h1_path = data_dir / "XAU_1h_data.csv"
    out_4h = data_dir / "XAU_4h_data.csv"
    cnt4, lo4, hi4 = _rebuild_4h_from_1h(h1_path, out_4h)
    print(f"rebuilt 4h rows={cnt4} coverage={lo4} -> {hi4}")


if __name__ == "__main__":
    main()
