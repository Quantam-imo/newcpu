import databento as db
from datetime import date, timedelta

yesterday = date.today() - timedelta(days=1)
today = date.today()

client = db.Historical("REDACTED")

# Try a known available dataset and symbol for OHLCV-1m schema
dataset = "GLBX.MDP3"
symbol = "ES.FUT"  # S&P 500 E-mini, commonly available

try:
    df = client.timeseries.get_range(
        dataset=dataset,
        schema="ohlcv-1m",
        symbols=symbol,
        start=str(yesterday),
        end=str(today),
        limit=5,
    )
    print(df)
    df.to_csv("yesterday_data.csv")
    print("Data written to yesterday_data.csv")
except Exception as e:
    print(f"Error: {e}")
