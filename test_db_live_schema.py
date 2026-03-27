import databento as db

# Test the API key with a valid schema for live data
client = db.Live(key="REDACTED")

# Try subscribing to a valid schema (e.g., 'mbo') for ES.FUT
client.subscribe(
    dataset="GLBX.MDP3",
    schema="mbo",  # 'mbo' is a valid live schema
    stype_in="parent",
    symbols=["ES.FUT"],
)

# Print a few records to verify data is streaming
for i, record in enumerate(client):
    print(record)
    if i >= 5:
        break
