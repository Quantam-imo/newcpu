import databento as db


# Static, repo-style test: known-good symbol and time window (Friday US session)
API_KEY = "REDACTED"
DATASET = "GLBX.MDP3"
SCHEMA = "trades"
SYMBOL = "ES.c.0"  # S&P 500 E-mini continuous contract
# Friday, March 20, 2026, 14:00-16:00 UTC (during US session)
START = "2026-03-20T14:00:00Z"
END = "2026-03-20T16:00:00Z"

client = db.Historical(API_KEY)

try:
    data = client.timeseries.get_range(
        dataset=DATASET,
        schema=SCHEMA,
        symbols=SYMBOL,
        start=START,
        end=END,
    )
    print(data.to_df().head())
    print(f"Records fetched: {len(data)}")
except Exception as e:
    print(f"Error: {e}")
