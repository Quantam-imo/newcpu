from __future__ import annotations

import threading
import time

from astroquant.backend.config import (
	EXECUTION_LOGIN_PASSWORD,
	EXECUTION_LOGIN_USERNAME,
	RUNTIME_SYMBOLS as _CONFIG_RUNTIME_SYMBOLS,
)
from astroquant.engine.multi_symbol_runner import MultiSymbolRunner


# Mutable list so new symbols can be registered at runtime without restart.
RUNTIME_SYMBOLS: list[str] = list(_CONFIG_RUNTIME_SYMBOLS)
ALLOWED_RUNTIME_SYMBOLS: set[str] = set(_CONFIG_RUNTIME_SYMBOLS)
_runtime_symbols_lock = threading.Lock()


def register_symbol(symbol: str) -> bool:
	"""Add a new symbol to the runtime universe and auto-prewarm it.

	Returns True if the symbol was newly added, False if it was already present.
	The symbol will immediately begin contract resolution and broker spot cache
	refresh cycles — no restart required.
	"""
	key = str(symbol or "").strip().upper()
	if not key:
		return False
	if key not in ALLOWED_RUNTIME_SYMBOLS:
		return False
	with _runtime_symbols_lock:
		if key in RUNTIME_SYMBOLS:
			return False
		RUNTIME_SYMBOLS.append(key)

	# Bootstrap the runner's per-symbol state for the new entry.
	try:
		runner = get_runner()
		if key not in runner.symbols:
			runner.symbols.append(key)
		import collections
		if key not in runner.spot_tick_history:
			runner.spot_tick_history[key] = collections.deque(maxlen=600)
		if key not in runner.offset_smooth_window:
			runner.offset_smooth_window[key] = collections.deque(maxlen=20)
		# Trigger an immediate contract probe so the symbol is live quickly.
		threading.Thread(
			target=lambda: runner.resolve_active_feed_symbol(
				key, force_probe=True, max_candidates=8, max_probe_seconds=5.0,
				probe_lookback_minutes=120, probe_record_limit=200,
			),
			daemon=True,
			name=f"aq-register-{key}",
		).start()
	except Exception:
		pass
	return True

_runner_lock = threading.Lock()
_runner: MultiSymbolRunner | None = None
_prewarm_thread_started = False


_FUTURES_TO_CANONICAL = {
	"GC.FUT": "XAUUSD",
	"NQ.FUT": "NQ",
	"6E.FUT": "EURUSD",
	"YM.FUT": "US30",
	"GC": "XAUUSD",
	"GC-F": "XAUUSD",
	"YM": "US30",
}


def normalize_runtime_symbol(symbol: str) -> str:
	key = str(symbol or "").strip().upper()
	return _FUTURES_TO_CANONICAL.get(key, key or "XAUUSD")


def _prime_execution_connection(runner: MultiSymbolRunner) -> None:
	try:
		engine = runner.execution.playwright
		engine.set_reconnect_handler(lambda: engine.page if engine.connect_to_broker() else None)
		if engine.connect_to_broker():
			# If session is logged out after restart, attempt credentials-based login.
			engine.login_if_needed(
				username=EXECUTION_LOGIN_USERNAME,
				password=EXECUTION_LOGIN_PASSWORD,
			)
	except Exception:
		pass


def _prewarm_contract_cache_once(runner: MultiSymbolRunner) -> None:
	# Keep probe budgets tight for the baseline pass.
	try:
		warmed = runner.warmup_contracts(force_probe=False, max_candidates=2, max_probe_seconds=1.5)
	except Exception:
		return

	# Follow with deeper probes only for symbols still unresolved.
	for symbol, row in dict(warmed or {}).items():
		try:
			resolver = (row or {}).get("resolver") or {}
			active = resolver.get("active_symbol")
			status = str(resolver.get("last_status") or "").upper()
			if active and status in {"LIVE", "OK"}:
				continue
			runner.resolve_active_feed_symbol(
				symbol,
				force_probe=True,
				max_candidates=10,
				max_probe_seconds=5.0,
				probe_lookback_minutes=90,
				probe_record_limit=180,
			)
		except Exception:
			continue


def _start_prewarm_loop(runner: MultiSymbolRunner) -> None:
	global _prewarm_thread_started
	if _prewarm_thread_started:
		return
	_prewarm_thread_started = True

	def _loop():
		# First run immediately after startup, then periodic refresh.
		_prewarm_contract_cache_once(runner)
		while True:
			time.sleep(300)
			_prewarm_contract_cache_once(runner)

	threading.Thread(target=_loop, daemon=True, name="aq-runtime-prewarm").start()


