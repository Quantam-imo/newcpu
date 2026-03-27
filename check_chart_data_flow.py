import requests
import sys

# List of broker symbols to check
SYMBOLS = ["XAUUSD", "NQ", "EURUSD", "BTC", "US30"]
API_URL = "http://127.0.0.1:8000/chart/data"

results = {}

for symbol in SYMBOLS:
    params = {
        "symbol": symbol,
        "limit": 10,
        "timeframe": "1"
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            candles = data.get("candles", [])
            if candles:
                results[symbol] = f"OK: {len(candles)} candles"
            else:
                results[symbol] = f"EMPTY: No candles returned"
        else:
            results[symbol] = f"HTTP {resp.status_code}: {resp.text[:100]}"
    except Exception as e:
        results[symbol] = f"ERROR: {e}"

for symbol, result in results.items():
    print(f"{symbol}: {result}")
