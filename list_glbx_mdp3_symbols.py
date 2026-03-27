import databento as db
from datetime import date
import json

# Replace with your actual API key or use environment variable
API_KEY = None  # or "db-..."

# Set your date range (adjust as needed)
START_DATE = date(2023, 1, 1)
END_DATE = date(2023, 12, 31)

client = db.Historical(key=API_KEY)

try:
    # Attempt to resolve all available raw symbols to parent symbology
    result = client.symbology.resolve(
        dataset="GLBX.MDP3",
        symbols="ALL_SYMBOLS",
        stype_in="raw_symbol",
        stype_out="parent",
        start_date=START_DATE,
        end_date=END_DATE
    )
    # Save result to file for inspection
    with open("glbx_mdp3_all_symbols.json", "w") as f:
        json.dump(result, f, indent=2)
    print("Symbol resolution result saved to glbx_mdp3_all_symbols.json")
except Exception as e:
    print(f"Error during symbol resolution: {e}")
