from execution.playwright_engine import PlaywrightEngine

engine = PlaywrightEngine()
engine.start()
engine.wait_for_login()

# Test Buy
engine.execute_market_order("BUY")
