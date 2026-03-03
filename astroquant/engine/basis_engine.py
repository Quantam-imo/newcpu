import time
from collections import deque
from statistics import median


class BasisEngine:

    def __init__(
        self,
        smoothing_window=9,
        history_window=240,
        ewma_alpha=0.25,
        max_jump_bps=120.0,
        max_sigma=6.0,
        min_sigma_abs_bps=30.0,
        stale_seconds=180,
        max_abs_bps_by_symbol=None,
    ):
        self.smoothing_window = max(3, int(smoothing_window))
        self.history_window = max(30, int(history_window))
        self.ewma_alpha = min(1.0, max(0.01, float(ewma_alpha)))
        self.max_jump_bps = max(1.0, float(max_jump_bps))
        self.max_sigma = max(2.0, float(max_sigma))
        self.min_sigma_abs_bps = max(1.0, float(min_sigma_abs_bps))
        self.stale_seconds = max(30, int(stale_seconds))
        self.max_abs_bps_by_symbol = max_abs_bps_by_symbol or {
            "XAUUSD": 180.0,
            "NQ": 80.0,
            "EURUSD": 70.0,
            "BTC": 250.0,
            "US30": 90.0,
        }
        self.default_max_abs_bps = 200.0
        self._state = {}

    def _new_state(self):
        return {
            "raw_basis_history": deque(maxlen=self.history_window),
            "raw_bps_history": deque(maxlen=self.history_window),
            "smooth_basis": None,
            "smooth_bps": None,
            "last_raw_basis": None,
            "last_raw_bps": None,
            "last_update": None,
            "last_guard_reason": None,
            "guard_count": 0,
            "spot_source": None,
            "futures_source": None,
            "status": "UNINITIALIZED",
            "zscore": 0.0,
        }

    def _max_abs_bps(self, symbol):
        return float(self.max_abs_bps_by_symbol.get(symbol, self.default_max_abs_bps))

    def _guard_reason(self, symbol, raw_bps, state):
        if abs(raw_bps) > self._max_abs_bps(symbol):
            return f"Absolute basis too high ({raw_bps:.2f}bps)"

        smooth_bps = state.get("smooth_bps")
        if smooth_bps is not None and abs(raw_bps - smooth_bps) > self.max_jump_bps:
            return f"Basis jump too large ({abs(raw_bps - smooth_bps):.2f}bps)"

        history = list(state.get("raw_bps_history", []))
        if len(history) >= max(12, self.smoothing_window):
            med = float(median(history))
            deviations = [abs(x - med) for x in history]
            mad = float(median(deviations)) if deviations else 0.0
            robust_sigma = 1.4826 * mad
            dynamic_cap = max(self.min_sigma_abs_bps, self.max_sigma * robust_sigma)
            if abs(raw_bps - med) > dynamic_cap:
                return f"Basis outlier detected ({raw_bps:.2f}bps vs med {med:.2f}bps)"

        return None

    def update(self, symbol, spot_price, futures_price, spot_source=None, futures_source=None, event_time=None):
        timestamp = int(event_time or time.time())
        state = self._state.setdefault(symbol, self._new_state())
        state["spot_source"] = spot_source
        state["futures_source"] = futures_source

        try:
            spot = float(spot_price) if spot_price is not None else None
            fut = float(futures_price) if futures_price is not None else None
        except Exception:
            spot = None
            fut = None

        if spot is None or fut is None or spot <= 0 or fut <= 0:
            state["status"] = "UNAVAILABLE"
            state["last_update"] = timestamp
            return self.snapshot(symbol)

        raw_basis = fut - spot
        midpoint = (fut + spot) / 2.0
        raw_bps = (raw_basis / midpoint) * 10000.0 if midpoint > 0 else 0.0

        guard_reason = self._guard_reason(symbol, raw_bps, state)
        if guard_reason:
            state["status"] = "GUARDED"
            state["last_guard_reason"] = guard_reason
            state["guard_count"] = int(state.get("guard_count", 0)) + 1
            state["last_raw_basis"] = raw_basis
            state["last_raw_bps"] = raw_bps
            state["last_update"] = timestamp
            return self.snapshot(symbol)

        state["raw_basis_history"].append(raw_basis)
        state["raw_bps_history"].append(raw_bps)

        basis_window = list(state["raw_basis_history"])[-self.smoothing_window:]
        bps_window = list(state["raw_bps_history"])[-self.smoothing_window:]
        median_basis = float(median(basis_window)) if basis_window else raw_basis
        median_bps = float(median(bps_window)) if bps_window else raw_bps

        prev_basis = state.get("smooth_basis")
        prev_bps = state.get("smooth_bps")
        smooth_basis = median_basis if prev_basis is None else (self.ewma_alpha * median_basis) + ((1.0 - self.ewma_alpha) * prev_basis)
        smooth_bps = median_bps if prev_bps is None else (self.ewma_alpha * median_bps) + ((1.0 - self.ewma_alpha) * prev_bps)

        full_bps = list(state["raw_bps_history"])
        med_full = float(median(full_bps)) if full_bps else 0.0
        deviations = [abs(x - med_full) for x in full_bps]
        mad = float(median(deviations)) if deviations else 0.0
        robust_sigma = max(1e-9, 1.4826 * mad)
        zscore = (raw_bps - med_full) / robust_sigma

        state["status"] = "LIVE"
        state["last_guard_reason"] = None
        state["last_raw_basis"] = raw_basis
        state["last_raw_bps"] = raw_bps
        state["smooth_basis"] = smooth_basis
        state["smooth_bps"] = smooth_bps
        state["zscore"] = zscore
        state["last_update"] = timestamp

        return self.snapshot(symbol)

    def snapshot(self, symbol):
        state = self._state.get(symbol)
        if not state:
            return {
                "symbol": symbol,
                "status": "UNINITIALIZED",
                "safety_block": False,
                "sample_count": 0,
                "last_update": None,
            }

        now = int(time.time())
        last_update = state.get("last_update")
        status = state.get("status", "UNINITIALIZED")
        if last_update and status == "LIVE" and (now - last_update) > self.stale_seconds:
            status = "STALE"

        return {
            "symbol": symbol,
            "status": status,
            "safety_block": status == "GUARDED",
            "raw_basis": state.get("last_raw_basis"),
            "raw_bps": state.get("last_raw_bps"),
            "smooth_basis": state.get("smooth_basis"),
            "smooth_bps": state.get("smooth_bps"),
            "zscore": state.get("zscore", 0.0),
            "sample_count": len(state.get("raw_basis_history", [])),
            "spot_source": state.get("spot_source"),
            "futures_source": state.get("futures_source"),
            "guard_reason": state.get("last_guard_reason"),
            "guard_count": state.get("guard_count", 0),
            "last_update": last_update,
        }
