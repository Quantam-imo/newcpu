import sys
from astroquant.engine.live_sync.redis_reader import get_latest_tick

if len(sys.argv) < 2:
    print("Usage: python get_live_price.py SYMBOL")
    sys.exit(1)

symbol = sys.argv[1]
data = get_latest_tick(symbol)
if not data:
    print(f"No live data found for {symbol}")
    sys.exit(1)

print(f"Live price for {symbol}: {data['price']} (timestamp: {data['timestamp']})")
