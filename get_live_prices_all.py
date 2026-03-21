import os
import databento as db
from datetime import datetime, timezone, timedelta
import threading

from dotenv import load_dotenv
import os
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
# Canonical to Databento symbol mapping
SYMBOL_MAP = {
    "XAUUSD": "GC.c.1",
    "NQ": "NQ.c.1",
    "EURUSD": "6E.c.1",
    "BTC": "BTC.c.1",
    "US30": "YM.c.1",
}

DATASET = "GLBX.MDP3"
SCHEMA = "trades"  # Use 'trades' for tick/trade prices
API_KEY = os.environ.get("DATABENTO_API_KEY")

if not API_KEY:
    raise RuntimeError("DATABENTO_API_KEY not set in environment.")

latest_prices = {}
lock = threading.Lock()

def on_record(symbol):
    def _callback(record):
        price = getattr(record, "price", None)
        ts = getattr(record, "ts_event", None)
        if price is not None and ts is not None:
            with lock:
                latest_prices[symbol] = (float(price), ts)
            print(f"{symbol}: price={price} time={ts}")
    return _callback

def on_error(symbol):
    def _callback(exc):
        print(f"Error for {symbol}: {exc}")
    return _callback

threads = []
clients = []

for canonical, db_symbol in SYMBOL_MAP.items():
    client = db.Live(key=API_KEY)
    client.add_callback(on_record(canonical), on_error(canonical))
    client.subscribe(
        dataset=DATASET,
        schema=SCHEMA,
        symbols=[db_symbol],
        stype_in="continuous",
        start=datetime.now(timezone.utc) - timedelta(minutes=2),
    )
    t = threading.Thread(target=client.start, daemon=True)
    t.start()
    threads.append(t)
    clients.append(client)

print("Subscribed to live prices. Press Ctrl+C to exit.")
try:
    while True:
        pass
except KeyboardInterrupt:
    print("\nTerminating...")
    for client in clients:
        try:
            client.terminate()
        except Exception:
            pass
