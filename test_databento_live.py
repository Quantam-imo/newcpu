import databento as db


def main() -> None:
    # Create a live client
    client = db.Live(key="REDACTED")

    # Subscribe with a specified start time for intraday replay
    client.subscribe(
        dataset="GLBX.MDP3",
        schema="trades",
        symbols="ES.FUT",
        stype_in="parent",
        start="2023-04-17T09:00:00",
    )

    print("Subscription attempted. If no error, check your Databento portal or add a callback to receive data.")


if __name__ == "__main__":
    main()
