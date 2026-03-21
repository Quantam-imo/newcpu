
import databento as db
import redis
import json
from datetime import datetime
from astroquant.engine.candle.candle_engine import CandleEngine

class LiveSyncEngine:
    def __init__(self, api_key):
        self.client = db.Live(api_key)
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
        self.symbols = []
        self.running = False
        self.candle_engine = CandleEngine()

    def subscribe(self, symbols):
        self.symbols = symbols
        self.client.subscribe(
            dataset="GLBX.MDP3",
            schema="trades",
            symbols=symbols
        )

    def start(self):
        print("[LIVE SYNC] Starting engine...")
        self.running = True
        for msg in self.client:
            try:
                self.process_message(msg)
            except Exception as e:
                print("[ERROR]", e)

    def process_message(self, msg):
        # Handle error messages from Databento
        if hasattr(msg, 'error') or not hasattr(msg, 'price'):
            print(f"[DATABENTO ERROR] {getattr(msg, 'error', repr(msg))}")
            return
        try:
            price = msg.price / 1e9
            data = {
                "symbol": msg.symbol,
                "price": price,
                "timestamp": str(msg.ts_event)
            }
            key = f"market:{msg.symbol}"
            self.redis.set(key, json.dumps(data))
            # --- Candle Engine integration ---
            self.candle_engine.process_tick(
                msg.symbol,
                price,
                str(msg.ts_event)
            )
            print(f"[LIVE] {msg.symbol} → {price}")
        except Exception as e:
            print(f"[PROCESS ERROR] {e}")