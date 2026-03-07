from __future__ import annotations


class OrderflowImbalanceEngine:
    @staticmethod
    def _field(row, key, default=None):
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    @staticmethod
    def _normalize_side(raw):
        side = str(raw or "").upper().strip()
        if side in {"B", "BUY", "BID", "BUYER"}:
            return "BUY"
        if side in {"S", "SELL", "ASK", "A", "SELLER"}:
            return "SELL"
        return "UNKNOWN"

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    def compute(self, trades):
        buy_volume = 0.0
        sell_volume = 0.0
        buy_count = 0
        sell_count = 0

        for trade in list(trades or []):
            side = self._normalize_side(self._field(trade, "side", ""))
            size = self._to_float(self._field(trade, "size", 0.0), 0.0)
            if size <= 0.0:
                continue
            if side == "BUY":
                buy_volume += size
                buy_count += 1
            elif side == "SELL":
                sell_volume += size
                sell_count += 1

        total = buy_volume + sell_volume
        delta = buy_volume - sell_volume
        imbalance_ratio = (delta / total) if total > 0 else 0.0
        side = "BUY" if delta > 0 else ("SELL" if delta < 0 else "NEUTRAL")

        return {
            "buy_volume": round(buy_volume, 2),
            "sell_volume": round(sell_volume, 2),
            "delta": round(delta, 2),
            "imbalance_ratio": round(imbalance_ratio, 4),
            "imbalance_side": side,
            "buy_trades": int(buy_count),
            "sell_trades": int(sell_count),
        }
