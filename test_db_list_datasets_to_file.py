import databento as db

client = db.Historical("REDACTED")

datasets = client.metadata.list_datasets()

with open("db_datasets_list.txt", "w") as f:
    for ds in datasets:
        f.write(str(ds) + "\n")

print("Dataset list written to db_datasets_list.txt")
