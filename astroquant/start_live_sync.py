import os
from engine.live_sync.live_sync_engine import LiveSyncEngine

API_KEY = os.environ.get("DATABENTO_API_KEY")
if not API_KEY:
	raise RuntimeError("DATABENTO_API_KEY not set in environment. Please check your .env file.")

engine = LiveSyncEngine(API_KEY)
engine.subscribe(["GC.FUT", "ES.FUT"])  # Add more symbols as needed
engine.start()
