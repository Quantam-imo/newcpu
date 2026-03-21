
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

def get_latest_tick(symbol):
    key = f"market:{symbol}"
    data = redis_client.get(key)
    if not data:
        return None
    return json.loads(data)

def is_data_fresh(data):
    from datetime import datetime
    now = datetime.utcnow()
    ts = datetime.fromisoformat(data["timestamp"])
    delay = (now - ts).total_seconds()
    return delay < 2
