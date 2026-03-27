import databento as db
import pandas as pd
import os


def _client() -> db.Historical:
    api_key = str(os.getenv("DATABENTO_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("DATABENTO_API_KEY is not configured")
    return db.Historical(api_key)

def get_live_data():
    data = _client().timeseries.get_range(
        dataset="GLBX.MDP3",
        symbols=["GC"],
        schema="ohlcv-1m",
        start="now-10m"
    )
    df = data.to_df()
    return df
