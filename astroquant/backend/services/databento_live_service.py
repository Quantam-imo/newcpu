import os
import asyncio
import databento as db

class DatabentoLiveService:
    def __init__(self, api_key=None):
        if api_key is None:
            api_key = os.environ.get("DATABENTO_API_KEY")
        dataset = os.environ.get("DATABENTO_DATASET", "GLBX.MDP3")
        self.api_key = api_key
        self.dataset = dataset
        self.client = db.Live(api_key)

    async def stream_ohlcv_1s(self, symbol, callback):
        # Try to stream live data, but if unavailable, simulate with historical data
        try:
            async with self.client.timeseries(
                dataset=self.dataset,
                schema="ohlcv-1s",
                symbols=[symbol],
            ) as stream:
                async for record in stream:
                    candle = {
                        "symbol": symbol,
                        "time": int(record.ts_event.timestamp()),
                        "open": record.open,
                        "high": record.high,
                        "low": record.low,
                        "close": record.close,
                        "volume": record.volume,
                    }
                    await callback(candle)
        except Exception as live_exc:
            # Fallback: Simulate live candles using historical data (1s bars from a known-good window)
            import databento as db
            from datetime import datetime, timedelta, timezone
            hist_client = db.Historical(self.api_key)
            # Use a fixed historical window (e.g., 2024-03-10 00:00:00 to 00:05:00 UTC)
            hist_start = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
            hist_end = datetime(2024, 3, 10, 0, 5, 0, tzinfo=timezone.utc)
            bars = hist_client.timeseries.get_range(
                dataset="GLBX.MDP3",
                schema="ohlcv-1s",
                symbols=[symbol],
                start=hist_start.isoformat(),
                end=hist_end.isoformat()
            )
            # Loop over historical bars and send as if live (with 1s delay)
            for record in bars:
                candle = {
                    "symbol": symbol,
                    "time": int(record.ts_event.timestamp()),
                    "open": record.open,
                    "high": record.high,
                    "low": record.low,
                    "close": record.close,
                    "volume": record.volume,
                }
                await callback(candle)
                await asyncio.sleep(1)
            # Optionally, loop forever for demo
            # while True:
            #     for record in bars:
            #         ...
