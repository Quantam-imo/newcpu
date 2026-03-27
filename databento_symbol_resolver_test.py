import databento as db

API_KEY = "REDACTED"
DATASET = "GLBX.MDP3"
SCHEMA = "trades"
START = "2026-03-22T02:00:00Z"
END = "2026-03-22T04:00:00Z"

client = db.Historical(API_KEY)

# Step 1: Test with known working symbol (ES.c.0)
try:
    data = client.timeseries.get_range(
        dataset=DATASET,
        schema=SCHEMA,
        symbols=["ES.c.0"],
        start=START,
        end=END,
    )
    print(f"ES.c.0 records: {len(data)}")
    print(data[0] if len(data) > 0 else "No data")
except Exception as e:
    print(f"ES.c.0 test failed: {e}")

# Step 2: Fetch instrument list for GC
try:
    instruments = client.reference.get_instruments(
        dataset=DATASET,
        symbols="GC"
    )
    print("GC instrument list:")
    print(instruments)
except Exception as e:
    print(f"Instrument fetch failed: {e}")
