import databento as db
from datetime import date, timedelta

yesterday = date.today() - timedelta(days=1)
today = date.today()

client = db.Historical("REDACTED")

# Try common futures symbols for OHLCV-1m schema
test_symbols = [
    "ES.FUT",  # S&P 500 E-mini
    "NQ.FUT",  # Nasdaq 100 E-mini
    "YM.FUT",  # Dow Jones E-mini
    "RTY.FUT", # Russell 2000 E-mini
    "GC.FUT",  # Gold futures
    "CL.FUT",  # Crude Oil futures
    "SI.FUT",  # Silver futures
    "ZB.FUT",  # 30-Year Treasury Bond
]

for symbol in test_symbols:
    print(f"\nTesting historical data for: {symbol}")
    try:
        df = client.timeseries.get_range(
            dataset="GLBX.MDP3",
            schema="ohlcv-1m",
            symbols=symbol,
            start=str(yesterday),
            end=str(today),
            limit=5,
        )
        print(df)
    except Exception as e:
        print(f"Error for {symbol}: {e}")
