import time
from datetime import datetime, timezone
from typing import Dict, Optional

from astroquant.engine.databento import AstroQuantFinalDataEngine, FuturesSpotSyncModel, GCXAUUSDSyncModel
from astroquant.engine.contract_resolver import ContractResolver


class DatabentoSyncEngine:
    """
    Runtime sync wrapper over AstroQuantFinalDataEngine.

    Produces synchronized GC/ES snapshots with safe clamping and fallback logic
    inherited from the final data engine.

    GC → XAUUSD institutional sync:
        attach_runner(runner) wires the Playwright broker XAUUSD price into
        gc_xauusd_sync so that convert_signal() produces execution-ready
        XAUUSD entry/SL/TP from any GC futures signal.
    """

    DEFAULT_BRIDGES = {
        "XAUUSD": {
            "futures_alias": "GC",
            "default_contracts": ["GCJ6", "GCM6", "GCQ6"],
        },
        "NQ": {
            "futures_alias": "NQ",
            "default_contracts": ["NQH6", "NQM6"],
        },
        "EURUSD": {
            "futures_alias": "6E",
            "default_contracts": ["6EH6", "6EM6"],
        },
        "US30": {
            "futures_alias": "YM",
            "default_contracts": ["YMH6", "YMM6"],
        },
    }

    ROOT_MONTH_CYCLES = {
        "GC": ["G", "J", "M", "Q", "V", "Z"],
        "NQ": ["H", "M", "U", "Z"],
        "6E": ["H", "M", "U", "Z"],
        "YM": ["H", "M", "U", "Z"],
    }

    MONTH_CODE_TO_MONTH = {
        "F": 1,
        "G": 2,
        "H": 3,
        "J": 4,
        "K": 5,
        "M": 6,
        "N": 7,
        "Q": 8,
        "U": 9,
        "V": 10,
        "X": 11,
        "Z": 12,
    }

    @staticmethod
    def _classify_fetch_error(exc: Exception) -> str:
        text = str(exc or "")
        low = text.lower()
        if "symbology_invalid_request" in low or "symbology_invalid_symbol" in low:
            return "UNSUPPORTED_SYMBOL_OR_ENTITLEMENT"
        if "authentication" in low or "401" in low:
            return "AUTH_ERROR"
        if "timeout" in low:
            return "TIMEOUT"
        return "FETCH_ERROR"

    def __init__(self, safety_lag_minutes: int = 30, runner=None):
        self.engine = AstroQuantFinalDataEngine(safety_lag_minutes=safety_lag_minutes)
        self.last_snapshot: Dict[str, Optional[dict]] = {"GC": None, "ES": None}
        self.contract_resolver = ContractResolver()
        self.contract_probe_cooldown_seconds = 120
        self.contract_ttl_seconds = 6 * 3600
        self.auto_disable_threshold = 8
        self.symbols = list(self.DEFAULT_BRIDGES.keys())
        self.auto_reenable_seconds = 6 * 3600
        self.last_prices: Dict[str, Optional[float]] = {symbol: None for symbol in self.symbols}
        self.last_futures_sources: Dict[str, Optional[str]] = {symbol: None for symbol in self.symbols}
        self.last_symbol_sync_snapshots: Dict[str, dict] = {}
        # GC → XAUUSD sync model (wired to Playwright broker if runner provided)
        self.gc_xauusd_sync: Optional[GCXAUUSDSyncModel] = None
        self.symbol_sync_models: Dict[str, FuturesSpotSyncModel] = {}
        if runner is not None:
            self.attach_runner(runner)
        else:
            self._attach_placeholder_models()

    def _make_no_broker_spot_getter(self, broker_symbol: str):
        key = str(broker_symbol or "").upper()

        def _getter():
            return (None, f"NO_BROKER:{key}", time.time())

        return _getter

    def _attach_placeholder_models(self) -> None:
        """
        Attach models without broker runner so runtime fields/snapshots remain
        available in API-only deployments.
        """
        self.gc_xauusd_sync = GCXAUUSDSyncModel(
            get_xauusd_price_fn=self._make_no_broker_spot_getter("XAUUSD")
        )
        self.symbol_sync_models["XAUUSD"] = self.gc_xauusd_sync

        for broker_symbol, cfg in self.DEFAULT_BRIDGES.items():
            if broker_symbol == "XAUUSD":
                continue
            self.symbol_sync_models[broker_symbol] = FuturesSpotSyncModel(
                canonical_symbol=broker_symbol,
                broker_symbol=broker_symbol,
                futures_symbol=cfg["futures_alias"],
                get_spot_price_fn=self._make_no_broker_spot_getter(broker_symbol),
            )

    def attach_runner(self, runner) -> None:
        """
        Wire the MultiSymbolRunner's Playwright broker quote into the sync model.
        Call this once the runner's browser session is active.
        """
        self.gc_xauusd_sync = GCXAUUSDSyncModel(runner=runner)
        self.symbol_sync_models["XAUUSD"] = self.gc_xauusd_sync

        # Additional institutional bridges beyond gold.
        for broker_symbol, cfg in self.DEFAULT_BRIDGES.items():
            if broker_symbol == "XAUUSD":
                continue
            self.symbol_sync_models[broker_symbol] = FuturesSpotSyncModel(
                canonical_symbol=broker_symbol,
                broker_symbol=broker_symbol,
                futures_symbol=cfg["futures_alias"],
                runner=runner,
            )

    def get_active_futures_contract(self, broker_symbol: str) -> str:
        """
        Resolve active futures contract from latest snapshots with fallback defaults.

        This is a pragmatic rollover-safe helper: if the requested market has a
        recent symbol in snapshots, use it; otherwise fall back to first
        configured contract candidate.
        """
        symbol = str(broker_symbol or "").upper()
        if self.contract_resolver.is_disabled(symbol):
            return symbol
        cfg = self.DEFAULT_BRIDGES.get(symbol, {})
        defaults = list(cfg.get("default_contracts") or [])

        if symbol == "XAUUSD" and self.last_snapshot.get("GC"):
            return str(self.last_snapshot["GC"].get("symbol") or (defaults[0] if defaults else "GCJ6"))
        if symbol == "NQ" and self.last_snapshot.get("ES"):
            # If no dedicated NQ snapshot, reuse ES cadence only for timestamping.
            return str(self.last_snapshot["ES"].get("symbol") or (defaults[0] if defaults else "NQH6"))

        cached = self.contract_resolver.get_cached(symbol, max_age_seconds=self.contract_ttl_seconds)
        if cached:
            return cached

        dynamic_candidates = self.get_contract_candidates(symbol, max_count=3)
        candidates = dynamic_candidates or defaults

        if not candidates:
            return symbol

        if not self.contract_resolver.can_probe(symbol, cooldown_seconds=self.contract_probe_cooldown_seconds):
            return str(candidates[0])

        try:
            probe = self.engine.fetch_with_fallback(candidates, minutes=60)
            self.contract_resolver.set_active(
                symbol,
                probe.symbol,
                sample_count=probe.records,
                candidates_tried=candidates,
                ttl_seconds=self.contract_ttl_seconds,
            )
            return str(probe.symbol)
        except Exception:
            self.contract_resolver.mark_unresolved(symbol, candidates_tried=candidates)
            return str(candidates[0])

        if defaults:
            return str(defaults[0])
        return symbol

    def get_contract_candidates(self, broker_symbol: str, max_count: int = 3) -> list[str]:
        """
        Build rolling candidate futures contracts from month cycles.
        Example: GC -> [GCJ6, GCM6, GCQ6] depending on current UTC month.
        """
        key = str(broker_symbol or "").upper()
        cfg = self.DEFAULT_BRIDGES.get(key, {})
        root = str(cfg.get("futures_alias") or key)
        cycles = list(self.ROOT_MONTH_CYCLES.get(root, []))
        if not cycles:
            return list(cfg.get("default_contracts") or [])

        now = datetime.now(timezone.utc)
        current_month = int(now.month)
        current_year = int(now.year)

        month_sequence = []
        for code in cycles:
            month_num = self.MONTH_CODE_TO_MONTH.get(code)
            if month_num is not None:
                month_sequence.append((month_num, code))
        month_sequence.sort(key=lambda x: x[0])
        if not month_sequence:
            return list(cfg.get("default_contracts") or [])

        picks = []
        year = current_year
        month_cursor = current_month
        attempts = 0
        max_needed = max(1, int(max_count))

        while len(picks) < max_needed and attempts < 16:
            attempts += 1
            next_pair = None
            for month_num, code in month_sequence:
                if month_num >= month_cursor:
                    next_pair = (month_num, code)
                    break
            if next_pair is None:
                year += 1
                month_cursor = 1
                continue

            month_num, code = next_pair
            contract = f"{root}{code}{str(year)[-1]}"
            if contract not in picks:
                picks.append(contract)
            month_cursor = month_num + 1
            if month_cursor > 12:
                year += 1
                month_cursor = 1

        if picks:
            return picks
        return list(cfg.get("default_contracts") or [])

    def update_symbol_sync(
        self,
        broker_symbol: str,
        futures_price: float,
        futures_source: Optional[str] = None,
        futures_timestamp: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Feed any futures tick into its corresponding broker-spot bridge model.

        Useful for non-GC symbols where futures feeds come from another engine.
        """
        key = str(broker_symbol or "").upper()
        model = self.symbol_sync_models.get(key)
        if model is None:
            return None
        if key == "XAUUSD" and isinstance(model, GCXAUUSDSyncModel):
            return model.update(
                gc_futures_price=float(futures_price),
                gc_source=futures_source or self.get_active_futures_contract(key),
                event_time=futures_timestamp,
            )
        return model.update(
            futures_price=float(futures_price),
            futures_source=futures_source or self.get_active_futures_contract(key),
            event_time=futures_timestamp,
        )

    def get_gc_xauusd_snapshot(self, gc_price: Optional[float] = None, gc_source: str = "GCJ6") -> Optional[dict]:
        """
        Update and return the GC → XAUUSD basis snapshot.
        Uses the latest_price from last GC fetch if gc_price not specified.
        Returns None if sync model is not yet attached.
        """
        if self.gc_xauusd_sync is None:
            return None
        price = gc_price
        if price is None and self.last_snapshot.get("GC"):
            price = self.last_snapshot["GC"].get("latest_price")
        if price is None:
            return None
        return self.gc_xauusd_sync.update(gc_futures_price=float(price), gc_source=gc_source)

    def get_symbol_sync_snapshot(
        self,
        broker_symbol: str,
        futures_price: Optional[float] = None,
        futures_source: Optional[str] = None,
        futures_timestamp: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Generic accessor for all bridges (XAUUSD, NQ, EURUSD, BTC, US30).
        """
        key = str(broker_symbol or "").upper()
        model = self.symbol_sync_models.get(key)
        if model is None:
            return None

        resolved_price = futures_price
        resolved_source = futures_source or self.get_active_futures_contract(key)
        resolved_ts = futures_timestamp

        if resolved_price is None and key == "XAUUSD" and self.last_snapshot.get("GC"):
            resolved_price = self.last_snapshot["GC"].get("latest_price")
            resolved_source = self.last_snapshot["GC"].get("symbol") or resolved_source
            try:
                iso = self.last_snapshot["GC"].get("latest_ts")
                if iso:
                    resolved_ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
            except Exception:
                resolved_ts = None

        if resolved_price is None:
            return None

        return model.update(
            futures_price=float(resolved_price),
            futures_source=resolved_source,
            event_time=resolved_ts,
        )

    def _extract_latest_price_and_ts(self, result) -> tuple[Optional[float], Optional[float]]:
        latest_price = None
        latest_ts = None
        try:
            if result.records > 0 and len(result.dataframe.index) > 0:
                tail = result.dataframe.tail(1)
                if "price" in tail.columns:
                    latest_price = float(tail["price"].iloc[0])
                elif "close" in tail.columns:
                    latest_price = float(tail["close"].iloc[0])
                raw_ts = tail.index[0]
                if hasattr(raw_ts, "timestamp"):
                    latest_ts = float(raw_ts.timestamp())
                elif hasattr(raw_ts, "isoformat"):
                    latest_ts = datetime.fromisoformat(raw_ts.isoformat().replace("Z", "+00:00")).timestamp()
        except Exception:
            latest_price = None
            latest_ts = None
        return latest_price, latest_ts

    def _fetch_symbol_latest(self, contract_symbol: str, minutes: int = 60):
        result = self.engine.fetch_with_fallback([contract_symbol], minutes=minutes)
        latest_price, latest_ts = self._extract_latest_price_and_ts(result)
        return result.symbol, latest_price, latest_ts

    def _probe_candidate_contracts(self, broker_symbol: str, minutes: int = 60, max_count: int = 5):
        candidates = self.get_contract_candidates(broker_symbol, max_count=max_count)
        if not candidates:
            return None, None, None

        try:
            result = self.engine.fetch_with_fallback(candidates, minutes=minutes)
            latest_price, latest_ts = self._extract_latest_price_and_ts(result)
            return result.symbol, latest_price, latest_ts
        except Exception:
            return None, None, None

    def update_all_symbol_syncs(self, minutes: int = 60, symbols: Optional[list[str]] = None) -> Dict[str, dict]:
        """
        Refresh futures prices for configured bridge symbols and update sync models.

        If no runner/sync-model is attached for a symbol, this still refreshes
        compatibility fields like `last_prices` and `last_futures_sources`.
        """
        target_symbols = [str(s).upper() for s in (symbols or self.symbols)]
        out: Dict[str, dict] = {}

        for broker_symbol in target_symbols:
            if self.contract_resolver.is_disabled(broker_symbol):
                snap = self.contract_resolver.snapshot(broker_symbol)
                disabled_at = snap.get("disabled_at")
                should_retry = False
                if disabled_at:
                    try:
                        should_retry = (int(time.time()) - int(disabled_at)) >= int(self.auto_reenable_seconds)
                    except Exception:
                        should_retry = False

                if should_retry:
                    # Cooldown elapsed: re-enable and allow a new probe cycle.
                    self.contract_resolver.set_enabled(broker_symbol)
                else:
                    self.last_prices[broker_symbol] = None
                    self.last_futures_sources[broker_symbol] = None
                    next_retry_at = None
                    if disabled_at:
                        try:
                            next_retry_at = int(disabled_at) + int(self.auto_reenable_seconds)
                        except Exception:
                            next_retry_at = None
                    self.last_symbol_sync_snapshots[broker_symbol] = {
                        "symbol": broker_symbol,
                        "basis_status": "DISABLED",
                        "guard_reason": snap.get("disable_reason") or "DISABLED",
                        "futures_source": None,
                        "next_retry_at": next_retry_at,
                    }
                    out[broker_symbol] = {
                        "symbol": broker_symbol,
                        "status": "DISABLED",
                        "resolver": snap,
                        "next_retry_at": next_retry_at,
                        "sync_snapshot": self.last_symbol_sync_snapshots[broker_symbol],
                    }
                    continue

            futures_source = self.get_active_futures_contract(broker_symbol)
            futures_price = None
            futures_ts = None

            # Reuse GC/ES snapshot prices when possible to reduce extra requests.
            if broker_symbol == "XAUUSD" and self.last_snapshot.get("GC"):
                futures_price = self.last_snapshot["GC"].get("latest_price")
                futures_source = str(self.last_snapshot["GC"].get("symbol") or futures_source)
                try:
                    iso = self.last_snapshot["GC"].get("latest_ts")
                    if iso:
                        futures_ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
                except Exception:
                    futures_ts = None
            elif broker_symbol == "NQ" and self.last_snapshot.get("ES"):
                # Interim approximation until dedicated NQ timeseries sync is added.
                futures_price = self.last_snapshot["ES"].get("latest_price")
                futures_source = str(self.last_snapshot["ES"].get("symbol") or futures_source)
                try:
                    iso = self.last_snapshot["ES"].get("latest_ts")
                    if iso:
                        futures_ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
                except Exception:
                    futures_ts = None

            if futures_price is None:
                try:
                    resolved_symbol, latest_price, latest_ts = self._fetch_symbol_latest(futures_source, minutes=minutes)
                    futures_source = resolved_symbol
                    futures_price = latest_price
                    futures_ts = latest_ts
                except Exception as exc:
                    # Probe an expanded candidate set before declaring failure.
                    probe_minutes = max(120, int(minutes)) if broker_symbol == "BTC" else max(60, int(minutes))
                    resolved_symbol, latest_price, latest_ts = self._probe_candidate_contracts(
                        broker_symbol,
                        minutes=probe_minutes,
                        max_count=5,
                    )
                    if resolved_symbol is None:
                        err_code = self._classify_fetch_error(exc)
                        self.contract_resolver.mark_unresolved(
                            broker_symbol,
                            candidates_tried=self.get_contract_candidates(broker_symbol, max_count=5),
                        )
                        snap = self.contract_resolver.snapshot(broker_symbol)
                        if (
                            err_code == "UNSUPPORTED_SYMBOL_OR_ENTITLEMENT"
                            and int(snap.get("consecutive_failures", 0)) >= int(self.auto_disable_threshold)
                        ):
                            self.contract_resolver.set_disabled(broker_symbol, reason=err_code)
                            snap = self.contract_resolver.snapshot(broker_symbol)
                        self.last_prices[broker_symbol] = None
                        self.last_futures_sources[broker_symbol] = futures_source
                        self.last_symbol_sync_snapshots[broker_symbol] = {
                            "symbol": broker_symbol,
                            "basis_status": "DISABLED" if snap.get("disabled") else "UNAVAILABLE",
                            "guard_reason": err_code,
                            "futures_source": futures_source,
                        }
                        out[broker_symbol] = {
                            "symbol": broker_symbol,
                            "status": "DISABLED" if snap.get("disabled") else "ERROR",
                            "error_code": err_code,
                            "error": str(exc),
                            "futures_source": futures_source,
                            "resolver": snap,
                            "sync_snapshot": self.last_symbol_sync_snapshots[broker_symbol],
                        }
                        continue
                    futures_source = resolved_symbol
                    futures_price = latest_price
                    futures_ts = latest_ts

            if futures_price is None:
                # One more fallback probe for symbols that returned rows but no usable price field.
                probe_minutes = max(120, int(minutes)) if broker_symbol == "BTC" else max(60, int(minutes))
                resolved_symbol, latest_price, latest_ts = self._probe_candidate_contracts(
                    broker_symbol,
                    minutes=probe_minutes,
                    max_count=5,
                )
                if resolved_symbol is not None:
                    futures_source = resolved_symbol
                    futures_price = latest_price
                    futures_ts = latest_ts

            if futures_price is None:
                self.last_prices[broker_symbol] = None
                self.last_futures_sources[broker_symbol] = futures_source
                self.last_symbol_sync_snapshots[broker_symbol] = {
                    "symbol": broker_symbol,
                    "basis_status": "UNAVAILABLE",
                    "guard_reason": "NO_PRICE_IN_WINDOW",
                    "futures_source": futures_source,
                }
                out[broker_symbol] = {
                    "symbol": broker_symbol,
                    "status": "UNAVAILABLE",
                    "futures_price": None,
                    "futures_source": futures_source,
                    "sync_snapshot": self.last_symbol_sync_snapshots[broker_symbol],
                }
                continue

            self.last_prices[broker_symbol] = float(futures_price)
            self.last_futures_sources[broker_symbol] = futures_source

            snapshot = None
            if broker_symbol in self.symbol_sync_models:
                snapshot = self.update_symbol_sync(
                    broker_symbol=broker_symbol,
                    futures_price=float(futures_price),
                    futures_source=futures_source,
                    futures_timestamp=futures_ts,
                )

            out[broker_symbol] = {
                "symbol": broker_symbol,
                "status": "OK",
                "futures_price": self.last_prices.get(broker_symbol),
                "futures_source": futures_source,
                "sync_snapshot": snapshot,
            }
            if snapshot is not None:
                self.last_symbol_sync_snapshots[broker_symbol] = snapshot

        return out

    def get_symbol_registry(self) -> Dict[str, dict]:
        """
        Returns operational symbol registry with enabled/disabled state and resolver info.
        """
        rows: Dict[str, dict] = {}
        for symbol in self.symbols:
            snap = self.contract_resolver.snapshot(symbol)
            next_retry_at = None
            if snap.get("disabled") and snap.get("disabled_at"):
                try:
                    next_retry_at = int(snap.get("disabled_at")) + int(self.auto_reenable_seconds)
                except Exception:
                    next_retry_at = None
            rows[symbol] = {
                "symbol": symbol,
                "enabled": not bool(snap.get("disabled")),
                "disable_reason": snap.get("disable_reason"),
                "next_retry_at": next_retry_at,
                "active_symbol": snap.get("active_symbol"),
                "last_status": snap.get("last_status"),
                "attempts": snap.get("attempts"),
                "consecutive_failures": snap.get("consecutive_failures"),
                "resolver": snap,
            }
        return rows

    def fetch_all(self, minutes: int = 60, update_bridges: bool = True) -> Dict[str, Optional[dict]]:
        results = self.engine.fetch_synced_gc_es(minutes=minutes)
        snapshot: Dict[str, Optional[dict]] = {}

        for market, result in results.items():
            latest_price = None
            latest_ts = None
            if result.records > 0 and len(result.dataframe.index) > 0:
                # trades schema includes a numeric price field on each row.
                tail = result.dataframe.tail(1)
                latest_price = float(tail["price"].iloc[0]) if "price" in tail.columns else None
                latest_ts = tail.index[0].isoformat() if hasattr(tail.index[0], "isoformat") else str(tail.index[0])

            snapshot[market] = {
                "market": market,
                "symbol": result.symbol,
                "records": result.records,
                "window_start": result.start.isoformat(),
                "window_end": result.end.isoformat(),
                "fallback_used": result.fallback_used,
                "reason": result.reason,
                "latest_price": latest_price,
                "latest_ts": latest_ts,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

        self.last_snapshot = snapshot

        # Auto-update GC→XAUUSD sync model if runner is attached
        if self.gc_xauusd_sync is not None and snapshot.get("GC"):
            gc_price = snapshot["GC"].get("latest_price")
            gc_symbol = snapshot["GC"].get("symbol", "GCJ6")
            gc_event_ts = None
            try:
                iso = snapshot["GC"].get("latest_ts")
                if iso:
                    gc_event_ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
            except Exception:
                gc_event_ts = None
            if gc_price is not None:
                self.gc_xauusd_sync.update(
                    gc_futures_price=float(gc_price),
                    gc_source=gc_symbol,
                    event_time=gc_event_ts,
                )

        if update_bridges:
            self.update_all_symbol_syncs(minutes=minutes)

        return snapshot

    def sync_loop(self, interval: int = 10, minutes: int = 60):
        while True:
            try:
                snap = self.fetch_all(minutes=minutes)
                print("[DatabentoSync]", snap)
            except Exception as exc:
                print(f"[DatabentoSync] ERROR: {exc}")
            time.sleep(max(1, int(interval)))


if __name__ == "__main__":
    engine = DatabentoSyncEngine()
    engine.sync_loop(interval=10, minutes=60)
