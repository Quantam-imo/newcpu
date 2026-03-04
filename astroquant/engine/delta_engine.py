from __future__ import annotations


class DeltaEngine:
    @staticmethod
    def _to_int(value, default=0):
        try:
            return int(float(value))
        except Exception:
            return int(default)

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    def _bucket_time(self, epoch_sec: int, timeframe_minutes: int) -> int:
        tf = max(1, int(timeframe_minutes or 1)) * 60
        t = self._to_int(epoch_sec, 0)
        if t <= 0:
            return 0
        return int((t // tf) * tf)

    def build_candle_delta(self, time_sales_rows, candles, timeframe_minutes: int = 1, limit: int = 120):
        rows = list(time_sales_rows or [])
        out = []

        if rows:
            buckets = {}
            for row in rows:
                ts = self._to_int(row.get("time"), 0)
                if ts <= 0:
                    continue
                bkt = self._bucket_time(ts, timeframe_minutes)
                side = str(row.get("side", "")).upper()
                size = max(0, self._to_float(row.get("size"), 0.0))
                delta = self._to_float(row.get("delta"), size if side == "BUY" else -size)

                slot = buckets.setdefault(
                    bkt,
                    {
                        "time": int(bkt),
                        "buy_volume": 0.0,
                        "sell_volume": 0.0,
                        "delta": 0.0,
                    },
                )
                if delta >= 0:
                    slot["buy_volume"] += max(size, delta)
                else:
                    slot["sell_volume"] += max(size, abs(delta))
                slot["delta"] += delta

            for key in sorted(buckets.keys()):
                slot = buckets[key]
                out.append(
                    {
                        "time": int(slot["time"]),
                        "buy_volume": float(slot["buy_volume"]),
                        "sell_volume": float(slot["sell_volume"]),
                        "delta": float(slot["delta"]),
                    }
                )

        if not out:
            seq = list(candles or [])[-max(1, int(limit or 120)):]
            for row in seq:
                ts = self._to_int(row.get("time"), 0)
                close = self._to_float(row.get("close"), 0.0)
                open_px = self._to_float(row.get("open"), close)
                volume = max(0.0, self._to_float(row.get("volume"), 0.0))
                if ts <= 0 or volume <= 0:
                    continue
                buy = volume * (0.65 if close >= open_px else 0.35)
                sell = max(0.0, volume - buy)
                out.append(
                    {
                        "time": int(ts),
                        "buy_volume": float(buy),
                        "sell_volume": float(sell),
                        "delta": float(buy - sell),
                    }
                )

        out = out[-max(1, int(limit or 120)):]
        cumulative = 0.0
        for row in out:
            cumulative += self._to_float(row.get("delta"), 0.0)
            row["cum_delta"] = float(cumulative)
        return out

    def summarize(self, time_sales_rows, candle_delta_rows):
        buy = 0.0
        sell = 0.0

        for row in list(time_sales_rows or []):
            side = str(row.get("side", "")).upper()
            size = max(0.0, self._to_float(row.get("size"), 0.0))
            if side == "BUY":
                buy += size
            elif side == "SELL":
                sell += size

        if buy == 0 and sell == 0:
            for row in list(candle_delta_rows or []):
                buy += max(0.0, self._to_float(row.get("buy_volume"), 0.0))
                sell += max(0.0, self._to_float(row.get("sell_volume"), 0.0))

        total = max(1e-9, buy + sell)
        delta = buy - sell
        buy_aggr = (buy / total) * 100.0
        sell_aggr = (sell / total) * 100.0
        cum_delta = self._to_float((candle_delta_rows or [{}])[-1].get("cum_delta"), 0.0) if candle_delta_rows else 0.0

        return {
            "buy_volume": float(buy),
            "sell_volume": float(sell),
            "delta": float(delta),
            "delta_percent": float((delta / total) * 100.0),
            "buy_aggression": float(buy_aggr),
            "sell_aggression": float(sell_aggr),
            "cumulative_delta": float(cum_delta),
            "imbalance": "BUY" if delta >= 0 else "SELL",
        }

    def build(self, time_sales_rows, candles, timeframe_minutes: int = 1, limit: int = 120):
        candle_rows = self.build_candle_delta(
            time_sales_rows=time_sales_rows,
            candles=candles,
            timeframe_minutes=timeframe_minutes,
            limit=limit,
        )
        summary = self.summarize(time_sales_rows=time_sales_rows, candle_delta_rows=candle_rows)
        return {
            "summary": summary,
            "candles": candle_rows,
        }
