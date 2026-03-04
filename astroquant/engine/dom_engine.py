from __future__ import annotations


class DomEngine:
    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _to_int(value, default=0):
        try:
            return int(float(value))
        except Exception:
            return int(default)

    def _infer_mid(self, time_sales_rows, candles):
        if time_sales_rows:
            price = self._to_float(time_sales_rows[-1].get("price"), 0.0)
            if price > 0:
                return price
        if candles:
            price = self._to_float(candles[-1].get("close"), 0.0)
            if price > 0:
                return price
        return 0.0

    def _infer_tick(self, time_sales_rows, candles, mid):
        diffs = []
        prev = None
        for row in list(time_sales_rows or []):
            px = self._to_float(row.get("price"), 0.0)
            if px <= 0:
                continue
            if prev is not None:
                d = abs(px - prev)
                if d > 0:
                    diffs.append(d)
            prev = px

        if diffs:
            diffs.sort()
            return max(0.01, diffs[len(diffs) // 2])

        highs = [self._to_float(c.get("high"), 0.0) for c in list(candles or []) if self._to_float(c.get("high"), 0.0) > 0]
        lows = [self._to_float(c.get("low"), 0.0) for c in list(candles or []) if self._to_float(c.get("low"), 0.0) > 0]
        if highs and lows:
            span = max(highs) - min(lows)
            if span > 0:
                return max(0.01, span / 40.0)

        return max(0.01, (mid * 0.0002) if mid > 0 else 0.1)

    def build(self, time_sales_rows, candles, depth=12):
        depth = max(6, min(40, int(depth or 12)))
        tape = list(time_sales_rows or [])[-240:]
        bars = list(candles or [])[-120:]

        mid = self._infer_mid(tape, bars)
        if mid <= 0:
            return {
                "levels": [],
                "summary": {
                    "spread": 0.0,
                    "imbalance": 0.0,
                    "imbalance_side": "NEUTRAL",
                    "best_bid": None,
                    "best_ask": None,
                    "bid_wall": None,
                    "ask_wall": None,
                },
            }

        tick = self._infer_tick(tape, bars, mid)
        now_ts = self._to_int((tape[-1] if tape else bars[-1]).get("time"), 0) if (tape or bars) else 0

        observed_bid = {}
        observed_ask = {}
        for row in tape:
            side = str(row.get("side", "")).upper()
            px = self._to_float(row.get("price"), 0.0)
            size = max(0.0, self._to_float(row.get("size"), 0.0))
            if px <= 0 or size <= 0:
                continue
            level_px = round(round(px / tick) * tick, 6)
            if side == "BUY":
                observed_bid[level_px] = observed_bid.get(level_px, 0.0) + size
            elif side == "SELL":
                observed_ask[level_px] = observed_ask.get(level_px, 0.0) + size

        recent_volumes = [max(0.0, self._to_float(c.get("volume"), 0.0)) for c in bars[-20:]]
        baseline = max(1.0, (sum(recent_volumes) / max(1, len(recent_volumes))) if recent_volumes else 10.0)

        levels = []
        for step in range(depth, 0, -1):
            price = round(mid + (step * tick), 6)
            prox = max(0.25, 1.0 - ((step - 1) / max(1, depth + 1)))
            base = baseline * (0.45 + prox)
            ask_size = observed_ask.get(price, 0.0) + (base * (1.0 + (0.06 * step)))
            levels.append({
                "time": int(now_ts),
                "price": float(price),
                "bid_size": 0,
                "ask_size": int(round(max(0.0, ask_size))),
            })

        best_ask_price = round(mid + tick, 6)
        best_bid_price = round(mid - tick, 6)
        best_ask_size = int(round(max(1.0, observed_ask.get(best_ask_price, 0.0) + baseline * 1.3)))
        best_bid_size = int(round(max(1.0, observed_bid.get(best_bid_price, 0.0) + baseline * 1.3)))

        levels.append(
            {
                "time": int(now_ts),
                "price": float(mid),
                "bid_size": int(best_bid_size),
                "ask_size": int(best_ask_size),
            }
        )

        for step in range(1, depth + 1):
            price = round(mid - (step * tick), 6)
            prox = max(0.25, 1.0 - ((step - 1) / max(1, depth + 1)))
            base = baseline * (0.45 + prox)
            bid_size = observed_bid.get(price, 0.0) + (base * (1.0 + (0.06 * step)))
            levels.append({
                "time": int(now_ts),
                "price": float(price),
                "bid_size": int(round(max(0.0, bid_size))),
                "ask_size": 0,
            })

        bid_total = sum(max(0, self._to_int(row.get("bid_size"), 0)) for row in levels)
        ask_total = sum(max(0, self._to_int(row.get("ask_size"), 0)) for row in levels)
        total = max(1.0, float(bid_total + ask_total))
        imbalance = ((bid_total - ask_total) / total) * 100.0

        max_bid_row = max(levels, key=lambda row: self._to_int(row.get("bid_size"), 0)) if levels else None
        max_ask_row = max(levels, key=lambda row: self._to_int(row.get("ask_size"), 0)) if levels else None

        summary = {
            "spread": float(max(0.0, best_ask_price - best_bid_price)),
            "imbalance": float(imbalance),
            "imbalance_side": "BUY" if imbalance > 0.5 else ("SELL" if imbalance < -0.5 else "NEUTRAL"),
            "best_bid": {"price": float(best_bid_price), "size": int(best_bid_size)},
            "best_ask": {"price": float(best_ask_price), "size": int(best_ask_size)},
            "bid_wall": {
                "price": float(max_bid_row.get("price")) if max_bid_row else None,
                "size": int(self._to_int(max_bid_row.get("bid_size"), 0)) if max_bid_row else 0,
            },
            "ask_wall": {
                "price": float(max_ask_row.get("price")) if max_ask_row else None,
                "size": int(self._to_int(max_ask_row.get("ask_size"), 0)) if max_ask_row else 0,
            },
        }

        return {
            "levels": levels,
            "summary": summary,
        }
