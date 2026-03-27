import databento as db

# Establish connection and authenticate
client = db.Historical("REDACTED")

# Authenticated request: list available datasets
print(client.metadata.list_datasets())
