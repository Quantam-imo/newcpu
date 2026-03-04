from __future__ import annotations

from datetime import datetime, timezone


class TimeSalesEngine:
    def __init__(self, orderflow_engine=None):
        self.orderflow_engine = orderflow_engine

    @staticmethod
    def _extract_field(row, *keys):
        for key in keys:
            if isinstance(row, dict) and key in row:
                return row.get(key)
            if hasattr(row, key):
                try:
                    return getattr(row, key)
                except Exception:
                    continue
        return None

    @staticmethod
    def _coerce_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _coerce_int(value, default=0):
        try:
            return int(float(value))
        except Exception:
            return int(default)

    @staticmethod
    def _normalize_timestamp_seconds(value):
        if value is None:
            return int(datetime.now(timezone.utc).timestamp())

        try:
            if isinstance(value, datetime):
                dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
                return int(dt.timestamp())
        except Exception:
            pass

        text = str(value).strip()
        if not text:
            return int(datetime.now(timezone.utc).timestamp())

        try:
            raw = float(text)
            abs_raw = abs(raw)
            if abs_raw > 1e17:
                return int(raw / 1_000_000_000)
            if abs_raw > 1e14:
                return int(raw / 1_000_000)
            if abs_raw > 1e11:
                return int(raw / 1_000)
            return int(raw)
        except Exception:
            pass

        try:
            return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
        except Exception:
            return int(datetime.now(timezone.utc).timestamp())

    @staticmethod
    def _normalize_side(value):
        side = str(value or "").strip().upper()
        if side in {"B", "BUY", "BID", "BUYER"}:
            return "BUY"
        if side in {"S", "A", "SELL", "ASK", "SELLER"}:
            return "SELL"
        return "BUY"

    def from_trades(self, trades, limit=40):
        rows = []
        seq = list(trades or [])
        if not seq:
            return rows

        for row in seq:
            price = self._coerce_float(
                self._extract_field(row, "price", "px", "last", "close"),
                default=0.0,
            )
            size = self._coerce_int(self._extract_field(row, "size", "qty", "volume"), default=0)
            if price <= 0 or size <= 0:
                continue

            side = self._normalize_side(self._extract_field(row, "side", "aggressor_side", "action"))
            ts = self._normalize_timestamp_seconds(
                self._extract_field(row, "ts_event", "timestamp", "time", "ts_recv")
            )
            delta = size if side == "BUY" else -size
            rows.append(
                {
                    "time": int(ts),
                    "price": float(price),
                    "size": int(size),
                    "side": side,
                    "delta": int(delta),
                }
            )

        rows.sort(key=lambda item: int(item.get("time", 0)))
        cumulative = 0
        for item in rows:
            cumulative += int(item.get("delta", 0))
            item["cum_delta"] = int(cumulative)

        return rows[-max(1, int(limit or 40)):]

    def from_candles_fallback(self, candles, limit=24):
        seq = list(candles or [])[-max(1, int(limit or 24)):]
        rows = []
        cumulative = 0
        for row in seq:
            ts = self._coerce_int(row.get("time"), default=0)
            close = self._coerce_float(row.get("close"), default=0.0)
            open_px = self._coerce_float(row.get("open"), default=close)
            volume = max(0, self._coerce_int(row.get("volume"), default=0))
            if close <= 0 or volume <= 0:
                continue

            side = "BUY" if close >= open_px else "SELL"
            delta = volume if side == "BUY" else -volume
            cumulative += delta
            rows.append(
                {
                    "time": int(ts),
                    "price": float(close),
                    "size": int(volume),
                    "side": side,
                    "delta": int(delta),
                    "cum_delta": int(cumulative),
                }
            )
        return rows[-max(1, int(limit or 24)):]

    def build(self, trades, candles, limit=40):
        parsed = self.from_trades(trades=trades, limit=limit)
        if parsed:
            return parsed
        return self.from_candles_fallback(candles=candles, limit=max(12, int(limit or 40)))
