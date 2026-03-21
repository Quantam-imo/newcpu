#!/usr/bin/env python3
import os
from astroquant.engine.live_sync.live_sync_engine import LiveSyncEngine

if __name__ == "__main__":
    api_key = os.environ.get("DATABENTO_API_KEY")
    if not api_key:
        print("[ERROR] DATABENTO_API_KEY not set in environment.")
        exit(1)
    # Add all symbols you want to sync here
    symbols = ["GC.FUT"]
    engine = LiveSyncEngine(api_key)
    engine.subscribe(symbols)
    engine.start()
