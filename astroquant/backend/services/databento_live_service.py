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
            # Fallback: Simulate live candles using recent historical data (rolling 5-min window)
            from astroquant.backend.services.databento_utility import fetch_databento_data
            from datetime import datetime, timedelta, timezone
            hist_end = datetime.now(timezone.utc) - timedelta(minutes=35)  # 30-min safety lag
            hist_start = hist_end - timedelta(minutes=5)
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
    async def stream_ohlcv_1m(self, symbol, callback):
        """Aggregate 1s candles from the live feed into 1-minute OHLCV bars and emit them."""
        bucket_ts: int | None = None
        agg: dict | None = None

        async def _on_1s_candle(candle: dict):
            nonlocal bucket_ts, agg
            # Determine which 1-minute bucket this 1s candle belongs to
            candle_ts = int(candle["time"])
            minute_ts = candle_ts - (candle_ts % 60)  # floor to minute boundary

            if bucket_ts is None:
                bucket_ts = minute_ts

            if minute_ts != bucket_ts:
                # Emit the completed 1m candle
                if agg is not None:
                    await callback(agg)
                # Start new bucket
                bucket_ts = minute_ts
                agg = None

            if agg is None:
                agg = {
                    "symbol": candle["symbol"],
                    "time": minute_ts,
                    "open": candle["open"],
                    "high": candle["high"],
                    "low": candle["low"],
                    "close": candle["close"],
                    "volume": candle["volume"],
                }
            else:
                agg["high"] = max(agg["high"], candle["high"])
                agg["low"] = min(agg["low"], candle["low"])
                agg["close"] = candle["close"]
                agg["volume"] = agg["volume"] + candle["volume"]

        await self.stream_ohlcv_1s(symbol, _on_1s_candle)
        # Emit any partial last bucket on stream end
        if agg is not None:
            await callback(agg)
    async def stream_ohlcv_1m(self, symbol, callback):
        """Aggregate 1s candles from the live feed into 1-minute OHLCV bars and emit them."""
        bucket_ts: int | None = None
        agg: dict | None = None

        async def _on_1s_candle(candle: dict):
            nonlocal bucket_ts, agg
            # Determine which 1-minute bucket this 1s candle belongs to
            candle_ts = int(candle["time"])
            minute_ts = candle_ts - (candle_ts % 60)  # floor to minute boundary

            if bucket_ts is None:
                bucket_ts = minute_ts

            if minute_ts != bucket_ts:
                # Emit the completed 1m candle
                if agg is not None:
                    await callback(agg)
                # Start new bucket
                bucket_ts = minute_ts
                agg = None

            if agg is None:
                agg = {
                    "symbol": candle["symbol"],
                    "time": minute_ts,
                    "open": candle["open"],
                    "high": candle["high"],
                    "low": candle["low"],
                    "close": candle["close"],
                    "volume": candle["volume"],
                }
            else:
                agg["high"] = max(agg["high"], candle["high"])
                agg["low"] = min(agg["low"], candle["low"])
                agg["close"] = candle["close"]
                agg["volume"] = agg["volume"] + candle["volume"]

        await self.stream_ohlcv_1s(symbol, _on_1s_candle)
        # Emit any partial last bucket on stream end
        if agg is not None:
            await callback(agg)

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
