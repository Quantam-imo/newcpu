import databento as db

client = db.Historical("db-9YYc6umB6fA7Yv9rF5YjVhFT6Sips")

try:
    job = client.batch.submit_job(
        dataset="GLBX.MDP3",
        symbols="CLZ7",
        schema="trades",
        start="2022-06-06T00:00:00",
        end="2022-06-10T00:10:00",
        limit=10000,
    )
    print("Job submitted:", job)
except Exception as e:
    print("ERROR:", e)
