import databento as db
from datetime import date, timedelta

yesterday = date.today() - timedelta(days=1)
today = date.today()

client = db.Historical("REDACTED")
dataset = "GLBX.MDP3"
symbol = "ES.FUT"

for schema in ["trades", "mbo"]:
    print(f"\nTesting schema: {schema}")
    try:
        df = client.timeseries.get_range(
            dataset=dataset,
            schema=schema,
            symbols=symbol,
            start=str(yesterday),
            end=str(today),
            limit=5,
        )
        print(df)
        df.to_csv(f"yesterday_{schema}.csv")
        print(f"Data written to yesterday_{schema}.csv")
    except Exception as e:
        print(f"Error for schema {schema}: {e}")
