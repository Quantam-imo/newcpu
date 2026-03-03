import time


class BrokerEquityVerificationEngine:

    def __init__(self, max_divergence=75.0, mismatch_limit=2, check_interval_seconds=5):
        self.max_divergence = max(1.0, float(max_divergence))
        self.mismatch_limit = max(1, int(mismatch_limit))
        self.check_interval_seconds = max(1, int(check_interval_seconds))
        self._last_check = 0
        self._consecutive_mismatches = 0
        self._last_snapshot = {
            "status": "UNINITIALIZED",
            "hard_halt": False,
            "reason": None,
            "timestamp": None,
            "internal_equity": None,
            "broker_equity": None,
            "divergence": None,
            "max_divergence": self.max_divergence,
            "consecutive_mismatches": 0,
            "mismatch_limit": self.mismatch_limit,
        }

    def snapshot(self):
        return dict(self._last_snapshot)

    def verify(self, internal_equity, broker_equity):
        now = int(time.time())
        if (now - int(self._last_check)) < self.check_interval_seconds and self._last_snapshot.get("status") != "UNINITIALIZED":
            return dict(self._last_snapshot)

        self._last_check = now

        if broker_equity is None:
            self._last_snapshot = {
                "status": "BROKER_UNAVAILABLE",
                "hard_halt": False,
                "reason": "Broker equity unavailable",
                "timestamp": now,
                "internal_equity": float(internal_equity) if internal_equity is not None else None,
                "broker_equity": None,
                "divergence": None,
                "max_divergence": self.max_divergence,
                "consecutive_mismatches": self._consecutive_mismatches,
                "mismatch_limit": self.mismatch_limit,
            }
            return dict(self._last_snapshot)

        internal = float(internal_equity)
        broker = float(broker_equity)
        divergence = abs(internal - broker)

        mismatch = divergence > self.max_divergence
        if mismatch:
            self._consecutive_mismatches += 1
        else:
            self._consecutive_mismatches = 0

        hard_halt = self._consecutive_mismatches >= self.mismatch_limit
        reason = "Equity mismatch" if hard_halt else None
        status = "MISMATCH" if mismatch else "OK"

        self._last_snapshot = {
            "status": status,
            "hard_halt": hard_halt,
            "reason": reason,
            "timestamp": now,
            "internal_equity": internal,
            "broker_equity": broker,
            "divergence": divergence,
            "max_divergence": self.max_divergence,
            "consecutive_mismatches": self._consecutive_mismatches,
            "mismatch_limit": self.mismatch_limit,
        }
        return dict(self._last_snapshot)
