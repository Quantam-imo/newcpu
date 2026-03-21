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

    def process_tick(self, symbol, price, timestamp):
        for tf in [1, 5, 15]:
            bucket = self.get_bucket(timestamp, tf)
            key = f"{symbol}_{tf}_{bucket}"
            if key not in self.candles:
                self.candles[key] = {
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1,
                    "timestamp": str(bucket),
                    "timeframe": tf,
                    "symbol": symbol
                }
            else:
                candle = self.candles[key]
                candle["high"] = max(candle["high"], price)
                candle["low"] = min(candle["low"], price)
                candle["close"] = price
                candle["volume"] += 1
            redis_key = f"candle:{symbol}:{tf}"
            self.redis.set(redis_key, json.dumps(self.candles[key]))
            print("[CANDLE UPDATE]", symbol, price, timestamp)

    def get_latest_candle(self, symbol, timeframe):
        data = self.redis.get(f"candle:{symbol}:{timeframe}")
        if not data:
            return None
        return json.loads(data)
