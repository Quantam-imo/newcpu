from datetime import datetime, timedelta, timezone


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def generate_fallback_bars(count=120):
    bars = []
    now = datetime.now(timezone.utc)
    price = 2350.0

    for index in range(count):
        t = now - timedelta(minutes=(count - index))
        move = ((index % 7) - 3) * 0.35
        open_price = price
        close_price = max(1.0, price + move)
        high_price = max(open_price, close_price) + 0.6
        low_price = min(open_price, close_price) - 0.6
        volume = 100 + (index % 20) * 12

        bars.append(
            {
                "time": t.isoformat(),
                "open": round(open_price, 2),
                "high": round(high_price, 2),
                "low": round(low_price, 2),
                "close": round(close_price, 2),
                "volume": volume,
            }
        )
        price = close_price

    return bars


def _parse_time_value(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 1_000_000_000_000:
            numeric /= 1000.0
        dt = datetime.fromtimestamp(numeric, tz=timezone.utc)
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def normalize_bars(raw_bars):
    normalized_by_time = {}
    for bar in raw_bars or []:
        raw_time = (
            bar.get("time")
            or bar.get("ts_event")
            or bar.get("timestamp")
            or datetime.now(timezone.utc).isoformat()
        )

        parsed_time = _parse_time_value(raw_time)
        if parsed_time is None:
            continue

        iso_time = parsed_time.isoformat()

        normalized_by_time[iso_time] = {
            "time": iso_time,
            "open": safe_float(bar.get("open", bar.get("o", 0))),
            "high": safe_float(bar.get("high", bar.get("h", 0))),
            "low": safe_float(bar.get("low", bar.get("l", 0))),
            "close": safe_float(bar.get("close", bar.get("c", 0))),
            "volume": max(0.0, safe_float(bar.get("volume", bar.get("v", 0)))),
        }

    return [normalized_by_time[key] for key in sorted(normalized_by_time.keys())]


def aggregate_bars(bars, timeframe="1m"):
    if not bars:
        return []

    tf_map = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "1h": 60,
        "4h": 240,
    }
    minutes = tf_map.get(str(timeframe or "").lower(), 1)

    buckets = {}
    for bar in bars:
        dt = _parse_time_value(bar.get("time"))
        if dt is None:
            continue

        minute_bucket = (dt.minute // minutes) * minutes
        bucket_time = dt.replace(minute=minute_bucket, second=0, microsecond=0)
        key = bucket_time.isoformat()

        existing = buckets.get(key)
        if existing is None:
            buckets[key] = {
                "time": key,
                "open": safe_float(bar.get("open", 0)),
                "high": safe_float(bar.get("high", 0)),
                "low": safe_float(bar.get("low", 0)),
                "close": safe_float(bar.get("close", 0)),
                "volume": max(0.0, safe_float(bar.get("volume", 0))),
            }
            continue

        existing["high"] = max(existing["high"], safe_float(bar.get("high", existing["high"])))
        existing["low"] = min(existing["low"], safe_float(bar.get("low", existing["low"])))
        existing["close"] = safe_float(bar.get("close", existing["close"]))
        existing["volume"] += max(0.0, safe_float(bar.get("volume", 0)))

    aggregated = [buckets[key] for key in sorted(buckets.keys())]
    return aggregated
