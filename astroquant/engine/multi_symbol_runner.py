import time
import json
import sqlite3
import datetime
import threading
from datetime import datetime, timezone
from collections import deque
from engine.signal_manager import SignalManager
from engine.ai_decision import AIDecisionEngine
from engine.governance import Governance
from engine.prop_phase import PropPhase
from engine.risk import RiskEngine
from engine.execution import ExecutionEngine
from engine.journal import JournalEngine
from engine.position_manager import PositionManager
from engine.session_bias import SessionBias
from engine.system_state import SystemState
from engine.regime import RegimeEngine as VolatilityRegimeEngine
from engine.market_feed import MarketFeed
from engine.position_monitor import PositionMonitor
from engine.slippage import SlippageGuard
from engine.telegram import TelegramEngine
from telegram.clawbot import ClawbotEngine
from engine.capital_engine import CapitalEngine
from engine.montecarlo_engine import MonteCarlo
from engine.basis_engine import BasisEngine
from engine.contract_resolver import ContractResolver
from engine.position_reconciliation import PositionReconciliationEngine
from engine.broker_equity_verification import BrokerEquityVerificationEngine
from backend.ai.model_learning import ModelLearningEngine
from backend.config import (
    DATABENTO_API_KEY,
    DATABENTO_DATASET,
    SPOT_CONFIRMATION_MAX_BPS,
    SPOT_FIDELITY_STRICT,
    SPOT_FIDELITY_SYMBOLS,
    symbol_dataset,
)


