import databento as db

client = db.Historical("db-sfFfTe5QH8NsyXVrK9yMsUsGHmYfT")

data = client.timeseries.get_range(
    dataset="GLBX.MDP3",
    schema="trades",
    symbols=["ESH6"],   # ES March 2026
    start="2026-03-20T13:00:00Z",  # Friday US session
    end="2026-03-20T14:00:00Z",
)

df = data.to_df()

print("Records:", len(df))
print(df.head())
