import json
import time
from pathlib import Path


class ContractResolver:

    def __init__(self, cache_file="data/contract_resolver_cache.json"):
        self.file = Path(cache_file)
        self.cache = {}
        self._load()

    def _load(self):
        try:
            self.cache = json.loads(self.file.read_text(encoding="utf-8"))
            if not isinstance(self.cache, dict):
                self.cache = {}
        except Exception:
            self.cache = {}
            self._save()

    def _save(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.cache, indent=2), encoding="utf-8")

    def _entry(self, canonical_symbol):
        key = str(canonical_symbol)
        if key not in self.cache:
            self.cache[key] = {
                "active_symbol": None,
                "resolved_at": None,
                "last_probe_at": None,
                "last_status": "UNRESOLVED",
                "sample_count": 0,
                "attempts": 0,
                "consecutive_failures": 0,
                "ttl_seconds": 6 * 3600,
                "candidates_tried": [],
            }
        return self.cache[key]

    def get_cached(self, canonical_symbol, max_age_seconds=6 * 3600):
        entry = self._entry(canonical_symbol)
        active_symbol = entry.get("active_symbol")
        resolved_at = entry.get("resolved_at")
        if not active_symbol or not resolved_at:
            return None

        ttl_seconds = int(entry.get("ttl_seconds", max_age_seconds) or max_age_seconds)
        now = int(time.time())
        if (now - int(resolved_at)) > int(ttl_seconds):
            entry["active_symbol"] = None
            entry["last_status"] = "STALE"
            self._save()
            return None

        return str(active_symbol)

    def can_probe(self, canonical_symbol, cooldown_seconds=120):
        entry = self._entry(canonical_symbol)
        last_probe = entry.get("last_probe_at")
        if not last_probe:
            return True

        now = int(time.time())
        return (now - int(last_probe)) >= int(cooldown_seconds)

    def set_active(self, canonical_symbol, active_symbol, sample_count=0, candidates_tried=None, ttl_seconds=6 * 3600):
        entry = self._entry(canonical_symbol)
        now = int(time.time())
        entry["active_symbol"] = str(active_symbol)
        entry["resolved_at"] = now
        entry["last_probe_at"] = now
        entry["last_status"] = "LIVE"
        entry["sample_count"] = int(sample_count or 0)
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["consecutive_failures"] = 0
        entry["ttl_seconds"] = max(300, int(ttl_seconds or 6 * 3600))
        entry["candidates_tried"] = list(candidates_tried or [])[:40]
        self._save()

    def mark_unresolved(self, canonical_symbol, candidates_tried=None):
        entry = self._entry(canonical_symbol)
        now = int(time.time())
        entry["last_probe_at"] = now
        entry["last_status"] = "UNRESOLVED"
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
        entry["candidates_tried"] = list(candidates_tried or [])[:40]
        self._save()

    def mark_miss(self, canonical_symbol, failed_symbol=None):
        entry = self._entry(canonical_symbol)
        entry["last_status"] = "MISS"
        entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
        if failed_symbol and entry.get("active_symbol") == str(failed_symbol):
            entry["active_symbol"] = None
        entry["last_probe_at"] = int(time.time())
        self._save()

    def invalidate_active(self, canonical_symbol, reason="INVALIDATED"):
        entry = self._entry(canonical_symbol)
        entry["active_symbol"] = None
        entry["resolved_at"] = None
        entry["last_status"] = str(reason)
        entry["last_probe_at"] = int(time.time())
        self._save()

    def snapshot(self, canonical_symbol):
        entry = self._entry(canonical_symbol)
        return {
            "symbol": canonical_symbol,
            "active_symbol": entry.get("active_symbol"),
            "resolved_at": entry.get("resolved_at"),
            "last_probe_at": entry.get("last_probe_at"),
            "last_status": entry.get("last_status"),
            "sample_count": int(entry.get("sample_count", 0)),
            "attempts": int(entry.get("attempts", 0)),
            "consecutive_failures": int(entry.get("consecutive_failures", 0)),
            "ttl_seconds": int(entry.get("ttl_seconds", 6 * 3600) or 6 * 3600),
            "candidates_tried": list(entry.get("candidates_tried", [])),
        }

    def summary(self):
        return {symbol: self.snapshot(symbol) for symbol in self.cache.keys()}
