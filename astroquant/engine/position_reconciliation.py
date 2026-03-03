import time


class PositionReconciliationEngine:

    def __init__(self, check_interval_seconds=3, volume_tolerance=1e-6, mismatch_limit=2):
        self.check_interval_seconds = max(1, int(check_interval_seconds))
        self.volume_tolerance = max(0.0, float(volume_tolerance))
        self.mismatch_limit = max(1, int(mismatch_limit))
        self._last_check = 0
        self._consecutive_mismatches = 0
        self._last_snapshot = {
            "status": "UNINITIALIZED",
            "hard_halt": False,
            "reason": None,
            "timestamp": None,
            "internal_count": 0,
            "broker_count": 0,
            "missing_on_broker": [],
            "unexpected_on_broker": [],
            "volume_mismatches": [],
            "consecutive_mismatches": 0,
        }

    def _normalize_internal(self, internal_positions):
        normalized = {}
        for symbol, trade in (internal_positions or {}).items():
            key = str(symbol or "").upper()
            if not key:
                continue
            normalized[key] = {
                "symbol": key,
                "volume": float(trade.get("lot_size") or 0.0),
            }
        return normalized

    def _normalize_broker(self, broker_positions):
        normalized = {}
        for row in (broker_positions or []):
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            normalized[symbol] = {
                "symbol": symbol,
                "volume": float(row.get("volume") or 0.0),
            }
        return normalized

    def snapshot(self):
        return dict(self._last_snapshot)

    def reconcile(self, internal_positions, broker_positions):
        now = int(time.time())
        if (now - int(self._last_check)) < self.check_interval_seconds and self._last_snapshot.get("status") != "UNINITIALIZED":
            return dict(self._last_snapshot)

        self._last_check = now

        if broker_positions is None:
            internal_count = len(internal_positions or {})
            hard_halt = internal_count > 0
            reason = "Broker position feed unavailable"
            self._consecutive_mismatches = self._consecutive_mismatches + 1 if hard_halt else 0
            self._last_snapshot = {
                "status": "BROKER_UNAVAILABLE",
                "hard_halt": hard_halt,
                "reason": reason,
                "timestamp": now,
                "internal_count": internal_count,
                "broker_count": 0,
                "missing_on_broker": list((internal_positions or {}).keys()) if hard_halt else [],
                "unexpected_on_broker": [],
                "volume_mismatches": [],
                "consecutive_mismatches": self._consecutive_mismatches,
            }
            return dict(self._last_snapshot)

        internal = self._normalize_internal(internal_positions)
        broker = self._normalize_broker(broker_positions)

        internal_symbols = set(internal.keys())
        broker_symbols = set(broker.keys())

        missing_on_broker = sorted(list(internal_symbols - broker_symbols))
        unexpected_on_broker = sorted(list(broker_symbols - internal_symbols))

        volume_mismatches = []
        for symbol in sorted(list(internal_symbols & broker_symbols)):
            ivol = float(internal[symbol]["volume"])
            bvol = float(broker[symbol]["volume"])
            if abs(ivol - bvol) > self.volume_tolerance:
                volume_mismatches.append({
                    "symbol": symbol,
                    "internal_volume": ivol,
                    "broker_volume": bvol,
                })

        mismatch = bool(missing_on_broker or unexpected_on_broker or volume_mismatches)
        if mismatch:
            self._consecutive_mismatches += 1
        else:
            self._consecutive_mismatches = 0

        hard_halt = self._consecutive_mismatches >= self.mismatch_limit
        reason = None
        if hard_halt:
            reason = "Position reconciliation mismatch"

        status = "MISMATCH" if mismatch else "OK"
        self._last_snapshot = {
            "status": status,
            "hard_halt": hard_halt,
            "reason": reason,
            "timestamp": now,
            "internal_count": len(internal),
            "broker_count": len(broker),
            "missing_on_broker": missing_on_broker,
            "unexpected_on_broker": unexpected_on_broker,
            "volume_mismatches": volume_mismatches,
            "consecutive_mismatches": self._consecutive_mismatches,
        }
        return dict(self._last_snapshot)
