import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.services.market_data_service import normalize_bars


class RolloverManager:

    DEFAULT_CONTRACTS = {
        "GC": ["GC.FUT", "GCZ6", "GCG6", "GCJ6"],
        "NQ": ["NQ.FUT", "NQZ6", "NQH7", "NQM7"],
        "YM": ["YM.FUT", "YMZ6", "YMH7", "YMM7"],
        "CL": ["CL.FUT", "CLZ6", "CLF7", "CLG7"],
        "6E": ["6E.FUT", "6EZ6", "6EH7", "6EM7"],
        "6B": ["6B.FUT", "6BZ6", "6BH7", "6BM7"],
    }

    def __init__(self, data_engine, confirm_days=2):
        self.data_engine = data_engine
        self.confirm_days = max(1, int(confirm_days))
        self.storage_path = Path(__file__).resolve().parents[2] / "data" / "rollover_events.json"
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache = {}
        self._continuous_cache = {}
        self.contract_chains = dict(self.DEFAULT_CONTRACTS)

        env_chains = self._parse_contract_chain_env(os.getenv("ROLLOVER_CONTRACT_CHAINS", ""))
        if env_chains:
            self.contract_chains.update(env_chains)

    @staticmethod
    def _parse_contract_chain_env(value: str):
        chains = {}
        for block in str(value or "").split(";"):
            item = block.strip()
            if not item or ":" not in item:
                continue
            root, contracts = item.split(":", 1)
            key = str(root or "").strip().upper()
            items = [part.strip().upper() for part in contracts.split(",") if part.strip()]
            if key and items:
                chains[key] = items
        return chains

    @staticmethod
    def _utc_now():
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_root(symbol):
        normalized = str(symbol or "").strip().upper()
        if normalized.startswith("GC") or normalized == "XAUUSD":
            return "GC"
        if normalized.startswith("NQ") or normalized == "NAS100":
            return "NQ"
        if normalized.startswith("YM") or normalized == "US30":
            return "YM"
        if normalized.startswith("CL") or normalized == "USOIL":
            return "CL"
        if normalized.startswith("6E") or normalized == "EURUSD":
            return "6E"
        if normalized.startswith("6B") or normalized == "GBPUSD":
            return "6B"

        if "." in normalized:
            return normalized.split(".")[0]

        return normalized.split(".")[0] if normalized else "GC"

    def _load_events(self):
        if not self.storage_path.exists():
            return []

        try:
            return json.loads(self.storage_path.read_text())
        except Exception:
            return []

    def _save_events(self, events):
        self.storage_path.write_text(json.dumps(events, indent=2))

    @staticmethod
    def _daily_stats(bars):
        grouped = {}
        for bar in bars:
            ts = str(bar.get("time", ""))
            if not ts:
                continue
            day = ts[:10]
            state = grouped.setdefault(day, {"volume": 0.0, "close": None, "time": ts})
            state["volume"] += float(bar.get("volume", 0) or 0)
            state["close"] = float(bar.get("close", state["close"] or 0) or 0)
            state["time"] = ts

        return grouped

    def _get_contract_bars(self, contract, minutes):
        raw = self.data_engine.get_ohlcv(contract, minutes=minutes)
        return normalize_bars(raw) if raw else []

    def detect_rollover(self, symbol):
        root = self._normalize_root(symbol)
        cache_key = f"detect:{root}"
        now = self._utc_now()

        cached = self._cache.get(cache_key)
        if cached and (now - cached["time"]).total_seconds() < 900:
            return cached["payload"]

        contracts = self.contract_chains.get(root, [f"{root}.FUT"])
        front_contract = contracts[0]
        next_contract = contracts[1] if len(contracts) > 1 else contracts[0]

        front_bars = self._get_contract_bars(front_contract, minutes=5 * 24 * 60)
        next_bars = self._get_contract_bars(next_contract, minutes=5 * 24 * 60)

        front_daily = self._daily_stats(front_bars)
        next_daily = self._daily_stats(next_bars)

        common_days = sorted(set(front_daily.keys()) & set(next_daily.keys()))
        recent_days = common_days[-self.confirm_days:]
        latest_compare_day = common_days[-1] if common_days else None

        consecutive = 0
        rollover_date = None
        adjustment_value = 0.0

        for day in recent_days:
            if next_daily[day]["volume"] > front_daily[day]["volume"]:
                consecutive += 1
                rollover_date = day
                adjustment_value = float(next_daily[day]["close"] - front_daily[day]["close"])

        rollover_detected = consecutive >= self.confirm_days
        active_contract = next_contract if rollover_detected else front_contract

        latest_front_volume = 0.0
        latest_next_volume = 0.0
        if latest_compare_day:
            latest_front_volume = float(front_daily.get(latest_compare_day, {}).get("volume", 0) or 0)
            latest_next_volume = float(next_daily.get(latest_compare_day, {}).get("volume", 0) or 0)

        volume_ratio = 0.0
        if latest_front_volume > 0:
            volume_ratio = latest_next_volume / latest_front_volume

        events = self._load_events()
        if rollover_detected and rollover_date:
            exists = any(
                item.get("symbol") == root
                and item.get("old_contract") == front_contract
                and item.get("new_contract") == next_contract
                and item.get("rollover_date") == rollover_date
                for item in events
            )
            if not exists:
                events.append(
                    {
                        "symbol": root,
                        "old_contract": front_contract,
                        "new_contract": next_contract,
                        "rollover_date": rollover_date,
                        "adjustment_value": adjustment_value,
                        "recorded_at": now.isoformat(),
                    }
                )
                self._save_events(events)

        payload = {
            "symbol": root,
            "front_contract": front_contract,
            "next_contract": next_contract,
            "active_contract": active_contract,
            "rollover_detected": rollover_detected,
            "rollover_confirmed_days": consecutive,
            "rollover_date": rollover_date,
            "adjustment_value": adjustment_value,
            "latest_compare_day": latest_compare_day,
            "latest_front_volume": latest_front_volume,
            "latest_next_volume": latest_next_volume,
            "volume_ratio": volume_ratio,
            "events": events,
        }

        self._cache[cache_key] = {"time": now, "payload": payload}
        return payload

    def get_continuous_ohlcv(self, symbol, minutes=240):
        root = self._normalize_root(symbol)
        cache_key = f"continuous:{root}:{minutes}"
        now = self._utc_now()

        cached = self._continuous_cache.get(cache_key)
        if cached and (now - cached["time"]).total_seconds() < 20:
            return cached["payload"]

        detection = self.detect_rollover(root)
        front_contract = detection["front_contract"]
        next_contract = detection["next_contract"]

        front_bars = self._get_contract_bars(front_contract, minutes=minutes)
        if not front_bars:
            payload = {"bars": [], "meta": detection}
            self._continuous_cache[cache_key] = {"time": now, "payload": payload}
            return payload

        if not detection["rollover_detected"] or front_contract == next_contract:
            payload = {
                "bars": front_bars,
                "meta": {
                    **detection,
                    "continuous": True,
                    "rollover_week": False,
                },
            }
            self._continuous_cache[cache_key] = {"time": now, "payload": payload}
            return payload

        next_bars = self._get_contract_bars(next_contract, minutes=minutes)
        if not next_bars:
            payload = {
                "bars": front_bars,
                "meta": {
                    **detection,
                    "continuous": True,
                    "rollover_week": False,
                },
            }
            self._continuous_cache[cache_key] = {"time": now, "payload": payload}
            return payload

        adjustment = float(detection.get("adjustment_value", 0) or 0)
        rollover_day = detection.get("rollover_date")

        combined = []
        for bar in front_bars:
            ts = str(bar.get("time", ""))
            if rollover_day and ts[:10] >= rollover_day:
                continue
            combined.append(bar)

        for bar in next_bars:
            adjusted_bar = dict(bar)
            adjusted_bar["open"] = float(adjusted_bar.get("open", 0) or 0) - adjustment
            adjusted_bar["high"] = float(adjusted_bar.get("high", 0) or 0) - adjustment
            adjusted_bar["low"] = float(adjusted_bar.get("low", 0) or 0) - adjustment
            adjusted_bar["close"] = float(adjusted_bar.get("close", 0) or 0) - adjustment
            combined.append(adjusted_bar)

        combined.sort(key=lambda item: item.get("time", ""))

        rollover_week = False
        if rollover_day:
            try:
                rollover_dt = datetime.fromisoformat(f"{rollover_day}T00:00:00+00:00")
                rollover_week = abs((now - rollover_dt).days) <= 8
            except Exception:
                rollover_week = False

        payload = {
            "bars": combined,
            "meta": {
                **detection,
                "continuous": True,
                "rollover_week": rollover_week,
            },
        }

        self._continuous_cache[cache_key] = {"time": now, "payload": payload}
        return payload

    def get_rollover_history(self, symbol):
        root = self._normalize_root(symbol)
        events = [item for item in self._load_events() if item.get("symbol") == root]
        events.sort(key=lambda item: item.get("rollover_date", ""), reverse=True)
        return {
            "symbol": root,
            "events": events,
            "count": len(events),
        }

    def get_rollover_status(self, symbol):
        detection = self.detect_rollover(symbol)
        ratio = float(detection.get("volume_ratio", 0) or 0)
        rollover_imminent = (ratio >= 0.9) and (not detection.get("rollover_detected"))
        return {
            "symbol": detection.get("symbol"),
            "current_front": detection.get("front_contract"),
            "next_contract": detection.get("next_contract"),
            "active_contract": detection.get("active_contract"),
            "rollover_detected": bool(detection.get("rollover_detected", False)),
            "rollover_imminent": rollover_imminent,
            "rollover_week": bool(detection.get("rollover_date")) and bool(detection.get("rollover_confirmed_days", 0)),
            "volume_ratio": round(ratio, 4),
            "latest_compare_day": detection.get("latest_compare_day"),
            "adjustment_value": detection.get("adjustment_value", 0),
        }
