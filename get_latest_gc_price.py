import databento as db
import pandas as pd
from datetime import datetime, timedelta, timezone

# Example: Get latest trade price for GC.FUT (Gold Futures)
# Dataset for CME Globex: GLBX.MDP3
# Schema: trades (for last trade), or ohlcv-1m for candles


# Set your API key here if not using the environment variable
API_KEY = "db-9YYc6umB6fA7Yv9rF5YjVhFT6Sips"  # Replace with your actual key if needed
client = db.Historical(key=API_KEY)


# Set to the last available time from the error: 2026-03-19 05:30:00+00:00
to_time = datetime(2026, 3, 19, 5, 30, 0, tzinfo=timezone.utc)
from_time = to_time - timedelta(minutes=5)

symbol = "GC.FUT"
dataset = "GLBX.MDP3"
schema = "trades"

# Fetch the latest trade (limit=1, sorted by time desc)
data = client.timeseries.get_range(
    dataset=dataset,
    symbols=[symbol],
    schema=schema,
    start=from_time.isoformat(),
    end=to_time.isoformat(),
    limit=1
)
df = data.to_df()

if not df.empty:
    last_trade = df.iloc[-1]
    print(f"Symbol: {symbol}")
    print(f"Timestamp: {last_trade['ts_event']}")
    print(f"Price: {last_trade['price']}")
    print(f"Size: {last_trade['size']}")
else:
    print("No recent trades found.")
