from statistics import median

from backend.services.market_data_service import normalize_bars


class SpreadMapperService:

    def __init__(self):
        self._basis_cache = {}

    @staticmethod
    def _safe_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    def estimate_basis(self, data_engine, source_symbol, execution_symbol, lookback_minutes=180):
        cache_key = f"{source_symbol}->{execution_symbol}:{lookback_minutes}"
        if cache_key in self._basis_cache:
            return self._basis_cache[cache_key]

        source_raw = data_engine.get_ohlcv(source_symbol, minutes=lookback_minutes)
        execution_raw = data_engine.get_ohlcv(execution_symbol, minutes=lookback_minutes)

        source_bars = normalize_bars(source_raw) if source_raw else []
        execution_bars = normalize_bars(execution_raw) if execution_raw else []

        if not source_bars or not execution_bars:
            basis = 0.0
            self._basis_cache[cache_key] = basis
            return basis

        aligned_count = min(len(source_bars), len(execution_bars), 50)
        if aligned_count <= 0:
            basis = 0.0
            self._basis_cache[cache_key] = basis
            return basis

        diffs = []
        for index in range(1, aligned_count + 1):
            source_close = self._safe_float(source_bars[-index].get("close", 0), 0)
            execution_close = self._safe_float(execution_bars[-index].get("close", 0), 0)
            diffs.append(source_close - execution_close)

        basis = float(median(diffs)) if diffs else 0.0
        self._basis_cache[cache_key] = basis
        return basis

    def apply_basis(self, side, entry, stop, basis):
        entry_val = self._safe_float(entry, 0)
        stop_val = self._safe_float(stop, entry_val)
        basis_val = self._safe_float(basis, 0)

        adjusted_entry = entry_val - basis_val
        adjusted_stop = stop_val - basis_val

        return {
            "side": str(side or "").upper(),
            "entry": adjusted_entry,
            "stop": adjusted_stop,
            "basis": basis_val,
        }
