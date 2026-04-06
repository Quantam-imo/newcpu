
import redis
import json
import os
import time

def get_redis_client(retries=3, delay=1):
    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", 6379))
    db = int(os.environ.get("REDIS_DB", 0))
    for attempt in range(retries):
        try:
            return redis.Redis(host=host, port=port, db=db)
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise e

redis_client = get_redis_client()


def get_latest_candle(symbol, timeframe=1):
    key = f"candle:{symbol}:{timeframe}"
    data = redis_client.get(key)
    if not data:
        return None
    return json.loads(data)

# Canonical alias map — same as candle_engine so reader can resolve symbol names
_SYMBOL_ALIASES = {
    "GC.c.0": "XAUUSD", "GC.c.1": "XAUUSD", "GC.FUT": "XAUUSD",
    "GCM6": "XAUUSD", "GCQ6": "XAUUSD", "GCZ6": "XAUUSD",
}


def _parse_tf(tf) -> int:
    """Convert timeframe string/int to integer minutes (e.g. '1m'->1, '1h'->60, '4h'->240)."""
    if isinstance(tf, int):
        return tf
    s = str(tf).strip().lower()
    if s.endswith('h'):
        return int(s[:-1]) * 60
    if s.endswith('d'):
        return int(s[:-1]) * 1440
    if s.endswith('m'):
        return int(s[:-1])
    try:
        return int(s)
    except ValueError:
        return 1


def get_candle_series(symbol, timeframe=1, limit=80):
    tf_int = _parse_tf(timeframe)
    canonical = _SYMBOL_ALIASES.get(str(symbol).upper(), symbol)
    # Try timestamped keys first (populated by live candle engine)
    # For timeframes not stored (e.g. 60min) fall back to nearest stored TF
    _available_tfs = [tf_int] if tf_int in (1, 5, 15) else [1]
    for try_tf in _available_tfs:
        pattern = f"candle:{canonical}:{try_tf}:*"
        keys = redis_client.keys(pattern)
        if keys:
            def extract_ts(k):
                parts = k.decode().split(":")
                return int(parts[-1]) if parts[-1].isdigit() else 0
            sorted_keys = sorted(keys, key=extract_ts, reverse=True)
            candles = []
            for k in sorted_keys[:limit]:
                data = redis_client.get(k)
                if data:
                    candles.append(json.loads(data))
            return candles[::-1]
    # Fallback: single latest key
    for try_tf in _available_tfs:
        single = redis_client.get(f"candle:{canonical}:{try_tf}")
        if single:
            return [json.loads(single)]
    return []
