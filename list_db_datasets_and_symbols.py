import os
import databento as db

API_KEY = os.environ.get("DATABENTO_API_KEY")
if not API_KEY:
    raise RuntimeError("DATABENTO_API_KEY not set in environment.")

client = db.Historical(key=API_KEY)

print("Listing available datasets and symbols for your API key...")

try:
    # List all datasets available to the API key
    datasets = client.metadata.list_datasets()
    print("\nAvailable datasets:")
    for ds in datasets:
        print(f"- {ds}")
except Exception as e:
    print(f"ERROR listing datasets: {e}")

# Try to list symbols for each dataset
for ds in datasets:
    try:
        print(f"\nSymbols for dataset {ds}:")
        symbols = client.metadata.list_symbols(dataset=ds)
        for sym in symbols[:10]:  # Print only first 10 for brevity
            print(f"  {sym}")
        if len(symbols) > 10:
            print(f"  ...and {len(symbols)-10} more")
    except Exception as e:
        print(f"  ERROR listing symbols for {ds}: {e}")
