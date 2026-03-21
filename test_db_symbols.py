import os
import databento as db

API_KEY = os.environ.get("DATABENTO_API_KEY")
if not API_KEY:
    raise RuntimeError("DATABENTO_API_KEY not set in environment.")

DATASET = "GLBX.MDP3"
SYMBOLS = [
    "GC.c.1",  # XAUUSD
    "NQ.c.1",  # NQ
    "6E.c.1",  # EURUSD
    "BTC.c.1", # BTC
    "YM.c.1",  # US30
]

print(f"Testing access for dataset: {DATASET}")
client = db.Historical(key=API_KEY)

for symbol in SYMBOLS:
    try:
        print(f"\nTesting symbol: {symbol}")
        data = client.timeseries.get_range(
            dataset=DATASET,
            symbols=[symbol],
            schema="ohlcv-1m",
            start="2024-03-10T00:00:00+00:00",
            end="2024-03-10T00:05:00+00:00",
            limit=1
        )
        rows = list(data)
        if rows:
            print(f"SUCCESS: Data found for {symbol} (sample: {rows[0]})")
        else:
            print(f"NO DATA: {symbol} returned no rows.")
    except Exception as e:
        print(f"ERROR: {symbol} - {e}")
