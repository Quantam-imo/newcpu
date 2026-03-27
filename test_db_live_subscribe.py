import databento as db

# Create a live client
client = db.Live(key="REDACTED")

# Authentication happens on the first subscribe
client.subscribe(
    dataset="GLBX.MDP3",
    schema="trades",
    stype_in="parent",
    symbols=["ES.FUT"],  # Use a list, not a string
)

# Print a few records to verify data is streaming
for i, record in enumerate(client):
    print(record)
    if i >= 5:
        break