_broker_watchdog_started = False


def _start_broker_watchdog(runner: MultiSymbolRunner) -> None:
	"""Periodic watchdog: re-attaches Playwright to broker when heartbeat goes stale.

	This allows the bridge to auto-recover once a Cloudflare challenge clears
	or after a brief network drop, without requiring manual intervention.
	"""
	global _broker_watchdog_started
	if _broker_watchdog_started:
		return
	_broker_watchdog_started = True

	def _try_connect(engine) -> bool:
		if engine.connect_to_broker():
			engine.login_if_needed(
				username=EXECUTION_LOGIN_USERNAME,
				password=EXECUTION_LOGIN_PASSWORD,
			)
			return True
		return False

	def _loop():
		# Fast-startup phase: retry every 5 s for up to 90 s so that if
		# Chrome starts after the backend we connect within seconds rather
		# than waiting the full 30-second normal interval.
		startup_deadline = time.time() + 90
		while time.time() < startup_deadline:
			time.sleep(5)
			try:
				engine = runner.execution.playwright
				last_hb = getattr(engine, "last_browser_heartbeat", None)
				if last_hb is None:
					if _try_connect(engine):
						break  # Connected — fall through to normal loop
			except Exception:
				pass

		# Normal watchdog loop: reconnect whenever heartbeat goes stale.
		while True:
			time.sleep(30)
			try:
				engine = runner.execution.playwright
				now = int(time.time())
				last_hb = getattr(engine, "last_browser_heartbeat", None)
				# Re-attach if heartbeat is stale (>60 s) or never set
				if last_hb is None or (now - int(last_hb)) > 60:
					_try_connect(engine)
			except Exception:
				pass

	threading.Thread(target=_loop, daemon=True, name="aq-broker-watchdog").start()


def get_runner() -> MultiSymbolRunner:
	global _runner
	with _runner_lock:
		if _runner is None:
			_runner = MultiSymbolRunner(RUNTIME_SYMBOLS)
			_prime_execution_connection(_runner)
			_start_prewarm_loop(_runner)
			_start_broker_watchdog(_runner)
		return _runner


def trigger_prewarm_once() -> dict:
	runner = get_runner()
	_prewarm_contract_cache_once(runner)
	resolver = getattr(runner, "contract_resolver", None)
	if resolver is None:
		return {
			"status": "OK",
			"resolver": {},
			"summary": {
				"symbols": len(RUNTIME_SYMBOLS),
				"resolved": 0,
				"unresolved": len(RUNTIME_SYMBOLS),
			},
		}

	rows = {}
	resolved = 0
	for symbol in RUNTIME_SYMBOLS:
		try:
			snapshot = resolver.snapshot(symbol)
			rows[symbol] = snapshot
			if snapshot.get("active_symbol") and str(snapshot.get("last_status") or "").upper() in {"LIVE", "OK"}:
				resolved += 1
		except Exception:
			rows[symbol] = {"symbol": symbol, "status": "UNKNOWN"}
	return {
		"status": "OK",
		"resolver": rows,
		"summary": {
			"symbols": len(RUNTIME_SYMBOLS),
			"resolved": resolved,
			"unresolved": max(0, len(RUNTIME_SYMBOLS) - resolved),
		},
	}


def queue_symbol_reprobe(symbol: str, delay_seconds: float = 8.0, max_probe_seconds: float = 2.5) -> bool:
	"""
	Queue a one-shot background force probe for a specific runtime symbol.
	Used as a low-cost recovery nudge after manual pin operations.
	"""
	raw_key = str(symbol or "").strip().upper()
	key = raw_key if raw_key in RUNTIME_SYMBOLS else normalize_runtime_symbol(raw_key)
	if key not in RUNTIME_SYMBOLS:
		return False

	runner = get_runner()
	delay = max(0.0, min(float(delay_seconds or 0.0), 30.0))
	probe_budget = max(0.5, min(float(max_probe_seconds or 2.5), 8.0))

	def _reprobe_once() -> None:
		if delay > 0:
			time.sleep(delay)
		try:
			runner.resolve_active_feed_symbol(
				key,
				force_probe=True,
				max_candidates=10,
				max_probe_seconds=probe_budget,
				probe_lookback_minutes=120,
				probe_record_limit=220,
			)
		except Exception:
			pass

	threading.Thread(target=_reprobe_once, daemon=True, name=f"aq-reprobe-{key.lower()}").start()
	return True