import databento as db
from datetime import datetime, timedelta

API_KEY = "REDACTED"
DATASET = "GLBX.MDP3"
SCHEMA = "trades"

# List of possible contract codes for Gold (GC) 2026
CONTRACTS = [
    "GCG2026",  # Feb
    "GCH2026",  # Mar
    "GCJ2026",  # Apr
    "GCM2026",  # Jun
    "GCQ2026",  # Aug
    "GCV2026",  # Oct
    "GCZ2026",  # Dec
]

SAFE_END = "2026-03-22T04:00:00Z"  # From Databento error message
SAFE_START = "2026-03-22T02:00:00Z"  # 2 hours before

client = db.Historical(API_KEY)

success = False
for symbol in CONTRACTS:
    try:
        data = client.timeseries.get_range(
            dataset=DATASET,
            schema=SCHEMA,
            symbols=[symbol],
            start=SAFE_START,
            end=SAFE_END,
        )
        print(f"Tried symbol: {symbol} | Records: {len(data)}")
        if len(data) > 0:
            print("Sample:", data[0])
            success = True
            break
    except Exception as e:
        print(f"Symbol {symbol} failed: {e}")

if not success:
    print("No valid contract found for this window. Check Databento portal for active contracts.")
