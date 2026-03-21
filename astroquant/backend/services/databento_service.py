import databento as db
import os

class DatabentoService:
    def __init__(self, api_key=None):
        if api_key is None:
            api_key = os.environ.get("DATABENTO_API_KEY")
        dataset = os.environ.get("DATABENTO_DATASET", "GLBX.MDP3")
        self.api_key = api_key
        self.dataset = dataset
        self.client = db.Historical(api_key)

    def get_latest_price(self, symbol):
        data = self.client.timeseries.get_range(
            dataset=self.dataset,
            schema="ohlcv-1s",
            symbols=[symbol],
            start="-10s"
        )
        for record in data:
            return {
                "symbol": symbol,
                "price": record.close,
                "high": record.high,
                "low": record.low,
                "volume": record.volume
            }
        return None
