from __future__ import annotations

from datetime import datetime, timezone


class TapeSpeedEngine:
    @staticmethod
    def _field(row, key, default=None):
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _to_ts_seconds(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return float(dt.timestamp())
        try:
            raw = float(value)
            if abs(raw) > 1e17:
                return raw / 1_000_000_000.0
            if abs(raw) > 1e14:
                return raw / 1_000_000.0
            if abs(raw) > 1e11:
                return raw / 1_000.0
            return raw
        except Exception:
            pass
        try:
            return float(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
        except Exception:
            return None

    def compute(self, trades, lookback_seconds=5.0):
        seq = list(trades or [])
        if not seq:
            return {
                "trades_per_second": 0.0,
                "volume_per_second": 0.0,
                "window_seconds": float(lookback_seconds),
                "speed_state": "QUIET",
            }

        now_ts = None
        normalized = []
        for row in seq:
            ts = self._to_ts_seconds(
                self._field(row, "ts_event", None)
                or self._field(row, "timestamp", None)
                or self._field(row, "time", None)
            )
            size = self._to_float(self._field(row, "size", 0.0), 0.0)
            if ts is None or size <= 0:
                continue
            normalized.append((ts, size))
            now_ts = max(now_ts, ts) if now_ts is not None else ts

        if not normalized or now_ts is None:
            return {
                "trades_per_second": 0.0,
                "volume_per_second": 0.0,
                "window_seconds": float(lookback_seconds),
                "speed_state": "QUIET",
            }

        window = max(1.0, float(lookback_seconds or 5.0))
        cutoff = now_ts - window
        recent = [(ts, sz) for ts, sz in normalized if ts >= cutoff]
        trades_count = len(recent)
        volume_sum = sum(sz for _, sz in recent)
        tps = trades_count / window
        vps = volume_sum / window

        if tps >= 20 or vps >= 200:
            state = "FAST"
        elif tps >= 8 or vps >= 80:
            state = "ACTIVE"
        else:
            state = "QUIET"

        return {
            "trades_per_second": round(tps, 3),
            "volume_per_second": round(vps, 3),
            "window_seconds": float(window),
            "speed_state": state,
        }
