
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
        redis_db = int(os.environ.get("REDIS_DB", 0))
        for attempt in range(3):
            try:
                self.redis = redis.Redis(host=host, port=port, db=redis_db)
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(1)
                else:
                    raise e
        self.symbols = []
        self.running = False
        self.candle_engine = CandleEngine()
        # instrument_id → feed symbol mapping (populated from SymbolMappingMsg)
        self._instrument_map: dict[int, str] = {}

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
        try:
            for msg in self.client:
                try:
                    self.process_message(msg)
                except Exception as e:
                    print("[ERROR]", e)
        except Exception as e:
            err = str(e)
            if "resolve symbol" in err.lower() or "symbol_resolution" in err.lower():
                print(f"[LIVE SYNC] Symbol resolution failed — market may be closed or symbol incorrect: {e}")
            elif "authentication" in err.lower() or "unauthorized" in err.lower():
                print(f"[LIVE SYNC] Auth error — check DATABENTO_API_KEY: {e}")
            else:
                print(f"[LIVE SYNC] Stream ended: {e}")

    def process_message(self, msg):
        rtype_name = type(msg).__name__

        # SymbolMappingMsg — build instrument_id → symbol lookup table
        if rtype_name == "SymbolMappingMsg":
            sym = getattr(msg, "stype_in_symbol", None) or getattr(msg, "stype_out_symbol", None)
            iid = getattr(msg, "instrument_id", None)
            if iid and sym:
                self._instrument_map[iid] = sym
                print(f"[LIVE SYNC] Mapped instrument_id={iid} → {sym}")
            return

        # SystemMsg — informational, not an error
        if rtype_name == "SystemMsg":
            print(f"[LIVE SYNC] System: {getattr(msg, 'msg', repr(msg))}")
            return

        # ErrorMsg — log but don't crash
        if rtype_name == "ErrorMsg" or hasattr(msg, "error"):
            print(f"[LIVE SYNC] Error from feed: {getattr(msg, 'err', repr(msg))}")
            return

        # TradeMsg — process tick
        if not hasattr(msg, "price"):
            return  # skip unknown message types silently

        try:
            price = msg.price / 1e9
            if price <= 0:
                return

            # Resolve symbol: try attribute first, then instrument_id map, then subscribed list
            symbol = (
                getattr(msg, "symbol", None)
                or self._instrument_map.get(getattr(msg, "instrument_id", None))
                or (self.symbols[0] if self.symbols else "UNKNOWN")
            )

            data = {
                "symbol": symbol,
                "price": price,
                "timestamp": str(msg.ts_event)
            }
            key = f"market:{symbol}"
            self.redis.set(key, json.dumps(data))
            # --- Candle Engine integration ---
            self.candle_engine.process_tick(
                symbol,
                price,
                str(msg.ts_event)
            )
            print(f"[LIVE] {symbol} → {price}")
        except Exception as e:
            print(f"[PROCESS ERROR] {e}")