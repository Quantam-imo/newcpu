import databento as db
import pandas as pd
import os

client = db.Historical(os.getenv("DATABENTO_API_KEY", "YOUR_API_KEY"))

def get_live_data():
    data = client.timeseries.get_range(
        dataset="GLBX.MDP3",
        symbols=["GC"],
        schema="ohlcv-1m",
        start="now-10m"
    )
    df = data.to_df()
    return df
