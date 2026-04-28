import databento as db


def main() -> None:
	# Establish connection and authenticate
	client = db.Historical("REDACTED")

	# Authenticated request: list available datasets
	print(client.metadata.list_datasets())


if __name__ == "__main__":
	main()
