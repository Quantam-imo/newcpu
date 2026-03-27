import databento as db
from datetime import datetime, timezone, timedelta


# Test with the symbol 'GCJ2026' as provided by the user
SYMBOLS = [
    ("GCJ2026", "GCJ2026"),
]

API_KEY = "REDACTED"  # <-- Databento API key

client = db.Historical(API_KEY)
results = {}

# Increase buffer to 15 minutes before now to avoid requesting data beyond available range
now = datetime.now(timezone.utc)
end = now - timedelta(minutes=15)
start = end - timedelta(minutes=30)


for broker_symbol, db_symbol in SYMBOLS:
    try:
        df = client.timeseries.get_range(
            dataset="GLBX.MDP3",
            schema="ohlcv-1m",
            symbols=[db_symbol],
            start=start.isoformat(),
            end=end.isoformat(),
            limit=10,
        )
        rows = list(df)
        results[broker_symbol] = f"OK: {len(rows)} rows"
    except Exception as e:
        results[broker_symbol] = f"ERROR: {e}"

print(results)
