from astroquant.execution.playwright_engine import PlaywrightExecutionEngine
import time

SYMBOLS = ["XAUUSD", "GC-F", "NQ", "EURUSD", "BTC", "US30"]

import asyncio

async def main():
    engine = PlaywrightExecutionEngine(headless=False)
    await engine.connect_to_broker()
    price_memory = {}
    while True:
        for symbol in SYMBOLS:
            try:
                price = engine.get_broker_price(symbol)
                if price is not None:
                    price_memory[symbol] = price
                    print(f"{symbol}: {price}")
                else:
                    print(f"{symbol}: price not available")
            except Exception as exc:
                print(f"Error fetching price for {symbol}: {exc}")
        # Optionally, save price_memory to disk or database here
        await asyncio.sleep(5)  # Poll every 5 seconds

if __name__ == "__main__":
    asyncio.run(main())
