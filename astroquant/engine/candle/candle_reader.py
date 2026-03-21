
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

# New function to fetch multiple candles
def get_candle_series(symbol, timeframe=1, limit=80):
    pattern = f"candle:{symbol}:{timeframe}:*"
    keys = redis_client.keys(pattern)
    # Sort keys by timestamp descending (assuming last part is timestamp)
    def extract_ts(k):
        parts = k.decode().split(":")
        return int(parts[-1]) if parts[-1].isdigit() else 0
    sorted_keys = sorted(keys, key=extract_ts, reverse=True)
    candles = []
    for k in sorted_keys[:limit]:
        data = redis_client.get(k)
        if data:
            candles.append(json.loads(data))
    # Reverse to ascending order for chart
    return candles[::-1]
