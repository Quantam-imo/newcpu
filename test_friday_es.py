import databento as db
import os


def main() -> None:
    api_key = str(os.getenv("DATABENTO_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("DATABENTO_API_KEY is required to run this script")

    client = db.Historical(api_key)

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


if __name__ == "__main__":
    main()
