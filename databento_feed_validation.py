import databento as db

client = db.Historical("REDACTED")

data = client.timeseries.get_range(
    dataset="GLBX.MDP3",
    schema="trades",
    symbols=["GCG2026"],   # Feb 2026 contract
    start="2026-03-22T02:00:00Z",
    end="2026-03-22T04:00:00Z",
)

print("Records:", len(data))
print(data[0] if len(data) > 0 else "No data")
import databento as db
from datetime import datetime, timedelta, timezone


API_KEY = "REDACTED"
SYMBOL = "GC.c.0"  # Use continuous contract symbol
DATASET = "GLBX.MDP3"
SCHEMA = "trades"

# 1. Fetch recent trades (last 2 days) with safe end time buffer


# Auto-detect last available timestamp for GC.c.0
def get_last_available_timestamp(client):
    # Query the most recent trade (limit=1, descending order)
    recent = client.timeseries.get_range(
        dataset=DATASET,
        schema=SCHEMA,
        symbols=[SYMBOL],
        start=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        end=datetime.now(timezone.utc).isoformat(),
        limit=1,
        order="desc",
    )
    if recent and hasattr(recent[0], "ts_event"):
        ts = recent[0].ts_event
        if isinstance(ts, str):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif isinstance(ts, datetime):
            return ts
    return None

client = db.Historical(key=API_KEY)

end = get_last_available_timestamp(client)
if not end:
    print("❌ Could not determine last available timestamp. No data available.")
    exit(1)
start = datetime(2026, 3, 21, 13, 0, 0, tzinfo=timezone.utc)

client = db.Historical(key=API_KEY)

data = client.timeseries.get_range(
    dataset=DATASET,
    schema=SCHEMA,
    symbols=[SYMBOL],
    start=start.isoformat(),
    end=end.isoformat(),
)

print(f"Records fetched: {len(data)}")

# 2. Structure validation
if not data or len(data) == 0:
    print("❌ No data returned")
else:
    print("✅ Data received:", len(data))
    sample = data[0]
    print("Sample record:", sample)
    if not hasattr(sample, "price") or not hasattr(sample, "ts_event"):
        print("❌ Invalid structure")
    else:
        print("✅ Structure valid")

# 3. Time validation
now = datetime.now(timezone.utc).timestamp() * 1000
future_count = 0
for d in data:
    ts = d.ts_event
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000
    elif isinstance(ts, datetime):
        ts = ts.timestamp() * 1000
    if ts > now:
        future_count += 1
if future_count:
    print(f"❌ {future_count} records have future timestamps!")
else:
    print("✅ No future timestamps")

# 4. Continuity check (detect gaps > 1 min)
gaps = 0
if len(data) > 1:
    prev = data[0].ts_event
    if isinstance(prev, str):
        prev = datetime.fromisoformat(prev.replace("Z", "+00:00")).timestamp() * 1000
    elif isinstance(prev, datetime):
        prev = prev.timestamp() * 1000
    for d in data[1:]:
        curr = d.ts_event
        if isinstance(curr, str):
            curr = datetime.fromisoformat(curr.replace("Z", "+00:00")).timestamp() * 1000
        elif isinstance(curr, datetime):
            curr = curr.timestamp() * 1000
        if curr - prev > 60000:
            gaps += 1
        prev = curr
print(f"Gaps found: {gaps}")

# Pro tip: Latency
if data:
    last_ts = data[-1].ts_event
    if isinstance(last_ts, str):
        last_ts = datetime.fromisoformat(last_ts.replace("Z", "+00:00")).timestamp() * 1000
    elif isinstance(last_ts, datetime):
        last_ts = last_ts.timestamp() * 1000
    latency = now - last_ts
    print(f"Feed latency: {latency:.0f} ms")
