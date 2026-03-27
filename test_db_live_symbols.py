import databento as db

# List of common CME/Globex futures symbols to test
symbols = [
    "ES.FUT",  # S&P 500 E-mini
    "NQ.FUT",  # Nasdaq 100 E-mini
    "YM.FUT",  # Dow Jones E-mini
    "RTY.FUT", # Russell 2000 E-mini
    "GC.FUT",  # Gold futures
    "CL.FUT",  # Crude Oil futures
    "SI.FUT",  # Silver futures
    "ZB.FUT",  # 30-Year Treasury Bond
]

client = db.Live(key="REDACTED")

for symbol in symbols:
    print(f"\nTesting symbol: {symbol}")
    try:
        client.subscribe(
            dataset="GLBX.MDP3",
            schema="mbo",
            stype_in="parent",
            symbols=[symbol],
        )
        for i, record in enumerate(client):
            print(record)
            if i >= 1:
                break
    except Exception as e:
        print(f"Error for {symbol}: {e}")
