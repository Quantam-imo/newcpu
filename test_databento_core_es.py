"""
Test Databento core: fetch ES.c.0 with correct stype_in (continuous)
"""
from databento_core import fetch_historical_data
from datetime import datetime, timedelta, timezone

API_KEY = None  # Use env or set here
SYMBOL = "ES.c.0"
DATASET = "GLBX.MDP3"
SCHEMA = "trades"
# Friday, March 20, 2026, 14:00-16:00 UTC
START = "2026-03-20T14:00:00Z"
END = "2026-03-20T16:00:00Z"

try:
    data = fetch_historical_data(
        symbol=SYMBOL,
        start=START,
        end=END,
        schema=SCHEMA,
        dataset=DATASET,
        api_key=API_KEY,
    )
    df = data.to_df()
    print(df.head())
    print(f"Records fetched: {len(df)}")
except Exception as e:
    print(f"Error: {e}")