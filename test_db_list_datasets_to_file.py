import databento as db


def main() -> None:
    client = db.Historical("REDACTED")

    datasets = client.metadata.list_datasets()

    with open("db_datasets_list.txt", "w") as f:
        for ds in datasets:
            f.write(str(ds) + "\n")

    print("Dataset list written to db_datasets_list.txt")


if __name__ == "__main__":
    main()
