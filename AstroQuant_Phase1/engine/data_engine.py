import datetime
import os
import re
import databento as db
from backend.config import DATABENTO_API_KEY

class DataEngine:

    RAW_SYMBOL_CANDIDATES = {
        "GC": ["GCZ6", "GCG6", "GCJ6", "GCM6"],
        "NQ": ["NQZ6", "NQH7", "NQM7"],
        "ES": ["ESZ6", "ESH7", "ESM7"],
        "YM": ["YMZ6"],
        "CL": ["CLZ6", "CLF7", "CLG7", "CLH7", "CLM7"],
        "6E": ["6EZ6", "6EH7", "6EM7"],
        "6B": ["6BZ6", "6BH7", "6BM7"],
    }

    def __init__(self):
        self.client = None
        self._resolved_symbols = {}
        self._available_end_cache = None
        self.raw_symbol_candidates = dict(self.RAW_SYMBOL_CANDIDATES)
        try:
            configured_lag = int(os.getenv("DATABENTO_END_LAG_MINUTES", "10"))
        except Exception:
            configured_lag = 10
        self.default_end_lag_minutes = max(1, min(configured_lag, 60))

        env_chains = self._parse_symbol_chain_env(os.getenv("DATABENTO_RAW_SYMBOL_CANDIDATES", ""))
        if env_chains:
            self.raw_symbol_candidates.update(env_chains)

        if not DATABENTO_API_KEY:
            print("DataEngine: DATABENTO_API_KEY missing, live feed disabled.")
            return

        try:
            self.client = db.Historical(DATABENTO_API_KEY)
        except Exception as error:
            print(f"DataEngine: failed to initialize client ({error}).")
            self.client = None

    @staticmethod
    def _parse_symbol_chain_env(value: str):
        chains = {}
        for block in str(value or "").split(";"):
            item = block.strip()
            if not item or ":" not in item:
                continue
            root, raw_list = item.split(":", 1)
            key = str(root or "").strip().upper()
            symbols = [part.strip().upper() for part in raw_list.split(",") if part.strip()]
            if key and symbols:
                chains[key] = symbols
        return chains

    @staticmethod
    def _parse_available_end(message: str):
        if not message:
            return None

        match = re.search(r"available up to '([^']+)'", message)
        if not match:
            return None

        try:
            parsed = datetime.datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            return parsed.astimezone(datetime.timezone.utc)
        except Exception:
            return None

    def _request_ohlcv(self, dataset, raw_symbol, start, end):
        data = self.client.timeseries.get_range(
            dataset=dataset,
            schema="ohlcv-1m",
            symbols=[raw_symbol],
            start=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            stype_in="raw_symbol",
        )
        df = data.to_df()
        if df.empty:
            return []
        return df.reset_index().to_dict(orient="records")

    def _symbol_candidates(self, symbol: str):
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return []

        cached = self._resolved_symbols.get(normalized)

        if normalized.endswith(".FUT"):
            root = normalized.split(".", 1)[0]
        elif normalized in self.raw_symbol_candidates:
            root = normalized
        else:
            root = None

        candidates = [normalized]
        if root in self.raw_symbol_candidates:
            candidates.extend(self.raw_symbol_candidates[root])
        if cached:
            candidates.insert(0, cached)

        seen = set()
        ordered = []
        for item in candidates:
            key = str(item or "").strip().upper()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(key)

        return ordered

    def get_ohlcv(self, symbol: str, minutes=120):

        if self.client is None:
            return []

        dataset = "GLBX.MDP3"
        symbol_candidates = self._symbol_candidates(symbol)
        if not symbol_candidates:
            return []

        now = datetime.datetime.now(datetime.timezone.utc)

        fallback_lags = []
        for lag in [
            self.default_end_lag_minutes,
            self.default_end_lag_minutes + 3,
            self.default_end_lag_minutes + 8,
            self.default_end_lag_minutes + 15,
        ]:
            clipped = max(1, min(int(lag), 90))
            if clipped not in fallback_lags:
                fallback_lags.append(clipped)

        for lag in fallback_lags:
            end = now - datetime.timedelta(minutes=lag)
            if self._available_end_cache:
                end = min(end, self._available_end_cache - datetime.timedelta(minutes=1))
            start = end - datetime.timedelta(minutes=minutes)
            for raw_symbol in symbol_candidates:
                try:
                    bars = self._request_ohlcv(dataset, raw_symbol, start, end)
                    if not bars:
                        continue
                    self._resolved_symbols[str(symbol or "").strip().upper()] = raw_symbol
                    return bars
                except Exception as e:
                    message = str(e)
                    if "symbology_invalid_request" in message:
                        continue

                    if "data_end_after_available_end" in message:
                        available_end = self._parse_available_end(message)
                        if available_end:
                            self._available_end_cache = available_end
                            safe_end = available_end - datetime.timedelta(minutes=1)
                            safe_start = safe_end - datetime.timedelta(minutes=minutes)
                            try:
                                bars = self._request_ohlcv(dataset, raw_symbol, safe_start, safe_end)
                                if bars:
                                    self._resolved_symbols[str(symbol or "").strip().upper()] = raw_symbol
                                    return bars
                            except Exception:
                                pass
                            continue

                    print(f"Data error (lag={lag}m, symbol={raw_symbol}):", e)

        return []
