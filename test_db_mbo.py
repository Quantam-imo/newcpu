import os
import databento as db

API_KEY = os.environ.get("DATABENTO_API_KEY", "db-9YYc6umB6fA7Yv9rF5YjVhFT6Sips")
client = db.Historical(API_KEY)

try:
    data = client.timeseries.get_range(
        dataset='GLBX.MDP3',
        schema='mbo',
        start='2023-01-09T00:00',
        end='2023-01-09T20:00',
        limit=100,
    )
    print("Replaying records:")
    data.replay(print)
except Exception as e:
    print(f"ERROR: {e}")
