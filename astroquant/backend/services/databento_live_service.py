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
            from astroquant.backend.services.databento_utility import fetch_databento_data
            from datetime import datetime, timedelta, timezone
            hist_start = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
            hist_end = datetime(2024, 3, 10, 0, 5, 0, tzinfo=timezone.utc)
            try:
                df = fetch_databento_data([symbol], "ohlcv-1s", hist_start.isoformat(), hist_end.isoformat(), dataset=self.dataset, api_key=self.api_key)
                for _, record in df.iterrows():
                    candle = {
                        "symbol": symbol,
                        "time": int(record["ts_event"].timestamp()) if hasattr(record["ts_event"], "timestamp") else int(record["ts_event"]),
                        "open": record["open"],
                        "high": record["high"],
                        "low": record["low"],
                        "close": record["close"],
                        "volume": record["volume"],
                    }
                    await callback(candle)
                    await asyncio.sleep(1)
            except Exception as e:
                print(f"[DatabentoLiveService] Fallback failed: {e}")

    async def stream_trades(self, symbol, callback):
        # Stream live trades using Databento Live API
        try:
            self.client.subscribe(
                dataset=self.dataset,
                schema="trades",
                stype_in="parent",
                symbols=[symbol],
            )
            async for record in self.client:
                await callback(record)
        except Exception as e:
            print(f"[DatabentoLiveService] Live trades stream failed: {e}")
            # Optionally, loop forever for demo
            # while True:
            #     for record in bars:
            #         ...
