import databento as db

# Create a live client
client = db.Live(key="db-9YYc6umB6fA7Yv9rF5YjVhFT6Sips")

# Subscribe with a specified start time for intraday replay
client.subscribe(
    dataset="GLBX.MDP3",
    schema="trades",
    symbols="ES.FUT",
    stype_in="parent",
    start="2023-04-17T09:00:00",
)

print("Subscription attempted. If no error, check your Databento portal or add a callback to receive data.")
