import requests
from datetime import datetime, timezone, timedelta

API_KEY = "REDACTED"
BASE_URL = "https://hist.databento.com/v0"

def get_symbols(dataset="GLBX.MDP3", limit=10):
    url = f"{BASE_URL}/reference/instruments"
    params = {"dataset": dataset, "limit": limit}
    headers = {"X-API-Key": API_KEY}
    resp = requests.get(url, params=params, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    print(f"Sample symbols for {dataset}:")
    for item in data.get("data", []):
        print(item)
    return [item["symbol"] for item in data.get("data", [])]

def test_symbol(symbol, dataset="GLBX.MDP3"):
    url = f"{BASE_URL}/timeseries.get_range"
    now = datetime.now(timezone.utc)
    end = now - timedelta(minutes=15)
    start = end - timedelta(minutes=30)
    params = {
        "dataset": dataset,
        "schema": "ohlcv-1m",
        "symbols": symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": 10,
    }
    headers = {"X-API-Key": API_KEY}
    resp = requests.get(url, params=params, headers=headers)
    try:
        resp.raise_for_status()
        print(f"{symbol}: OK")
    except Exception as e:
        print(f"{symbol}: ERROR: {e}\n{resp.text}")

if __name__ == "__main__":
    symbols = get_symbols(limit=5)
    for symbol in symbols:
        test_symbol(symbol)
