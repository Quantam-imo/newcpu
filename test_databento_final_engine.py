from datetime import datetime, timezone

from astroquant.engine.databento import AstroQuantFinalDataEngine


def main() -> None:
    engine = AstroQuantFinalDataEngine()

    start = datetime(2026, 3, 20, 13, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 3, 20, 14, 0, 0, tzinfo=timezone.utc)

    results = engine.fetch_synced_gc_es(start=start, end=end)

    for market, result in results.items():
        print(
            f"{market}: symbol={result.symbol} records={result.records} "
            f"window={result.start.isoformat()}->{result.end.isoformat()} "
            f"fallback={result.fallback_used} reason={result.reason}"
        )
        print(result.dataframe.head(2))


if __name__ == "__main__":
    main()
