import os
import databento as db


def main() -> None:
    api_key = os.environ.get("DATABENTO_API_KEY")
    if not api_key:
        raise RuntimeError("DATABENTO_API_KEY not set in environment.")

    # Test symbols for live endpoint (replace with symbols you expect to have access to)
    live_symbols = [
        "ESM6",  # S&P 500 E-mini (example)
        "NQH6",  # Nasdaq 100 E-mini (example)
        "GCZ6",  # Gold (example)
    ]

    print("Testing live endpoint for symbols:", live_symbols)
    client = db.Live(key=api_key)

    for symbol in live_symbols:
        try:
            print(f"\nTesting live symbol: {symbol}")
            # Try subscribing to the symbol (schema: trades)
            sub = client.subscribe(
                dataset="GLBX.MDP3",
                symbols=[symbol],
                schema="trades",
            )
            # Try to get a single message (if available)
            msg = next(sub, None)
            if msg:
                print(f"SUCCESS: Live data received for {symbol} (sample: {msg})")
            else:
                print(f"NO DATA: No live data for {symbol} (may be market closed or no access)")
        except Exception as e:
            print(f"ERROR: {symbol} - {e}")


if __name__ == "__main__":
    main()