class MultiSymbolRunner:

    SYMBOL_MAP = {
        "XAUUSD": "GC.c.1",
        "NQ": "NQ.c.1",
        "EURUSD": "6E.c.1",
        "BTC": "BTC.c.1",
        "US30": "YM.c.1",
    }

    SPOT_SYMBOL_MAP = {
        "XAUUSD": ["XAUUSD", "XAU/USD"],
        "NQ": ["NDX", "US100"],
        "EURUSD": ["EURUSD"],
        "BTC": ["BTCUSD", "BTC-USD"],
        "US30": ["US30", "DJI"],
    }

    ROOT_MONTH_CYCLES = {
        "GC": ["G", "J", "M", "Q", "V", "Z"],
        "NQ": ["H", "M", "U", "Z"],
        "6E": ["H", "M", "U", "Z"],
        "YM": ["H", "M", "U", "Z"],
        "BTC": ["H", "M", "U", "Z"],
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

    def __init__(self, symbols, prop_engine=None):
        self.symbols = symbols
        self.state = SystemState()
        self.prop_engine = prop_engine
        if self.prop_engine:
            self.state.phase = self.prop_engine.phase

        self.signal_manager = SignalManager(DATABENTO_API_KEY)
        self.ai_engine = AIDecisionEngine()
        self.governance = Governance(self.state)
        self.prop = PropPhase(self.state)
        self.risk = RiskEngine(self.state)
        self.execution = ExecutionEngine()
        self.journal = JournalEngine(self.state)
        self.session_bias = SessionBias()
        self.regime_engine = VolatilityRegimeEngine()
        self.monitor = PositionMonitor()
        self.slippage_guard = SlippageGuard()
        self.telegram = TelegramEngine()
        self.clawbot = ClawbotEngine()
        self.feed = MarketFeed(DATABENTO_API_KEY)
        self.dataset = DATABENTO_DATASET
        self.spot_fidelity_symbols = set(str(s).upper() for s in SPOT_FIDELITY_SYMBOLS)
        self.spot_fidelity_strict = bool(SPOT_FIDELITY_STRICT)
        self.spot_confirmation_max_bps = float(SPOT_CONFIRMATION_MAX_BPS)
        self.spot_tick_history = {str(symbol).upper(): deque(maxlen=600) for symbol in self.symbols}
        self.broker_spot_cache = {}
        self.broker_spot_cache_lock = threading.Lock()
        self.broker_spot_refresh_pending = set()
        self.broker_spot_refresh_min_interval_seconds = 1.0
        self.broker_spot_quote_ttl_seconds = 8.0
        self.broker_spot_scanner_interval_seconds = 1.5
        self.broker_spot_scanner_enabled = True
        self.capital = CapitalEngine()
        self.montecarlo = MonteCarlo()
        self.montecarlo_checked = False
        self.model_learning_engine = ModelLearningEngine()
        self.basis_engine = BasisEngine()
        self.contract_resolver = ContractResolver()
        self.reconciliation_engine = PositionReconciliationEngine()
        self.last_reconciliation = self.reconciliation_engine.snapshot()
        self.equity_verification_engine = BrokerEquityVerificationEngine()
        self.last_equity_verification = self.equity_verification_engine.snapshot()
        self.last_prop_behavior = {}
        self.prop_behavior_overrides = {}
        self.watch_only_symbols = {}
        self.watch_alerted_at = {}
        self.watch_failure_threshold = 4
        self.watch_alert_cooldown_seconds = 15 * 60

        self.positions = PositionManager(self.state)
        self.cooldowns = {}
        self.entry_attempt_lock = {}
        self.symbol_cycle_seconds = 10
        self.reconciliation_interval_seconds = 3
        self.equity_verify_interval_seconds = 3
        self.entry_lock_seconds = 60
        self.trade_cooldown_seconds = 300
        self.max_trades_per_day_limit = 20
        self.max_concurrent_trades_limit = 2
        self.max_spread_limit = 2.5
        self.auto_trading_enabled = True
        self.disabled_symbols = set()
        self.engine_enable_flags = {"ICT": True, "ICEBERG": True, "GANN": True, "ASTRO": True}
        self.min_confidence_threshold = 55.0
        self.confluence_threshold = 0.5
        self.phase_risk_multipliers = {"PHASE1": 1.0, "PHASE2": 1.0, "FUNDED": 1.0}
        self.strict_challenge_mode = True
        self.allowed_models_for_challenge = {
            "ICT",
            "ICEBERG",
            "ORDERFLOW_IMBALANCE",
            "LIQUIDITY_TRAP",
            "GANN",
            "NEWS",
            "EXPANSION",
        }
        self.offset_baselines = {}
        self.offset_baseline_day = {}
        self.offset_smooth_window = {str(symbol).upper(): deque(maxlen=20) for symbol in self.symbols}
        self.offset_halt_points = 3.0
        self.offset_kill_points = 5.0
        self.daily_trade_count = 0
        self.daily_trade_date = datetime.now(timezone.utc).date()
        self.prop_status_callback = None

        self.running = False
        self._start_broker_spot_scanner()

    def _start_broker_spot_scanner(self):
        if not bool(self.broker_spot_scanner_enabled):
            return

        def _loop():
            while bool(self.broker_spot_scanner_enabled):
                try:
                    watch_symbols = set(self.spot_fidelity_symbols) | set(self.SPOT_SYMBOL_MAP.keys())
                    for canonical in sorted(watch_symbols):
                        self._schedule_broker_spot_refresh(canonical)
                except Exception:
                    pass
                time.sleep(max(0.5, float(self.broker_spot_scanner_interval_seconds)))

        threading.Thread(target=_loop, daemon=True, name="aq-broker-spot-scanner").start()

    def _is_allowed_execution_model(self, model_name: str | None) -> bool:
        name = str(model_name or "").upper().strip()
        if not name:
            return False
        # Allow exact model match or prefixed variants like ICT_LIQUIDITY.
        return any(name == token or name.startswith(f"{token}_") for token in self.allowed_models_for_challenge)

    def verify_broker_equity(self):
        snapshot = self.equity_verification_engine.verify(
            internal_equity=self.state.balance,
            broker_equity=self.execution.broker_equity_snapshot(),
        )
        self.last_equity_verification = snapshot
        if snapshot.get("hard_halt"):
            self.execution.emergency_halt(snapshot.get("reason") or "Equity mismatch")
        return snapshot

    def reconcile_positions(self):
        snapshot = self.reconciliation_engine.reconcile(
            internal_positions=self.positions.get_positions(),
            broker_positions=self.execution.broker_positions_snapshot(),
        )
        self.last_reconciliation = snapshot
        if snapshot.get("hard_halt"):
            self.execution.emergency_halt(snapshot.get("reason") or "Position reconciliation mismatch")
        return snapshot

    def _front_month_contracts(self, root):
        cycle = self.ROOT_MONTH_CYCLES.get(root, ["H", "M", "U", "Z"])
        now = datetime.now(timezone.utc)
        current_month = now.month
        current_year = now.year

        ordered = sorted(cycle, key=lambda code: self.MONTH_CODE_TO_MONTH.get(code, 13))
        fronts = []
        for year_offset in (0, 1):
            year = current_year + year_offset
            for code in ordered:
                contract_month = self.MONTH_CODE_TO_MONTH.get(code, 13)
                if year_offset == 0 and contract_month < current_month:
                    continue
                y1 = str(year)[-1]
                y2 = str(year)[-2:]
                fronts.append(f"{root}{code}{y1}")
                fronts.append(f"{root}{code}{y2}")
        return fronts[:10]

    def candidate_feed_symbols(self, symbol, include_contracts=True):
        preferred_feed_symbol = self.SYMBOL_MAP.get(symbol, symbol)
        root = preferred_feed_symbol.split(".")[0] if preferred_feed_symbol else symbol

        raw_contracts = []
        # Enhanced fallback for GC-F and other symbols
        if include_contracts:
            if root in {"GC-F", "GC", "GC.FUT"}:
                raw_contracts = ["GC.FUT", "GC.c.1", "GC.c.0", "GCJ6", "GCJ26"]
            elif root in {"NQ", "NQ-F", "NQ.FUT"}:
                raw_contracts = ["NQ.FUT", "NQ.c.1", "NQ.c.0"]
            elif root in {"6E", "EURUSD", "6E.FUT"}:
                raw_contracts = ["6E.FUT", "6E.c.1", "6E.c.0"]
            elif root in {"BTC", "BTC-F", "BTC.FUT"}:
                raw_contracts = ["BTC.FUT", "BTC.c.1", "BTC.c.0"]
            elif root in {"YM", "US30", "YM.FUT"}:
                raw_contracts = ["YM.FUT", "YM.c.1", "YM.c.0"]
            else:
                raw_contracts = self._front_month_contracts(root)

        candidates = [
            preferred_feed_symbol,
            f"{root}.c.0",
            f"{root}.c.1",
            *raw_contracts,
            root,
        ]

        seen = set()
        unique = []
        for value in candidates:
            key = str(value or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(key)
        return unique

    def resolve_active_feed_symbol(self, symbol, max_candidates=4, force_probe=False, max_probe_seconds=6.0):
        preferred = self.SYMBOL_MAP.get(symbol, symbol)
        cached = self.contract_resolver.get_cached(symbol, max_age_seconds=6 * 3600)
        valid_candidates = set(self.candidate_feed_symbols(symbol, include_contracts=True))

        if cached and cached not in valid_candidates:
            self.contract_resolver.invalidate_active(symbol, reason="INVALID_SYMBOL_CACHE")
            cached = None

        if cached and not force_probe:
            return cached

        if not force_probe and not self.contract_resolver.can_probe(symbol, cooldown_seconds=120):
            return cached or preferred

        dataset = symbol_dataset(symbol)
        candidates = self.candidate_feed_symbols(symbol, include_contracts=True)[: max(1, min(int(max_candidates), 12))]
        probe_start = time.monotonic()
        for candidate in candidates:
            if (time.monotonic() - probe_start) > float(max_probe_seconds):
                break
            candles = self.feed.get_ohlcv(
                dataset=dataset,
                symbol=candidate,
                lookback_minutes=180,
                record_limit=400,
            )
            if candles:
                self.contract_resolver.set_active(symbol, candidate, sample_count=len(candles), candidates_tried=candidates, ttl_seconds=4 * 3600)
                return candidate

        self.contract_resolver.mark_unresolved(symbol, candidates_tried=candidates)
        return cached or preferred

    def get_futures_candles(self, symbol, lookback_minutes=180, record_limit=1200, prefer_cached=True):
        dataset = symbol_dataset(symbol)
        active = self.resolve_active_feed_symbol(
            symbol,
            force_probe=not prefer_cached,
            max_candidates=(3 if prefer_cached else 5),
            max_probe_seconds=(4.0 if prefer_cached else 8.0),
        )

        bounded_lookback = max(60, min(int(lookback_minutes or 180), 60 * 24 * 3))
        bounded_limit = max(100, min(int(record_limit or 1200), 4000))

        base_candidates = self.candidate_feed_symbols(symbol, include_contracts=True)
        root = str(self.SYMBOL_MAP.get(symbol, symbol) or symbol).split(".")[0]
        preferred_continuous = [f"{root}.c.1", f"{root}.c.0"]

        ordered_candidates = []
        if str(active or "").endswith(".FUT"):
            ordered_candidates.extend(preferred_continuous)
            ordered_candidates.append(active)
        else:
            ordered_candidates.append(active)
            ordered_candidates.extend(preferred_continuous)
        ordered_candidates.extend(base_candidates)

        unique_candidates = []
        seen_candidates = set()
        for candidate in ordered_candidates:
            key = str(candidate or "").strip()
            if not key or key in seen_candidates:
                continue
            seen_candidates.add(key)
            unique_candidates.append(key)

        attempted = []
        for candidate in unique_candidates[:6]:
            attempted.append(candidate)
            candidate_candles = self.feed.get_ohlcv(
                dataset=dataset,
                symbol=candidate,
                lookback_minutes=bounded_lookback,
                record_limit=bounded_limit,
            )
            if candidate_candles:
                self.contract_resolver.set_active(
                    symbol,
                    candidate,
                    sample_count=len(candidate_candles),
                    candidates_tried=attempted,
                    ttl_seconds=4 * 3600,
                )
                return candidate, candidate_candles

        self.contract_resolver.mark_miss(symbol, failed_symbol=active)

        preferred = self.SYMBOL_MAP.get(symbol, symbol)
        if active != preferred:
            preferred_candles = self.feed.get_ohlcv(
                dataset=dataset,
                symbol=preferred,
                lookback_minutes=bounded_lookback,
                record_limit=bounded_limit,
            )
            if preferred_candles:
                self.contract_resolver.set_active(symbol, preferred, sample_count=len(preferred_candles), candidates_tried=[active, preferred], ttl_seconds=4 * 3600)
                return preferred, preferred_candles

        return active, []

    def warmup_contracts(self, force_probe=False, max_candidates=2, max_probe_seconds=2.0):
        warmed = {}
        for symbol in self.symbols:
            active = self.resolve_active_feed_symbol(
                symbol,
                force_probe=force_probe,
                max_candidates=max(1, min(int(max_candidates or 2), 6)),
                max_probe_seconds=max(0.5, min(float(max_probe_seconds or 2.0), 6.0)),
            )
            warmed[symbol] = {
                "active_symbol": active,
                "resolver": self.contract_resolver.snapshot(symbol),
            }
        return warmed

    def get_spot_price(self, symbol):
        canonical = str(symbol).upper()
        if canonical in self.spot_fidelity_symbols or canonical in self.SPOT_SYMBOL_MAP:
            broker_quote = self.get_broker_spot_quote(symbol)
            if broker_quote.get("price") is not None:
                return float(broker_quote["price"]), broker_quote.get("source")
            # Avoid unsupported raw-symbol probes on futures datasets for spot aliases.
            return None, None

        dataset = symbol_dataset(symbol)
        candidates = [symbol] + self.SPOT_SYMBOL_MAP.get(symbol, [])
        checked = set()

        for candidate in candidates:
            spot_symbol = str(candidate or "").strip()
            if not spot_symbol or spot_symbol in checked:
                continue
            checked.add(spot_symbol)

            self.feed.ensure_live_subscription(dataset=dataset, symbol=spot_symbol, stype_in="raw_symbol")
            live_quote = self.feed.get_live_quote(dataset=dataset, symbol=spot_symbol, stype_in="raw_symbol", max_age_seconds=20)
            if live_quote and live_quote.get("price") is not None:
                try:
                    return float(live_quote.get("price")), f"DATABENTO_LIVE:{spot_symbol}"
                except Exception:
                    pass

            candles = self.feed.get_ohlcv(
                dataset=dataset,
                symbol=spot_symbol,
                lookback_minutes=180,
                stype_in="raw_symbol",
                record_limit=1200,
            )
            if candles:
                try:
                    return float(candles[-1]["close"]), f"DATABENTO:{spot_symbol}"
                except Exception:
                    continue

        return None, None

    def _record_spot_tick(self, symbol, price, source):
        key = str(symbol).upper()
        series = self.spot_tick_history.setdefault(key, deque(maxlen=600))
        now = int(time.time())
        series.append({
            "time": now,
            "price": float(price),
            "source": source,
        })

    def _spot_candles_from_ticks(self, symbol, lookback_minutes=240):
        key = str(symbol).upper()
        ticks = list(self.spot_tick_history.get(key, []))
        if not ticks:
            return []

        cutoff = int(time.time()) - (max(60, min(int(lookback_minutes or 240), 60 * 24 * 3)) * 60)
        buckets = {}
        for tick in ticks:
            ts = int(tick.get("time", 0))
            if ts < cutoff:
                continue
            bucket = (ts // 60) * 60
            price = float(tick.get("price", 0.0) or 0.0)
            row = buckets.get(bucket)
            if row is None:
                buckets[bucket] = {
                    "time": bucket,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1.0,
                }
                continue
            row["high"] = max(float(row.get("high", price)), price)
            row["low"] = min(float(row.get("low", price)), price)
            row["close"] = price
            row["volume"] = float(row.get("volume", 0.0) or 0.0) + 1.0

        return [buckets[key] for key in sorted(buckets.keys())]

    def get_broker_spot_quote(self, symbol):
        canonical = str(symbol).upper()
        now = time.time()
        with self.broker_spot_cache_lock:
            cached = dict(self.broker_spot_cache.get(canonical) or {})

        cached_price = cached.get("price")
        cached_source = cached.get("source")
        cached_snapshot = cached.get("snapshot")
        cached_at = float(cached.get("captured_at") or 0.0)
        cache_age = (now - cached_at) if cached_at > 0 else None

        if cached_price is not None and cache_age is not None and cache_age <= float(self.broker_spot_quote_ttl_seconds):
            return {
                "price": float(cached_price),
                "source": cached_source,
                "snapshot": cached_snapshot,
                "cache_age_seconds": cache_age,
                "stale": False,
                "from_cache": True,
            }

        self._schedule_broker_spot_refresh(canonical)

        if cached_price is not None:
            return {
                "price": float(cached_price),
                "source": cached_source,
                "snapshot": cached_snapshot,
                "cache_age_seconds": cache_age,
                "stale": True,
                "from_cache": True,
            }

        return {"price": None, "source": None, "snapshot": cached_snapshot, "stale": True, "from_cache": False}

    def _schedule_broker_spot_refresh(self, canonical):
        key = str(canonical or "").upper().strip()
        if not key:
            return

        now = time.time()
        with self.broker_spot_cache_lock:
            current = dict(self.broker_spot_cache.get(key) or {})
            last_attempt = float(current.get("last_attempt_at") or 0.0)
            if (now - last_attempt) < float(self.broker_spot_refresh_min_interval_seconds):
                return
            if key in self.broker_spot_refresh_pending:
                return
            self.broker_spot_refresh_pending.add(key)
            current["last_attempt_at"] = now
            self.broker_spot_cache[key] = current

        def _worker(target_key):
            try:
                playwright = getattr(self.execution, "playwright", None)
                if getattr(playwright, "page", None) is None:
                    with self.broker_spot_cache_lock:
                        current = dict(self.broker_spot_cache.get(target_key) or {})
                        current["snapshot"] = None
                        current["captured_at"] = time.time()
                        current["source"] = None
                        self.broker_spot_cache[target_key] = current
                    return

                candidates = [target_key] + self.SPOT_SYMBOL_MAP.get(target_key, [])
                snapshot = self.execution.broker_quote_snapshot(expected_symbols=candidates)
                price = None
                source = None
                if snapshot and not bool(snapshot.get("symbol_mismatch")):
                    price = snapshot.get("mid")
                    if price is None:
                        price = snapshot.get("last")
                    if price is not None:
                        symbol_name = str(snapshot.get("symbol") or target_key)
                        source = f"BROKER:{symbol_name}"
                        try:
                            self._record_spot_tick(target_key, float(price), source)
                        except Exception:
                            pass

                with self.broker_spot_cache_lock:
                    current = dict(self.broker_spot_cache.get(target_key) or {})
                    current["snapshot"] = snapshot
                    current["captured_at"] = time.time()
                    current["source"] = source
                    if price is not None:
                        current["price"] = float(price)
                    self.broker_spot_cache[target_key] = current
            except Exception:
                pass
            finally:
                with self.broker_spot_cache_lock:
                    self.broker_spot_refresh_pending.discard(target_key)

        threading.Thread(target=_worker, args=(key,), daemon=True).start()

    def get_spot_candles(self, symbol, lookback_minutes=240, record_limit=2400):
        canonical = str(symbol).upper()
        if canonical in self.spot_fidelity_symbols or canonical in self.SPOT_SYMBOL_MAP:
            broker_quote = self.get_broker_spot_quote(canonical)
            broker_candles = self._spot_candles_from_ticks(canonical, lookback_minutes=lookback_minutes)
            if broker_quote.get("price") is not None and len(broker_candles) >= 5:
                return broker_quote.get("source") or "BROKER", broker_candles[-max(100, min(int(record_limit or 2400), 4000)):]
            return None, []

        dataset = symbol_dataset(symbol)
        candidates = [symbol] + self.SPOT_SYMBOL_MAP.get(symbol, [])
        checked = set()

        bounded_lookback = max(60, min(int(lookback_minutes or 240), 60 * 24 * 3))
        bounded_limit = max(100, min(int(record_limit or 2400), 4000))

        for candidate in candidates:
            spot_symbol = str(candidate or "").strip()
            if not spot_symbol or spot_symbol in checked:
                continue
            checked.add(spot_symbol)

            candles = self.feed.get_ohlcv(
                dataset=dataset,
                symbol=spot_symbol,
                lookback_minutes=bounded_lookback,
                stype_in="raw_symbol",
                record_limit=bounded_limit,
            )
            if candles and len(candles) >= 5:
                return f"DATABENTO:{spot_symbol}", candles

        return None, []

    def update_basis_snapshot(self, symbol, futures_price, futures_source=None):
        spot_price, spot_source = self.get_spot_price(symbol)
        fut_source = futures_source or self.SYMBOL_MAP.get(symbol, symbol)
        return self.basis_engine.update(
            symbol=symbol,
            spot_price=spot_price,
            futures_price=futures_price,
            spot_source=spot_source,
            futures_source=fut_source,
        )

    def get_basis_snapshot(self, symbol):
        return self.basis_engine.snapshot(symbol)

    def basis_summary(self):
        return {symbol: self.basis_engine.snapshot(symbol) for symbol in self.symbols}

    def resolver_watch_snapshot(self, symbol):
        resolver = self.contract_resolver.snapshot(symbol)
        watch = self.watch_only_symbols.get(symbol, {})
        return {
            "symbol": symbol,
            "watch_only": bool(watch.get("watch_only", False)),
            "reason": watch.get("reason"),
            "since": watch.get("since"),
            "last_alert_at": self.watch_alerted_at.get(symbol),
            "failure_threshold": self.watch_failure_threshold,
            "resolver_status": resolver.get("last_status"),
            "resolver_failures": int(resolver.get("consecutive_failures") or 0),
        }

    def resolver_watch_summary(self):
        return {symbol: self.resolver_watch_snapshot(symbol) for symbol in self.symbols}

    def prop_behavior_snapshot(self, symbol):
        if symbol in self.last_prop_behavior:
            return self.last_prop_behavior[symbol]
        return {
            "mode": "UNINITIALIZED",
            "risk_multiplier": 1.0,
            "hard_block": False,
            "reasons": [],
            "phase": self.prop_engine.phase if self.prop_engine else self.state.phase,
        }

    def _cleanup_behavior_override(self, symbol):
        key = str(symbol)
        override = self.prop_behavior_overrides.get(key)
        if not isinstance(override, dict):
            return None
        expires_at = override.get("expires_at")
        if expires_at is not None:
            try:
                if float(expires_at) <= time.time():
                    del self.prop_behavior_overrides[key]
                    return None
            except Exception:
                del self.prop_behavior_overrides[key]
                return None
        return override

    def behavior_override_snapshot(self, symbol):
        key = str(symbol)
        override = self._cleanup_behavior_override(key)
        if override is None:
            return {
                "symbol": key,
                "enabled": False,
            }
        return {
            "symbol": key,
            "enabled": True,
            "mode": override.get("mode"),
            "risk_multiplier": override.get("risk_multiplier"),
            "hard_block": bool(override.get("hard_block", False)),
            "reasons": list(override.get("reasons", [])),
            "created_at": override.get("created_at"),
            "expires_at": override.get("expires_at"),
        }

    def behavior_override_summary(self):
        summary = {}
        for symbol in self.symbols:
            summary[symbol] = self.behavior_override_snapshot(symbol)
        return summary

    def set_behavior_override(
        self,
        symbol,
        mode=None,
        risk_multiplier=None,
        hard_block=None,
        reasons=None,
        expires_minutes=None,
    ):
        key = str(symbol)
        now = time.time()
        override = {
            "created_at": int(now),
            "mode": str(mode).upper() if mode is not None else None,
            "risk_multiplier": (None if risk_multiplier is None else float(risk_multiplier)),
            "hard_block": bool(hard_block) if hard_block is not None else False,
            "reasons": list(reasons or []),
            "expires_at": None,
        }

        if expires_minutes is not None:
            try:
                minutes = max(1.0, float(expires_minutes))
                override["expires_at"] = int(now + (minutes * 60.0))
            except Exception:
                override["expires_at"] = None

        self.prop_behavior_overrides[key] = override
        return self.behavior_override_snapshot(key)

    def clear_behavior_override(self, symbol=None):
        if symbol is None:
            self.prop_behavior_overrides.clear()
            return {"cleared": "ALL"}
        key = str(symbol)
        existed = key in self.prop_behavior_overrides
        self.prop_behavior_overrides.pop(key, None)
        return {"cleared": key, "existed": bool(existed)}

    def apply_behavior_override(self, symbol, behavior):
        key = str(symbol)
        current = dict(behavior or {})
        override = self._cleanup_behavior_override(key)
        if override is None:
            current["override_active"] = False
            return current

        mode = override.get("mode")
        if mode:
            current["mode"] = mode

        risk_multiplier = override.get("risk_multiplier")
        if risk_multiplier is not None:
            current["risk_multiplier"] = max(0.0, min(2.0, float(risk_multiplier)))

        if bool(override.get("hard_block")):
            current["hard_block"] = True

        override_reasons = [str(reason) for reason in list(override.get("reasons", [])) if str(reason).strip()]
        if override_reasons:
            current["reasons"] = [*list(current.get("reasons", [])), *override_reasons]

        current["override_active"] = True
        current["override"] = self.behavior_override_snapshot(key)
        return current

    def prop_behavior_summary(self):
        return {symbol: self.prop_behavior_snapshot(symbol) for symbol in self.symbols}

    def clawbot_status(self):
        if not self.clawbot:
            return {"mode": "UNKNOWN", "risk_multiplier": 1.0, "reason": "Clawbot unavailable"}
        return self.clawbot.status()

    def _send_watch_alert(self, symbol, reason, resolver_snapshot):
        now = int(time.time())
        last_alert = int(self.watch_alerted_at.get(symbol) or 0)
        if (now - last_alert) < int(self.watch_alert_cooldown_seconds):
            return False

        message = (
            f"⚠ Resolver Watch-Only Activated\n"
            f"Symbol: {symbol}\n"
            f"Reason: {reason}\n"
            f"Resolver status: {resolver_snapshot.get('last_status')}\n"
            f"Failures: {resolver_snapshot.get('consecutive_failures')}\n"
            f"Attempts: {resolver_snapshot.get('attempts')}"
        )
        sent = self.telegram.send(message)
        if sent:
            self.watch_alerted_at[symbol] = now
        return sent

    def _send_recovery_alert(self, symbol):
        message = f"✅ Resolver Recovered\nSymbol: {symbol}\nWatch-only mode cleared."
        return self.telegram.send(message)

    def update_resolver_watch_only(self, symbol, resolver_snapshot):
        status = str(resolver_snapshot.get("last_status") or "UNRESOLVED").upper()
        failures = int(resolver_snapshot.get("consecutive_failures") or 0)
        active = self.watch_only_symbols.get(symbol, {})
        active_watch = bool(active.get("watch_only", False))

        if status == "LIVE":
            if active_watch:
                self._send_recovery_alert(symbol)
            self.watch_only_symbols[symbol] = {
                "watch_only": False,
                "reason": None,
                "since": None,
            }
            return self.watch_only_symbols[symbol]

        should_watch = status in {"UNRESOLVED", "MISS", "STALE", "INVALIDATED"} and failures >= self.watch_failure_threshold
        if should_watch:
            reason = f"Resolver {status} with {failures} consecutive failures"
            if not active_watch:
                self.watch_only_symbols[symbol] = {
                    "watch_only": True,
                    "reason": reason,
                    "since": int(time.time()),
                }
            else:
                self.watch_only_symbols[symbol]["reason"] = reason

            self._send_watch_alert(symbol, reason, resolver_snapshot)
            return self.watch_only_symbols[symbol]

        self.watch_only_symbols[symbol] = {
            "watch_only": False,
            "reason": None,
            "since": None,
        }
        return self.watch_only_symbols[symbol]

    def basis_safety_policy(self, symbol, basis_snapshot=None, resolver_snapshot=None):
        basis = basis_snapshot or self.get_basis_snapshot(symbol)
        resolver = resolver_snapshot or self.contract_resolver.snapshot(symbol)

        hard_block = False
        reasons = []
        modifier = 1.0

        basis_status = str(basis.get("status") or "UNINITIALIZED").upper()
        if basis_status == "GUARDED":
            hard_block = True
            reasons.append(f"Basis guarded ({basis.get('guard_reason', 'anomaly')})")

        resolver_status = str(resolver.get("last_status") or "UNRESOLVED").upper()
        resolver_failures = int(resolver.get("consecutive_failures") or 0)
        if resolver_status in {"UNRESOLVED", "STALE"} and resolver_failures >= 3:
            hard_block = True
            reasons.append("Contract resolver unresolved")

        zscore = abs(float(basis.get("zscore") or 0.0))
        if zscore >= 3.0:
            modifier *= 0.5
            reasons.append("Basis z-score >= 3")
        elif zscore >= 2.0:
            modifier *= 0.75
            reasons.append("Basis z-score >= 2")

        sample_count = int(basis.get("sample_count") or 0)
        if sample_count < 8:
            modifier *= 0.8
            reasons.append("Basis sample low")

        if resolver_failures > 0:
            modifier *= 0.85
            reasons.append("Resolver failure history")

        modifier = max(0.3, min(1.0, modifier))
        return {
            "hard_block": hard_block,
            "risk_modifier": modifier,
            "reasons": reasons,
            "basis_status": basis_status,
            "resolver_status": resolver_status,
            "resolver_failures": resolver_failures,
        }

    def offset_guard_snapshot(self, symbol, basis_snapshot=None):
        basis = basis_snapshot or self.get_basis_snapshot(symbol)
        guard = self._offset_guard_state(symbol, basis)
        return {
            "symbol": symbol,
            "status": str(guard.get("status") or "UNAVAILABLE").upper(),
            "deviation": guard.get("deviation"),
            "baseline": guard.get("baseline"),
            "smooth": guard.get("smooth"),
        }

    def trade_quality_snapshot(self, symbol, market_data=None, basis_snapshot=None, basis_policy=None):
        data = market_data or self.get_market_data(symbol) or {}
        basis = basis_snapshot or data.get("basis") or self.get_basis_snapshot(symbol)
        policy = basis_policy or self.basis_safety_policy(symbol, basis_snapshot=basis)
        offset = self.offset_guard_snapshot(symbol, basis_snapshot=basis)

        score = 100.0
        reasons = []

        basis_status = str((basis or {}).get("status") or "UNINITIALIZED").upper()
        if basis_status in {"UNINITIALIZED", "UNAVAILABLE"}:
            score -= 40.0
            reasons.append("Basis unavailable")
        elif basis_status == "STALE":
            score -= 25.0
            reasons.append("Basis stale")
        elif basis_status == "GUARDED":
            score -= 45.0
            reasons.append(str((basis or {}).get("guard_reason") or "Basis guarded"))

        try:
            zscore = abs(float((basis or {}).get("zscore") or 0.0))
        except Exception:
            zscore = 0.0
        if zscore >= 3.0:
            score -= 25.0
            reasons.append("High basis z-score")
        elif zscore >= 2.0:
            score -= 12.0
            reasons.append("Moderate basis z-score")

        if bool((policy or {}).get("hard_block")):
            score -= 45.0
            reasons.append("Basis safety hard block")
        score *= float((policy or {}).get("risk_modifier") or 1.0)

        offset_status = str((offset or {}).get("status") or "UNAVAILABLE").upper()
        if offset_status == "HALT":
            score -= 25.0
            reasons.append("Offset deviation halt")
        elif offset_status == "KILL":
            score -= 45.0
            reasons.append("Offset kill threshold")

        try:
            if bool(data.get("spot_guard_block")):
                score -= 35.0
                reasons.append(str(data.get("spot_guard_reason") or "Spot fidelity guard"))
        except Exception:
            pass

        try:
            if bool(data.get("volume_spike")):
                score += 5.0
            if bool(data.get("liquidity_sweep")):
                score += 3.0
        except Exception:
            pass

        score = max(0.0, min(100.0, float(score)))
        grade = "A" if score >= 80 else ("B" if score >= 65 else ("C" if score >= 50 else "D"))

        signal_preview = []
        try:
            candidates = self.signal_manager.generate_signals(data, symbol) or []
            for row in list(candidates)[:5]:
                signal_preview.append({
                    "model": str(row.get("model") or "UNKNOWN"),
                    "direction": str(row.get("direction") or "").upper(),
                    "confidence": float(row.get("confidence") or 0.0),
                    "risk_percent": float(row.get("risk_percent") or 0.0),
                })
        except Exception:
            signal_preview = []

        return {
            "symbol": symbol,
            "score": round(score, 2),
            "grade": grade,
            "basis_status": basis_status,
            "offset_status": offset_status,
            "hard_block": bool((policy or {}).get("hard_block")),
            "risk_modifier": float((policy or {}).get("risk_modifier") or 1.0),
            "reasons": reasons,
            "signal_candidates": signal_preview,
        }

    def get_market_data(self, symbol):
        feed_symbol, candles = self.get_futures_candles(
            symbol,
            lookback_minutes=240,
            record_limit=2400,
            prefer_cached=True,
        )
        dataset = symbol_dataset(symbol)

        if not candles or len(candles) < 5:
            return None

        pricing_candles = candles
        pricing_source = feed_symbol
        spot_primary = str(symbol).upper() in self.spot_fidelity_symbols
        strict_spot = bool(self.spot_fidelity_strict and spot_primary)
        spot_symbol = None
        spot_confirmation_bps = None
        spot_guard_block = False
        spot_guard_reason = None

        if spot_primary:
            spot_symbol, spot_candles = self.get_spot_candles(
                symbol,
                lookback_minutes=240,
                record_limit=2400,
            )
            if spot_candles:
                pricing_candles = spot_candles
                pricing_source = spot_symbol
                try:
                    futures_price = float(candles[-1]["close"])
                    spot_price = float(spot_candles[-1]["close"])
                    midpoint = (futures_price + spot_price) / 2.0
                    if midpoint > 0:
                        spot_confirmation_bps = abs(((futures_price - spot_price) / midpoint) * 10000.0)
                    if spot_confirmation_bps is not None and spot_confirmation_bps > self.spot_confirmation_max_bps:
                        spot_guard_block = True
                        spot_guard_reason = (
                            f"Spot/Futures divergence {spot_confirmation_bps:.2f}bps > {self.spot_confirmation_max_bps:.2f}bps"
                        )
                except Exception:
                    pass
            elif strict_spot:
                spot_guard_block = True
                spot_guard_reason = "Strict spot fidelity enabled and spot quote unavailable"

        last = pricing_candles[-1]

        trend = "UP" if last["close"] > pricing_candles[-5]["close"] else "DOWN"
        delta = 0.0
        buy_volume = 0.0
        sell_volume = 0.0
        absorption_levels = []
        if self.signal_manager.orderflow_engine:
            trades = self.signal_manager.orderflow_engine.get_recent_trades(
                dataset=dataset,
                symbol=feed_symbol,
            )
            delta, buy_volume, sell_volume = self.signal_manager.orderflow_engine.calculate_delta(trades)
            absorption_levels = self.signal_manager.orderflow_engine.detect_absorption(trades)

        rolling_volumes = [float(c.get("volume", 0.0) or 0.0) for c in pricing_candles[-20:]]
        avg_volume = (sum(rolling_volumes[:-1]) / max(1, len(rolling_volumes) - 1)) if len(rolling_volumes) > 1 else rolling_volumes[-1]
        last_volume = rolling_volumes[-1] if rolling_volumes else 0.0
        volume_spike = bool(last_volume > (avg_volume * 1.35 if avg_volume > 0 else last_volume + 1))

        recent_high = max(float(c["high"]) for c in pricing_candles[-6:-1])
        recent_low = min(float(c["low"]) for c in pricing_candles[-6:-1])
        liquidity_sweep = float(last["high"]) > recent_high or float(last["low"]) < recent_low

        ranges = [max(0.0, float(c["high"]) - float(c["low"])) for c in pricing_candles[-20:]]
        avg_range = (sum(ranges[:-1]) / max(1, len(ranges) - 1)) if len(ranges) > 1 else ranges[-1]
        volatility_breakout = bool(avg_range > 0 and ranges[-1] > (avg_range * 1.6))
        futures_price = float(candles[-1]["close"])
        basis_snapshot = self.update_basis_snapshot(symbol, futures_price, futures_source=feed_symbol)

        return {
            "candles": pricing_candles,
            "trend": trend,
            "dataset": dataset,
            "pricing_source": pricing_source,
            "futures_source": feed_symbol,
            "spot_source": spot_symbol,
            "spot_primary": spot_primary,
            "spot_fidelity_strict": strict_spot,
            "spot_confirmation_bps": spot_confirmation_bps,
            "spot_confirmation_max_bps": self.spot_confirmation_max_bps,
            "spot_guard_block": spot_guard_block,
            "spot_guard_reason": spot_guard_reason,
            "liquidity_sweep": liquidity_sweep,
            "absorption": bool(absorption_levels),
            "absorption_levels": absorption_levels,
            "delta_positive": delta >= 0,
            "delta": delta,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "volatility_breakout": volatility_breakout,
            "time_cycle_alignment": False,
            "high_impact_news": False,
            "volume_spike": volume_spike,
            "basis": basis_snapshot,
        }

    def spread_volatility_filter(self, spread, volatility_mode):
        if spread > float(self.max_spread_limit):
            return False

        if volatility_mode == "HIGH" and spread > 2.0:
            return False

        if volatility_mode == "EXTREME":
            return False

        return True

    def _in_trading_window(self):
        now = datetime.datetime.now(timezone.utc)
        hour = int(now.hour)
        minute = int(now.minute)

        london = 7 <= hour <= 12
        ny_first_half = 13 <= hour <= 15
        if not (london or ny_first_half):
            return False, "Outside London/NY-first-half window"

        in_rollover = (hour == 21 and minute >= 55) or (hour == 22 and minute <= 10)
        if in_rollover:
            return False, "Rollover window lock"

        return True, "OK"

    def _phase_limits_runtime(self):
        phase = str(self.prop_engine.phase if self.prop_engine else self.state.phase).upper()
        if self.prop_engine and hasattr(self.prop_engine, "phase_limits"):
            limits = dict(self.prop_engine.phase_limits(phase))
        else:
            limits = {
                "risk_pct": 0.005,
                "max_trades_per_day": 3,
                "confidence_threshold": 75.0,
                "daily_halt_pct": 0.02,
            }
        limits["phase"] = phase
        return limits

    def _offset_guard_state(self, symbol, basis_snapshot):
        key = str(symbol).upper()
        raw_basis = basis_snapshot.get("raw_basis")
        try:
            raw_basis = float(raw_basis)
        except Exception:
            return {"status": "UNAVAILABLE", "deviation": None, "baseline": None, "smooth": None}

        now = datetime.datetime.now(timezone.utc)
        if now.hour < 7:
            return {"status": "PRE_LONDON", "deviation": 0.0, "baseline": self.offset_baselines.get(key), "smooth": raw_basis}

        window = self.offset_smooth_window.setdefault(key, deque(maxlen=20))
        window.append(raw_basis)
        smooth = sum(window) / max(1, len(window))

        baseline_day = self.offset_baseline_day.get(key)
        if baseline_day != now.date() or key not in self.offset_baselines:
            self.offset_baselines[key] = smooth
            self.offset_baseline_day[key] = now.date()

        baseline = float(self.offset_baselines.get(key, smooth))
        deviation = abs(smooth - baseline)
        if deviation > float(self.offset_kill_points):
            return {"status": "KILL", "deviation": deviation, "baseline": baseline, "smooth": smooth}
        if deviation > float(self.offset_halt_points):
            return {"status": "HALT", "deviation": deviation, "baseline": baseline, "smooth": smooth}
        return {"status": "OK", "deviation": deviation, "baseline": baseline, "smooth": smooth}

    def _audit_event(self, category, action, payload=None):
        try:
            conn = sqlite3.connect("data/admin_control.db")
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO audit_log (category, action, actor, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    str(category or "SYSTEM").upper(),
                    str(action or "EVENT").upper(),
                    "engine",
                    json.dumps(payload or {}, ensure_ascii=False),
                    int(time.time()),
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def process_symbol(self, symbol):
        now_date = datetime.now(timezone.utc).date()
        if now_date != self.daily_trade_date:
            self.daily_trade_date = now_date
            self.daily_trade_count = 0

        if not bool(self.auto_trading_enabled):
            return {"status": "Blocked", "symbol": symbol, "reason": "Auto trading disabled"}

        if str(symbol or "").upper() in self.disabled_symbols:
            return {"status": "Blocked", "symbol": symbol, "reason": "Symbol disabled by admin"}

        if self.strict_challenge_mode:
            session_ok, session_reason = self._in_trading_window()
            if not session_ok:
                return {"status": "Blocked", "symbol": symbol, "reason": session_reason}

        equity_verification = self.verify_broker_equity()
        if equity_verification.get("hard_halt"):
            return {
                "status": "Halted",
                "symbol": symbol,
                "reason": equity_verification.get("reason", "Equity mismatch"),
                "equity_verification": equity_verification,
                "execution_health": self.execution.execution_health(),
            }

        reconciliation = self.reconcile_positions()
        if reconciliation.get("hard_halt"):
            return {
                "status": "Halted",
                "symbol": symbol,
                "reason": reconciliation.get("reason", "Position reconciliation mismatch"),
                "reconciliation": reconciliation,
                "execution_health": self.execution.execution_health(),
            }

        if self.execution.is_halted():
            health = self.execution.execution_health()
            return {
                "status": "Halted",
                "symbol": symbol,
                "reason": health.get("last_error", "Execution HALTED"),
                "execution_health": health,
            }

        feed_health = self.feed.health()
        if not bool(feed_health.get("healthy") or feed_health.get("configured")):
            self.execution.emergency_halt("Databento disconnect")
            return {
                "status": "Halted",
                "symbol": symbol,
                "reason": "Databento disconnect",
                "execution_health": self.execution.execution_health(),
            }

        if self.prop_engine:
            prop_status = self.prop_engine.update_equity(self.state.balance)
            self.state.phase = self.prop_engine.phase
            if callable(self.prop_status_callback):
                try:
                    self.prop_status_callback(prop_status)
                except Exception:
                    pass
            if not self.prop_engine.can_trade():
                return {
                    "status": "Blocked",
                    "symbol": symbol,
                    "reason": "Trading disabled due to prop rule breach",
                    "prop_status": prop_status,
                }

            cooldown_status = self.prop_engine.check_cooldown()
            if cooldown_status != "OK":
                return {
                    "status": "Blocked",
                    "symbol": symbol,
                    "reason": "Cooldown active",
                    "prop_status": cooldown_status,
                }

        mode_now, event_now = self.governance.news.news_risk_mode(symbol)
        self.state.news_halt = (mode_now == "HALT")

        if self.state.news_halt:
            return {"status": "Halted", "symbol": symbol, "reason": f"High impact news ({event_now})"}

        hard_news_halt, news_title, minutes_to_news = self.governance.news.high_impact_halt(symbol, minutes_to_news=20)
        if hard_news_halt:
            return {
                "status": "Halted",
                "symbol": symbol,
                "reason": f"High impact news halt active ({news_title}, T-{minutes_to_news}m)",
            }

        market_data = self.get_market_data(symbol)
        resolver_snapshot = self.contract_resolver.snapshot(symbol)
        resolver_watch = self.update_resolver_watch_only(symbol, resolver_snapshot)
        if resolver_watch.get("watch_only"):
            return {
                "status": "WatchOnly",
                "symbol": symbol,
                "reason": resolver_watch.get("reason", "Resolver watch-only mode"),
                "resolver": resolver_snapshot,
                "resolver_watch": resolver_watch,
            }

        if not market_data:
            return {
                "status": "No Data",
                "symbol": symbol,
                "resolver": resolver_snapshot,
                "resolver_watch": resolver_watch,
            }

        basis_snapshot = market_data.get("basis", self.get_basis_snapshot(symbol))
        if basis_snapshot.get("status") == "GUARDED":
            return {
                "status": "Blocked",
                "symbol": symbol,
                "reason": f"Basis safety guard ({basis_snapshot.get('guard_reason', 'anomaly detected')})",
                "basis": basis_snapshot,
            }

        basis_policy = self.basis_safety_policy(symbol, basis_snapshot=basis_snapshot, resolver_snapshot=resolver_snapshot)
        if basis_policy.get("hard_block"):
            return {
                "status": "Blocked",
                "symbol": symbol,
                "reason": "Basis/Resolver safety policy",
                "basis": basis_snapshot,
                "resolver": resolver_snapshot,
                "basis_policy": basis_policy,
            }

        offset_guard = self._offset_guard_state(symbol, basis_snapshot)
        offset_status = str(offset_guard.get("status") or "OK").upper()
        if offset_status == "KILL":
            import logging, traceback
            logging.basicConfig(level=logging.ERROR)
            logging.error("Offset kill switch triggered for %s: %s\n%s", symbol, offset_guard, traceback.format_stack())
            self.execution.emergency_halt(f"Offset kill switch ({offset_guard.get('deviation', 0.0):.2f}pts)")
            return {
                "status": "Halted",
                "symbol": symbol,
                "reason": "Offset kill switch",
                "offset": offset_guard,
            }
        if offset_status == "HALT":
            return {
                "status": "Blocked",
                "symbol": symbol,
                "reason": f"Offset deviation halt ({offset_guard.get('deviation', 0.0):.2f}pts)",
                "offset": offset_guard,
            }

        if bool(market_data.get("spot_guard_block")):
            return {
                "status": "Blocked",
                "symbol": symbol,
                "reason": market_data.get("spot_guard_reason", "Spot fidelity guard block"),
                "spot_fidelity": {
                    "spot_primary": market_data.get("spot_primary", False),
                    "strict": market_data.get("spot_fidelity_strict", False),
                    "pricing_source": market_data.get("pricing_source"),
                    "futures_source": market_data.get("futures_source"),
                    "spot_source": market_data.get("spot_source"),
                    "confirmation_bps": market_data.get("spot_confirmation_bps"),
                    "confirmation_max_bps": market_data.get("spot_confirmation_max_bps"),
                },
            }

        if self.prop_engine:
            candles = market_data.get("candles", [])
            highs = [float(c.get("high", 0.0) or 0.0) for c in candles]
            lows = [float(c.get("low", 0.0) or 0.0) for c in candles]
            closes = [float(c.get("close", 0.0) or 0.0) for c in candles]
            self.prop_engine.update_volatility(highs, lows, closes, self.prop_engine.baseline_atr)

            behavior = self.prop_engine.auto_behavior_profile(
                equity=self.state.balance,
                daily_loss=self.state.daily_loss,
                drawdown=self.capital.get_drawdown(self.state.balance),
                news_mode=mode_now,
            )
            behavior = self.apply_behavior_override(symbol, behavior)
            self.last_prop_behavior[symbol] = behavior
            if behavior.get("hard_block"):
                self._audit_event("RISK_VIOLATION", "PROP_HARD_BLOCK", {"symbol": symbol, "behavior": behavior})
                return {
                    "status": "Blocked",
                    "symbol": symbol,
                    "reason": "Prop auto-behavior block",
                    "prop_behavior": behavior,
                }

        phase_limits = self._phase_limits_runtime()
        self.max_trades_per_day_limit = int(phase_limits.get("max_trades_per_day", self.max_trades_per_day_limit))
        self.min_confidence_threshold = float(phase_limits.get("confidence_threshold", self.min_confidence_threshold))

        now = time.time()
        lock_timestamp = float(self.entry_attempt_lock.get(symbol) or 0.0)
        if (now - lock_timestamp) < float(self.entry_lock_seconds):
            remaining = int(max(0.0, float(self.entry_lock_seconds) - (now - lock_timestamp)))
            return {"status": "Blocked", "symbol": symbol, "reason": f"Entry lock active ({remaining}s)"}

        if symbol in self.cooldowns:
            if now - self.cooldowns[symbol] < self.trade_cooldown_seconds:
                remaining = int(max(0.0, float(self.trade_cooldown_seconds) - (now - self.cooldowns[symbol])))
                return {"status": "Cooldown", "symbol": symbol, "remaining_seconds": remaining}

        if len(self.positions.get_positions()) >= int(self.max_concurrent_trades_limit):
            self._audit_event("RISK_VIOLATION", "MAX_CONCURRENT_TRADES", {"symbol": symbol, "limit": self.max_concurrent_trades_limit})
            return {"status": "Blocked", "symbol": symbol, "reason": "Max concurrent trades reached"}

        if int(self.daily_trade_count) >= int(self.max_trades_per_day_limit):
            self._audit_event("RISK_VIOLATION", "DAILY_MAX_TRADES", {"symbol": symbol, "limit": self.max_trades_per_day_limit})
            return {"status": "Blocked", "symbol": symbol, "reason": "Daily max trades reached"}

        if self.positions.has_open_position(symbol):
            position = self.state.open_positions[symbol]
            current_price = market_data["candles"][-1]["close"]

            closed, pnl = self.monitor.check_close(position, current_price)

            if closed:
                self.positions.close_position(symbol)
                self.journal.close_trade(
                    position["model"],
                    pnl,
                    trade_context={
                        "symbol": position.get("symbol", symbol),
                        "phase": self.prop_engine.phase if self.prop_engine else self.state.phase,
                        "session": position.get("session", "ASIA"),
                        "volatility": position.get("volatility", "NORMAL"),
                        "volatility_mode": position.get("volatility_mode", self.prop_engine.volatility_mode if self.prop_engine else "NORMAL"),
                        "news_mode": position.get("news_mode", "NORMAL"),
                        "rr": position.get("rr", 0.0),
                        "risk": position.get("risk_percent", 0.0),
                        "entry_price": position.get("entry_price", 0.0),
                        "sl": position.get("sl", 0.0),
                        "tp": position.get("tp", 0.0),
                        "exit_price": current_price,
                        "confidence": position.get("confidence", 0.0),
                        "entry_reason": position.get("entry_reason", "AI-ranked signal selection"),
                        "account_size": self.prop_engine.config.account_size if self.prop_engine else 50000.0,
                        "governance_snapshot": position.get("governance_snapshot", {}),
                        "basis": position.get("basis", {}),
                    },
                )
                if self.prop_engine:
                    self.prop_engine.register_trade_result(pnl, model_name=position.get("model"))
                if pnl < 0:
                    self.state.consecutive_losses = int(self.state.consecutive_losses or 0) + 1
                else:
                    self.state.consecutive_losses = 0
                self.capital.update_equity(self.state.balance)
                print(f"Closed {symbol} trade. PnL: {pnl}")
                return {"status": "Closed", "symbol": symbol, "pnl": pnl}

            return {"status": "Open", "symbol": symbol}

        signals = self.signal_manager.generate_signals(market_data, symbol)
        filtered_signals = []
        for signal in signals or []:
            model_name = str(signal.get("model") or "").upper()
            if "ICT" in model_name and not bool(self.engine_enable_flags.get("ICT", True)):
                continue
            if "ICEBERG" in model_name and not bool(self.engine_enable_flags.get("ICEBERG", True)):
                continue
            if "ASTRO" in model_name and not bool(self.engine_enable_flags.get("ASTRO", True)):
                continue
            if "GANN" in model_name and not bool(self.engine_enable_flags.get("GANN", True)):
                continue

            if self.strict_challenge_mode:
                if not self._is_allowed_execution_model(model_name):
                    continue

            confidence_value = float(signal.get("confidence", 0.0) or 0.0)
            if confidence_value < float(self.min_confidence_threshold):
                continue

            confluence_value = signal.get("confluence")
            if confluence_value is not None and float(confluence_value) < float(self.confluence_threshold):
                continue
            filtered_signals.append(signal)
        signals = filtered_signals

        if not signals:
            return {"status": "No Signal", "symbol": symbol}

        spread = self.get_current_spread(symbol)
        current_volatility_mode = self.prop_engine.volatility_mode if self.prop_engine else "NORMAL"
        if not self.spread_volatility_filter(spread, current_volatility_mode):
            self._audit_event("RISK_VIOLATION", "SPREAD_FILTER_BLOCK", {"symbol": symbol, "spread": spread, "volatility": current_volatility_mode})
            return {"status": "Blocked", "symbol": symbol, "reason": "Spread/Volatility filter blocked trade"}

        clawbot_state = self.clawbot.evaluate(
            loss_streak=int(self.state.consecutive_losses or 0),
            spread=float(spread or 0.0),
            slippage=float(self.slippage_guard.average_slippage() or 0.0),
        )
        claw_mode = str(clawbot_state.get("mode") or "CLEAR").upper()
        if claw_mode == "HALT":
            return {
                "status": "Blocked",
                "symbol": symbol,
                "reason": f"Clawbot halt ({clawbot_state.get('reason', 'risk anomaly')})",
                "clawbot": clawbot_state,
            }

        high_news = (mode_now == "HALT")
        post_news_volatility = (mode_now == "BREAKOUT_ONLY")
        market_data["high_impact_news"] = high_news

        regime = self.regime_engine.detect(market_data)
        regime_weight = self.regime_engine.get_weight(regime)

        if regime == "VOLATILE":
            volatility_regime = "HIGH_VOL"
        elif regime == "ACCUMULATION":
            volatility_regime = "LOW_VOL"
        else:
            volatility_regime = "NORMAL"

        liquidity_vacuum = bool(market_data.get("liquidity_sweep"))
        drawdown = self.capital.get_drawdown(self.state.balance)
        current_session = self.session_bias.get_session()

        ranked = self.ai_engine.rank_models(
            signals,
            regime_weight,
            self.session_bias.get_session_weight(),
            self.state,
            high_news=high_news,
            post_news_volatility=post_news_volatility,
            regime_context={
                "volatility_regime": volatility_regime,
                "news_mode": mode_now,
                "session": current_session,
                "liquidity_vacuum": liquidity_vacuum,
                "drawdown": drawdown,
            },
            symbol=symbol,
        )

        best = self.ai_engine.select_best(ranked)

        if not best:
            return {"status": "No Trade", "symbol": symbol}

        if self.strict_challenge_mode:
            direction = str(best.get("direction") or "").upper()
            delta_positive = bool(market_data.get("delta_positive"))
            if direction == "BUY" and not delta_positive:
                return {"status": "Blocked", "symbol": symbol, "reason": "Delta does not confirm BUY"}
            if direction == "SELL" and delta_positive:
                return {"status": "Blocked", "symbol": symbol, "reason": "Delta does not confirm SELL"}

            model_name = str(best.get("model") or "").upper()
            has_absorption = bool(market_data.get("absorption"))
            if has_absorption and "ICEBERG" not in model_name:
                return {"status": "Blocked", "symbol": symbol, "reason": "Absorption present without Iceberg confirmation"}

        model_wr = self.ai_engine.weight_engine.win_rate(best.get("model", ""))
        learning_data = self.model_learning_engine.analyze()
        model_learning_confidence = float(
            learning_data.get(best.get("model", ""), {}).get("confidence_score", 0.5)
        )
        if model_learning_confidence < 0.45:
            return {
                "status": "Blocked",
                "symbol": symbol,
                "reason": "Model temporarily underperforming",
            }
        if regime == "VOLATILE":
            confidence_regime = "HIGH_VOL"
        elif regime == "ACCUMULATION":
            confidence_regime = "LOW_VOL"
        else:
            confidence_regime = "NORMAL"

        adaptive_threshold = self.ai_engine.adaptive_threshold(
            drawdown=self.capital.get_drawdown(self.state.balance),
            loss_streak=self.state.consecutive_losses,
            regime=confidence_regime,
            avg_slippage=self.slippage_guard.average_slippage(),
            model_win_rate=model_wr,
        )
        passes_confidence, normalized_confidence = self.ai_engine.passes_adaptive_threshold(
            best,
            adaptive_threshold,
        )
        if not passes_confidence:
            return {
                "status": "No Trade",
                "symbol": symbol,
                "reason": f"Confidence below adaptive threshold ({normalized_confidence:.2f} < {adaptive_threshold:.2f})",
            }

        approved, reason = self.governance.validate(
            best,
            spread=spread,
            daily_loss=self.state.daily_loss,
            phase=(self.prop_engine.phase if self.prop_engine else self.state.phase),
            symbol=symbol,
            session=current_session,
        )
        if not approved:
            self._audit_event("RISK_VIOLATION", "GOVERNANCE_BLOCK", {"symbol": symbol, "reason": reason})
            return {"status": "Blocked", "symbol": symbol, "reason": reason}

        limit_check, limit_reason = self.risk.check_limits()
        if not limit_check:
            self._audit_event("RISK_VIOLATION", "RISK_LIMIT_BLOCK", {"symbol": symbol, "reason": limit_reason})
            return {"status": "Blocked", "symbol": symbol, "reason": limit_reason}

        floor_check, floor_reason = self.prop.enforce_floor()
        if not floor_check:
            self._audit_event("RISK_VIOLATION", "PROP_FLOOR_BLOCK", {"symbol": symbol, "reason": floor_reason})
            return {"status": "Blocked", "symbol": symbol, "reason": floor_reason}

        current_phase = self.prop_engine.phase if self.prop_engine else self.state.phase
        if self.prop_engine:
            phase_risk = self.prop_engine.get_phase_risk(news_spike=(mode_now == "REDUCE_RISK"))
        else:
            phase_risk = self.risk.get_phase_risk(current_phase)
        base_risk_percent = float(best.get("risk_percent", phase_risk) or phase_risk)
        base_risk_percent = min(base_risk_percent, phase_risk)
        risk_percent = base_risk_percent * float(best.get("risk_modifier", 1.0) or 1.0)

        if model_wr < 0.40:
            risk_percent *= 0.5
        elif model_wr > 0.65:
            risk_percent *= 1.2

        if model_learning_confidence < 0.55:
            risk_percent *= 0.85

        risk_percent *= float(basis_policy.get("risk_modifier", 1.0) or 1.0)
        behavior_profile = self.prop_behavior_snapshot(symbol)
        behavior_profile = self.apply_behavior_override(symbol, behavior_profile)
        self.last_prop_behavior[symbol] = behavior_profile
        risk_percent *= float(behavior_profile.get("risk_multiplier", 1.0) or 1.0)
        risk_percent *= float(clawbot_state.get("risk_multiplier", 1.0) or 1.0)
        risk_percent *= float(self.phase_risk_multipliers.get(str(current_phase).upper(), 1.0) or 1.0)

        lot_size = self.risk.calculate_position_size(risk_percent, stop_distance=50)

        intended_price = float(market_data["candles"][-1]["close"])
        planned_tp = intended_price + 50 if best.get("direction") == "BUY" else intended_price - 50
        planned_sl = intended_price - 50 if best.get("direction") == "BUY" else intended_price + 50

        execution_signal = {
            **best,
            "symbol": symbol,
            "entry_price": intended_price,
            "tp": planned_tp,
            "sl": planned_sl,
        }

        self.entry_attempt_lock[symbol] = time.time()
        trade = self.execution.execute(execution_signal, lot_size)
        if trade.get("status") != "EXECUTED":
            self._audit_event("REJECTED_TRADE", "EXECUTION_REJECTED", {
                "symbol": symbol,
                "reason": trade.get("reason"),
                "retry_attempts": trade.get("retry_attempts"),
                "execution_status": trade.get("status"),
                "model": best.get("model"),
                "direction": best.get("direction"),
            })
            return {"status": "Rejected", "symbol": symbol, "reason": trade.get("reason")}

        filled_price = float(trade.get("fill_price") or trade.get("entry_price") or intended_price)
        slippage_ok, slippage_reason = self.slippage_guard.validate(intended_price, filled_price)
        if not slippage_ok:
            self.execution.emergency_halt(f"Offset divergence / slippage breach: {slippage_reason}")
            return {"status": "Blocked", "symbol": symbol, "reason": slippage_reason}

        trade["symbol"] = symbol
        trade["session"] = current_session
        trade["volatility"] = volatility_regime
        trade["volatility_mode"] = self.prop_engine.volatility_mode if self.prop_engine else "NORMAL"
        trade["news_mode"] = mode_now
        trade["rr"] = float(best.get("rr", 0.0) or 0.0)
        trade["confidence"] = float(best.get("confidence", 0.0) or 0.0)
        trade["learning_confidence"] = model_learning_confidence
        trade["entry_reason"] = best.get("entry_reason", "AI-ranked signal selection")
        trade["risk_percent"] = risk_percent
        trade["entry_price"] = intended_price
        trade["tp"] = planned_tp
        trade["sl"] = planned_sl
        trade["governance_snapshot"] = {
            "phase": current_phase,
            "volatility_mode": self.prop_engine.volatility_mode if self.prop_engine else "NORMAL",
            "news_mode": mode_now,
            "cooldown_active": self.prop_engine.cooldown_active if self.prop_engine else False,
            "trading_enabled": self.prop_engine.can_trade() if self.prop_engine else True,
        }
        trade["basis"] = basis_snapshot
        trade["resolver"] = resolver_snapshot
        trade["basis_policy"] = basis_policy
        trade["prop_behavior"] = behavior_profile
        trade["clawbot"] = clawbot_state

        self.journal.log_trade(trade)
        self.positions.add_position(symbol, trade)
        self.cooldowns[symbol] = time.time()
        self.daily_trade_count += 1

        print(f"Executed trade for {symbol}: {trade}")
        return trade

    def start(self):
        self.running = True
        print("Multi-Symbol Engine Started")

        self.warmup_contracts(force_probe=False)

        if not self.montecarlo_checked:
            worst, _ = self.montecarlo.simulate()
            self.state.reduce_risk = worst < -10
            self.montecarlo_checked = True

        now = time.monotonic()
        next_symbol_cycle = now
        next_reconciliation = now
        next_equity_verify = now

        while self.running:
            tick = time.monotonic()

            if tick >= next_equity_verify:
                self.verify_broker_equity()
                next_equity_verify = tick + float(self.equity_verify_interval_seconds)

            if tick >= next_reconciliation:
                self.reconcile_positions()
                next_reconciliation = tick + float(self.reconciliation_interval_seconds)

            if tick >= next_symbol_cycle:
                self.governance.news.check_and_alert(self.telegram)
                for symbol in self.symbols:
                    self.process_symbol(symbol)
                next_symbol_cycle = tick + float(self.symbol_cycle_seconds)

            time.sleep(1)

    def stop(self):
        self.running = False
        self.feed.stop_live()
        print("Multi-Symbol Engine Stopped")

    def get_current_spread(self, symbol):
        # Replace with real broker or feed spread
        return 1.5

    def feed_status(self):
        probe_symbol = self.resolve_active_feed_symbol(self.symbols[0]) if self.symbols else "GC.FUT"
        test = self.feed.test_connection(symbol_dataset(self.symbols[0]) if self.symbols else self.dataset, probe_symbol)
        return {
            "dataset": self.dataset,
            "probe_symbol": probe_symbol,
            **test,
        }
