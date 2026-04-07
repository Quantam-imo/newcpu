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

    async def stream_ohlcv_1s(self, symbol, callback):
        """Stream live 1-second OHLCV using Databento Live subscription API."""
        client = db.Live(self.api_key)
        try:
            client.subscribe(
                dataset=self.dataset,
                schema="ohlcv-1s",
                stype_in="parent",
                symbols=[symbol],
            )
            for record in client:
                if not hasattr(record, "open"):
                    continue
                candle = {
                    "symbol": symbol,
                    "time": int(record.ts_recv / 1_000_000_000),
                    "open": record.open / 1e9,
                    "high": record.high / 1e9,
                    "low": record.low / 1e9,
                    "close": record.close / 1e9,
                    "volume": record.volume,
                }
                await callback(candle)
        except Exception as live_exc:
            print(f"[DatabentoLiveService] Live stream failed: {live_exc}")
        finally:
            try:
                client.stop()
            except Exception:
                pass

    async def stream_ohlcv_1m(self, symbol, callback):
        """Aggregate 1s candles from the live feed into 1-minute OHLCV bars and emit them."""
        bucket_ts: int | None = None
        agg: dict | None = None

        async def _on_1s_candle(candle: dict):
            nonlocal bucket_ts, agg
            candle_ts = int(candle["time"])
            minute_ts = candle_ts - (candle_ts % 60)

            if bucket_ts is None:
                bucket_ts = minute_ts

            if minute_ts != bucket_ts:
                if agg is not None:
                    await callback(agg)
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
        if agg is not None:
            await callback(agg)

    async def stream_trades(self, symbol, callback):
        """Stream live trades using Databento Live subscription API."""
        client = db.Live(self.api_key)
        try:
            client.subscribe(
                dataset=self.dataset,
                schema="trades",
                stype_in="parent",
                symbols=[symbol],
            )
            for record in client:
                await callback(record)
        except Exception as e:
            print(f"[DatabentoLiveService] Live trades stream failed: {e}")
        finally:
            try:
                client.stop()
            except Exception:
                pass

