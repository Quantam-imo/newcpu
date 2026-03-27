import databento as db
from datetime import datetime, timezone, timedelta

API_KEY = "REDACTED"
client = db.Historical(API_KEY)

def get_sample_symbols():
    try:
        instruments = client.metadata.list_instruments(dataset="GLBX.MDP3", limit=50)
        symbols = [inst["symbol"] for inst in instruments]
        if not symbols:
            print("No symbols found for GLBX.MDP3.")
        else:
            print(f"Found {len(symbols)} symbols. Sample:")
            for symbol in symbols:
                print(symbol)
    except Exception as e:
        import traceback
        print(f"Error fetching instruments: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    get_sample_symbols()
