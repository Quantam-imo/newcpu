import redis
import json
from datetime import datetime

class CandleEngine:
    def __init__(self):
        import os
        import time
        host = os.environ.get("REDIS_HOST", "localhost")
        port = int(os.environ.get("REDIS_PORT", 6379))
        db = int(os.environ.get("REDIS_DB", 0))
        for attempt in range(3):
            try:
                self.redis = redis.Redis(host=host, port=port, db=db)
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(1)
                else:
                    raise e
        self.candles = {}

    def get_bucket(self, timestamp, timeframe):
        dt = datetime.fromisoformat(timestamp)
        minute = (dt.minute // timeframe) * timeframe
        return dt.replace(second=0, microsecond=0, minute=minute)

    # Map live feed symbols (e.g. GC.c.0, GCM6) to canonical names for cross-reader lookups
    _SYMBOL_ALIASES = {
        "GC.c.0": "XAUUSD", "GC.c.1": "XAUUSD", "GC.FUT": "XAUUSD",
        "GCM6": "XAUUSD", "GCQ6": "XAUUSD", "GCZ6": "XAUUSD",
    }

    def process_tick(self, symbol, price, timestamp):
        canonical = self._SYMBOL_ALIASES.get(symbol, symbol)
        for tf in [1, 5, 15]:
            bucket = self.get_bucket(timestamp, tf)
            bucket_epoch = int(bucket.timestamp())
            key = f"{symbol}_{tf}_{bucket}"
            if key not in self.candles:
                self.candles[key] = {
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1,
                    "time": bucket_epoch,
                    "timestamp": str(bucket),
                    "timeframe": tf,
                    "symbol": canonical
                }
            else:
                candle = self.candles[key]
                candle["high"] = max(candle["high"], price)
                candle["low"] = min(candle["low"], price)
                candle["close"] = price
                candle["volume"] += 1
            candle_data = json.dumps(self.candles[key])
            # Write latest key (for get_latest_candle)
            self.redis.set(f"candle:{canonical}:{tf}", candle_data)
            # Write timestamped key with 24h TTL (for get_candle_series)
            self.redis.setex(f"candle:{canonical}:{tf}:{bucket_epoch}", 86400, candle_data)
            # Also write under raw feed symbol for cross-lookup
            if canonical != symbol:
                self.redis.set(f"candle:{symbol}:{tf}", candle_data)
        print(f"[CANDLE UPDATE] {canonical} ({symbol}) → {price}")

    def get_latest_candle(self, symbol, timeframe):
        data = self.redis.get(f"candle:{symbol}:{timeframe}")
        if not data:
            return None
        return json.loads(data)
