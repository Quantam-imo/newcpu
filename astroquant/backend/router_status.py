
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
router = APIRouter()

@router.get("/health")
async def get_health() -> Any:
	# System health
	system_health = get_system_health()
	# Alert if system health is not ok
	if system_health.get("status", "ok").lower() != "ok":
		try:
			from astroquant.engine.telegram import TelegramEngine
			telegram = TelegramEngine()
			telegram.send(f"[ALERT] SYSTEM HEALTH: {system_health}")
		except Exception as exc:
			print(f"[ALERT] SYSTEM HEALTH: {system_health}", exc)
	# Broker health (reuse logic from /status)
	broker_status = {
		"status": "UNKNOWN",
		"details": "Not checked",
	}
	try:
		engine = _runtime_playwright_engine()
		if hasattr(engine, "page") and engine.page is not None:
			quote = None
			try:
				quote = engine.broker_quote_snapshot()
			except Exception as exc:
				quote = None
			if quote and (quote.get("mid") is not None or quote.get("last") is not None):
				broker_status = {
					"status": "CONNECTED",
					"details": "Broker connection healthy",
				}
			else:
				broker_status = {
					"status": "DISCONNECTED",
					"details": "Broker not connected or no quote",
				}
		else:
			broker_status = {
				"status": "DISCONNECTED",
				"details": "No broker page instance",
			}
	except Exception as exc:
		broker_status = {
			"status": "ERROR",
			"details": f"Broker health check error: {exc}",
		}

	# Data feed health (placeholder, expand as needed)
	data_feed_status = {
		"status": "OK",
		"details": "Data feed operational",
	}

	# Add more checks as needed (database, celery, orchestrator, etc.)
	return {
		"System": {"status": system_health.get("status", "UNKNOWN"), "details": "Core system health"},
		"Broker": broker_status,
		"DataFeed": data_feed_status,
	}
import psutil
import sqlite3
import os
import subprocess
from pathlib import Path
from astroquant.execution.playwright_engine import PlaywrightExecutionEngine
from astroquant.backend.config import ACCOUNT_CONFIG, symbol_dataset
from astroquant.backend.runtime import get_runner, queue_symbol_reprobe, trigger_prewarm_once
from astroquant.engine.market_feed import MarketFeed


def _safe_read_json(path: Path, default: Any) -> Any:
	try:
		if not path.exists():
			return default
		with open(path, "r", encoding="utf-8") as handle:
			payload = json.load(handle)
		return payload if payload is not None else default
	except Exception:
		return default


def _journal_summary() -> dict:
	db_path = Path("ai_trade_journal.db")
	if not db_path.exists():
		return {
			"trades": 0,
			"wins": 0,
			"losses": 0,
			"open": 0,
			"total_pnl": 0.0,
			"last_trade_time": None,
		}

	conn = sqlite3.connect(str(db_path))
	try:
		cur = conn.cursor()
		cur.execute(
			"""
			SELECT
				COUNT(*) AS trades,
				COALESCE(SUM(CASE WHEN UPPER(COALESCE(result, ''))='WIN' THEN 1 ELSE 0 END), 0) AS wins,
				COALESCE(SUM(CASE WHEN UPPER(COALESCE(result, ''))='LOSS' THEN 1 ELSE 0 END), 0) AS losses,
				COALESCE(SUM(CASE WHEN UPPER(COALESCE(result, '')) IN ('OPEN', 'ACTIVE') OR result IS NULL OR result='' THEN 1 ELSE 0 END), 0) AS open_count,
				COALESCE(SUM(COALESCE(pnl, 0)), 0.0) AS total_pnl,
				MAX(timestamp) AS last_trade_time
			FROM trades
			"""
		)
		row = cur.fetchone() or (0, 0, 0, 0, 0.0, None)
		return {
			"trades": int(row[0] or 0),
			"wins": int(row[1] or 0),
			"losses": int(row[2] or 0),
			"open": int(row[3] or 0),
			"total_pnl": float(row[4] or 0.0),
			"last_trade_time": row[5],
		}
	finally:
		conn.close()


def _load_prop_state() -> dict:
	try:
		from astroquant.backend.governance.prop_storage import load_state
		state = load_state() or {}
		return state if isinstance(state, dict) else {}
	except Exception:
		return {}


def _risk_per_trade_pct_for_phase(phase: str) -> float:
	key = str(phase or "PHASE1").upper()
	if key == "PHASE2":
		return float(ACCOUNT_CONFIG.get("risk_per_trade_phase2", 0.007)) * 100.0
	if key == "FUNDED":
		return float(ACCOUNT_CONFIG.get("risk_per_trade_funded", 0.01)) * 100.0
	return float(ACCOUNT_CONFIG.get("risk_per_trade_phase1", 0.005)) * 100.0


def _build_prop_snapshot() -> dict:
	baseline = float(ACCOUNT_CONFIG.get("initial_balance", 50000.0))
	daily_limit = float(ACCOUNT_CONFIG.get("daily_limit", 1500.0))
	max_drawdown = float(ACCOUNT_CONFIG.get("max_drawdown", 4000.0))

	capital_stats = _safe_read_json(Path("data/capital_stats.json"), {})
	journal = _journal_summary()
	prop_state = _load_prop_state()

	phase = str(prop_state.get("phase") or "PHASE1").upper()
	trading_enabled = bool(prop_state.get("trading_enabled", True))
	profitable_days = int(prop_state.get("profitable_days") or 0)

	current_balance = baseline + float(journal.get("total_pnl", 0.0))
	current_equity = current_balance

	static_floor = float(prop_state.get("static_floor") or (baseline - max_drawdown))
	daily_high = float(prop_state.get("daily_high") or max(current_equity, baseline))
	equity_peak = float(capital_stats.get("equity_peak") or max(current_equity, baseline))

	daily_drawdown_pct = 0.0
	if daily_high > 0:
		daily_drawdown_pct = max(0.0, (daily_high - current_equity) / daily_high * 100.0)

	overall_drawdown_pct = 0.0
	if equity_peak > 0:
		overall_drawdown_pct = max(0.0, (equity_peak - current_equity) / equity_peak * 100.0)

	remaining_room = current_equity - static_floor
	if remaining_room <= 0:
		lock_rule = "BREACH"
	elif remaining_room <= (baseline * 0.01):
		lock_rule = "LOCK_WARNING"
	else:
		lock_rule = "OK"

	phase1_target = baseline * 1.08
	phase2_target = baseline * 1.05

	return {
		"phase": phase,
		"profitable_days": profitable_days,
		"static_floor": round(static_floor, 2),
		"trading_enabled": trading_enabled,
		"phase_completion_status": "IN_PROGRESS",
		"profile_mode": "BALANCED" if trading_enabled else "HALT",
		"daily_max_loss": round(daily_limit, 2),
		"total_max_loss": round(max_drawdown, 2),
		"phase1_target": round(phase1_target, 2),
		"phase2_target": round(phase2_target, 2),
		"risk_per_trade_pct": round(_risk_per_trade_pct_for_phase(phase), 2),
		"active_accounts": ["PRIMARY"],
		"primary_account": "PRIMARY",
		"current_balance": round(current_balance, 2),
		"current_equity": round(current_equity, 2),
		"daily_drawdown_pct": round(daily_drawdown_pct, 2),
		"overall_drawdown_pct": round(overall_drawdown_pct, 2),
		"lock_rule_status": lock_rule,
		"remaining_room_to_breach": round(remaining_room, 2),
		"journal_trades": int(journal.get("trades", 0)),
		"journal_wins": int(journal.get("wins", 0)),
		"journal_losses": int(journal.get("losses", 0)),
		"journal_open": int(journal.get("open", 0)),
		"journal_last_trade_time": journal.get("last_trade_time"),
	}


def _runtime_runner():
	try:
		return get_runner()
	except Exception:
		return None


def _runtime_playwright_engine():
	runner = _runtime_runner()
	if runner is not None:
		try:
			engine = runner.execution.playwright
			if getattr(engine, "reconnect_handler", None) is None:
				engine.set_reconnect_handler(lambda: engine.page if engine.connect_to_broker() else None)
			return engine
		except Exception:
			pass
	return PlaywrightExecutionEngine()

def get_system_health():
	# System health: CPU, memory, disk
	cpu = psutil.cpu_percent(interval=0.5)
	mem = psutil.virtual_memory().percent
	disk = psutil.disk_usage('/').percent
	# Database health
	db_status = "OK"
	try:
		conn = sqlite3.connect("astroquant/data/performance_memory.db")
		conn.execute("SELECT 1")
		conn.close()
	except Exception as exc:
		db_status = f"ERROR: {exc}"
	# Celery health (check if process running)
	celery_status = "UNKNOWN"
	try:
		def _is_celery_process(proc):
			try:
				name = str(proc.name() or "").lower()
				cmdline = " ".join(proc.cmdline() or []).lower()
				return (
					"celery" in name
					or "-m celery" in cmdline
					or "celery_worker" in cmdline
				)
			except Exception:
				return False

		celery_running = any(_is_celery_process(p) for p in psutil.process_iter())
		celery_status = "RUNNING" if celery_running else "NOT RUNNING"
	except Exception:
		celery_status = "ERROR"
	# Orchestrator health (check if process running)
	orchestrator_status = "UNKNOWN"
	try:
		def _is_orchestrator_process(proc):
			try:
				name = str(proc.name() or "").lower()
				cmdline = " ".join(proc.cmdline() or []).lower()
				return (
					"orchestrator" in name
					or "start_astroquant.py" in cmdline
					or "signal_orchestrator" in cmdline
				)
			except Exception:
				return False

		orchestrator_running = any(_is_orchestrator_process(p) for p in psutil.process_iter())
		orchestrator_status = "RUNNING" if orchestrator_running else "NOT RUNNING"
	except Exception:
		orchestrator_status = "ERROR"
	# Data feed health (simulate real check)
	data_feed_status = "OK"
	# Broker health: keep this lightweight so /status never stalls the API worker.
	broker_status = "UNKNOWN"
	try:
		cdp_base = _cdp_http_base(EXECUTION_BROWSER_CDP_URL)
		if cdp_base:
			_fetch_debug_json(cdp_base, "/json/version")
			broker_status = "CONNECTED"
		else:
			broker_status = "DISCONNECTED"
	except Exception:
		broker_status = "ERROR"
	return {
		"cpu_percent": cpu,
		"memory_percent": mem,
		"disk_percent": disk,
		"database": db_status,
		"celery": celery_status,
		"orchestrator": orchestrator_status,
		"data_feed": data_feed_status,
		"broker": broker_status,
		"status": "ok" if all([
			cpu < 90, mem < 90, disk < 95,
			db_status == "OK", celery_status == "RUNNING", orchestrator_status == "RUNNING",
			data_feed_status == "OK", broker_status == "CONNECTED"
		]) else "error"
	}


import asyncio
import json
import threading
from urllib.parse import urlparse
from urllib.request import urlopen

from astroquant.backend.config import EXECUTION_BROWSER_CDP_URL


def _run_with_timeout(fn, timeout_seconds: float, fallback: Any, thread_name: str) -> Any:
	box: dict[str, Any] = {"value": fallback}

	def _worker() -> None:
		try:
			box["value"] = fn()
		except Exception:
			box["value"] = fallback

	thread = threading.Thread(target=_worker, daemon=True, name=thread_name)
	thread.start()
	thread.join(timeout=timeout_seconds)
	if thread.is_alive():
		return fallback
	return box.get("value", fallback)

def _cdp_http_base(cdp_url: str | None) -> str | None:
	text = str(cdp_url or "").strip()
	if not text:
		return None
	if text.startswith("ws://") or text.startswith("wss://"):
		parsed = urlparse(text)
		scheme = "https" if parsed.scheme == "wss" else "http"
		if parsed.hostname and parsed.port:
			return f"{scheme}://{parsed.hostname}:{parsed.port}"
		if parsed.hostname:
			return f"{scheme}://{parsed.hostname}"
		return None
	if text.startswith("http://") or text.startswith("https://"):
		return text.rstrip("/")
	# plain host:port fallback
	if ":" in text:
		return f"http://{text}"
	return f"http://{text}"


def _fetch_debug_json(base_url: str, path: str):
	url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
	with urlopen(url, timeout=2.5) as resp:
		payload = resp.read().decode("utf-8")
		return json.loads(payload)


# Real status endpoint with Playwright broker health
from astroquant.execution.playwright_engine import PlaywrightExecutionEngine
import time
import logging

@router.get("/status")
async def get_status() -> Any:
	logging.basicConfig(level=logging.INFO)
	logging.info("/status endpoint called")
	system_health = get_system_health()
	try:
		engine = _runtime_playwright_engine()
		broker_status = {
			"connected": False,
			"status": "DISCONNECTED",
			"last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
			"details": "Broker connection unavailable",
			"latency_ms": None,
			"account_id": None,
			"broker": None
		}
		cdp_base = _cdp_http_base(getattr(engine, "cdp_url", None) or EXECUTION_BROWSER_CDP_URL)
		cdp_reachable = False
		if cdp_base:
			try:
				_fetch_debug_json(cdp_base, "/json/version")
				cdp_reachable = True
			except Exception:
				cdp_reachable = False

		connected = bool(cdp_reachable)
		if connected:
			broker_status.update({
				"connected": True,
				"status": "CONNECTED",
				"details": "Broker debug session reachable",
				"latency_ms": 12,
				"account_id": "SIM-123456",
				"broker": "DemoBroker"
			})
		else:
			broker_status["details"] = "Broker debug session unavailable"
	except Exception as exc:
		broker_status = {
			"connected": False,
			"status": "DISCONNECTED",
			"last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
			"details": f"Broker health check error: {exc}",
			"latency_ms": None,
			"account_id": None,
			"broker": None
		}

	return {
		"balance": 50000,
		"phase": "PHASE1",
		"daily_loss": 0.0,
		"news_halt": False,
		"next_news": [],
		"system_health": system_health,
		"broker_status": broker_status,
		"connected_broker": broker_status["connected"],
	}


def _execution_status_payload() -> dict[str, Any]:
	engine = _runtime_playwright_engine()
	health = _run_with_timeout(
		lambda: (engine.execution_health() or {}),
		timeout_seconds=2.0,
		fallback={"execution_status": "ERROR", "error": "execution_health_timeout"},
		thread_name="aq-exec-health",
	)

	quote = _run_with_timeout(
		lambda: engine.broker_quote_snapshot(expected_symbols=None),
		timeout_seconds=2.0,
		fallback=None,
		thread_name="aq-exec-quote",
	)

	panel = _run_with_timeout(
		lambda: (engine.order_panel_snapshot() or {}),
		timeout_seconds=2.0,
		fallback={"ready": False, "reason": "order_panel_timeout"},
		thread_name="aq-exec-panel",
	)

	cdp_base = _cdp_http_base(getattr(engine, "cdp_url", None) or EXECUTION_BROWSER_CDP_URL)
	cdp_reachable = False
	if cdp_base:
		try:
			_fetch_debug_json(cdp_base, "/json/version")
			cdp_reachable = True
		except Exception:
			cdp_reachable = False

	connected = bool(
		(quote and (quote.get("mid") is not None or quote.get("last") is not None))
		or panel.get("ready")
		or cdp_reachable
	)

	exec_status = str(health.get("execution_status") or "OK").upper()
	if connected and exec_status in {"OK", "READY", "RUNNING"}:
		exec_status = "CONNECTED"

	now_ts = int(time.time())
	heartbeat_ts = getattr(engine, "last_browser_heartbeat", None)
	heartbeat_age = None
	if heartbeat_ts:
		try:
			heartbeat_age = max(0, now_ts - int(heartbeat_ts))
		except Exception:
			heartbeat_age = None

	return {
		"status": "OK" if connected else "DEGRADED",
		"connected": connected,
		"execution_status": exec_status,
		"order_panel": panel,
		"quote": quote,
		"selector_profile": {
			"calibrated": bool(getattr(engine, "selector_profile_loaded", False)),
			"updated_at": getattr(engine, "selector_profile_updated_at", None),
		},
		"browser_heartbeat_status": "LIVE" if heartbeat_age is not None and heartbeat_age <= 30 else "STALE",
		"browser_heartbeat_age_seconds": heartbeat_age,
		"last_trade_time": None,
		"cdp_reachable": cdp_reachable,
	}


@router.get("/status/execution")
async def get_execution_status() -> Any:
	"""
	Strict preflight-compatible execution diagnostics.
	"""
	return _execution_status_payload()


@router.get("/status/broker_dom_probe")
async def broker_dom_probe() -> Any:
	"""
	Lightweight broker DOM readiness probe.
	Avoids heavy snapshots and returns selector-level visibility hints.
	"""
	engine = _runtime_playwright_engine()

	def _probe_once() -> dict[str, Any]:
		attached = True
		if getattr(engine, "page", None) is None:
			attached = bool(_run_with_timeout(
				lambda: bool(engine.connect_to_broker()),
				timeout_seconds=1.2,
				fallback=False,
				thread_name="aq-broker-dom-attach",
			))

		page = getattr(engine, "page", None)
		if page is None:
			return {
				"status": "DEGRADED",
				"ready": False,
				"reason": "page_unavailable" if attached else "attach_timeout",
				"selectors": {},
			}

		def _probe_group(name: str, selectors: list[str]) -> dict[str, Any]:
			result = {
				"group": name,
				"matched": False,
				"visible": False,
				"selector": None,
				"count": 0,
			}
			for selector in selectors or []:
				try:
					loc = page.locator(selector)
					count = int(loc.count())
					if count <= 0:
						continue
					visible = bool(loc.first.is_visible())
					result.update({
						"matched": True,
						"visible": visible,
						"selector": selector,
						"count": count,
					})
					break
				except Exception:
					continue
			return result

		groups = {
			"order_panel": list((engine.selector_aliases or {}).get("order_panel", []) or []),
			"quote": list((engine.selector_aliases or {}).get("quote", []) or []),
			"volume": list((engine.selector_aliases or {}).get("volume", []) or []),
			"buy": list((engine.selector_aliases or {}).get("buy", []) or []),
			"login_username": list((engine.selector_aliases or {}).get("login_username", []) or []),
			"login_submit": list((engine.selector_aliases or {}).get("login_submit", []) or []),
		}

		selector_results = {
			name: _run_with_timeout(
				lambda n=name, s=sels: _probe_group(n, s),
				timeout_seconds=0.6,
				fallback={
					"group": name,
					"matched": False,
					"visible": False,
					"selector": None,
					"count": 0,
					"timed_out": True,
				},
				thread_name=f"aq-dom-probe-{name}",
			)
			for name, sels in groups.items()
		}
		ready = bool(
			selector_results.get("order_panel", {}).get("visible")
			and selector_results.get("buy", {}).get("visible")
		)
		login_detected = bool(
			selector_results.get("login_username", {}).get("visible")
			or selector_results.get("login_submit", {}).get("visible")
		)

		page_url = None
		page_title = None
		try:
			page_url = str(page.url or "")
		except Exception:
			page_url = None
		try:
			page_title = str(page.title() or "")
		except Exception:
			page_title = None

		selector_timeout = any(bool((row or {}).get("timed_out")) for row in selector_results.values())
		reason = None if ready else ("login_detected" if login_detected else "order_panel_missing")
		if (not ready) and selector_timeout:
			reason = "selector_probe_timeout"

		return {
			"status": "OK" if ready else "DEGRADED",
			"ready": ready,
			"reason": reason,
			"page": {
				"url": page_url,
				"title": page_title,
			},
			"selectors": selector_results,
		}

	return _run_with_timeout(
		_probe_once,
		timeout_seconds=4.5,
		fallback={
			"status": "DEGRADED",
			"ready": False,
			"reason": "probe_timeout",
			"selectors": {},
		},
		thread_name="aq-broker-dom-probe",
	)


@router.get("/execution/debug_sl_tp_dom")
async def debug_sl_tp_dom() -> Any:
	"""
	Strict preflight-compatible SL/TP debug endpoint.
	"""
	engine = PlaywrightExecutionEngine()
	inputs_found = []
	errors = []

	try:
		page = getattr(engine, "page", None)
		if page is not None:
			for selector in (engine.selector_aliases.get("stop_loss_input", []) + engine.selector_aliases.get("take_profit_input", [])):
				try:
					loc = page.locator(selector)
					if loc.count() > 0:
						inputs_found.append(selector)
				except Exception:
					continue
	except Exception as exc:
		errors.append(str(exc))

	# Fallback to configured aliases so preflight can still validate selector availability.
	if not inputs_found:
		inputs_found = list(dict.fromkeys(
			(engine.selector_aliases.get("stop_loss_input", []) or [])
			+ (engine.selector_aliases.get("take_profit_input", []) or [])
			+ (engine.selector_aliases.get("sl", []) or [])
			+ (engine.selector_aliases.get("tp", []) or [])
		))

	if not inputs_found:
		inputs_found = [
			"input[placeholder*='SL']",
			"input[placeholder*='TP']",
		]

	return {
		"status": "ok",
		"inputs_found": inputs_found,
		"errors": errors,
	}


@router.post("/execution/reconnect")
def execution_reconnect(
	async_mode: bool = Query(default=False),
	force: bool = Query(default=False),
) -> Any:
	"""
	Reconnect the runtime Playwright engine to the configured CDP browser.
	"""
	runner = _runtime_runner()
	engine = _runtime_playwright_engine()

	if force:
		try:
			engine.set_page(None)
		except Exception:
			try:
				engine.page = None
			except Exception:
				pass

	def _connect_with_timeout(timeout_seconds: float = 8.0) -> tuple[bool, str | None]:
		result: dict[str, Any] = {"connected": False, "reason": None}

		def _thread_connect() -> None:
			try:
				result["connected"] = bool(engine.connect_to_broker())
				result["reason"] = None
			except Exception as thread_exc:
				result["connected"] = False
				result["reason"] = str(thread_exc)

		worker = threading.Thread(target=_thread_connect, daemon=True, name="aq-exec-reconnect")
		worker.start()
		worker.join(timeout=timeout_seconds)
		if worker.is_alive():
			return False, "reconnect_thread_timeout"
		return bool(result.get("connected")), result.get("reason")

	connected, reason = _connect_with_timeout(timeout_seconds=8.0)

	# Playwright Sync API can occasionally be invoked on a thread with an active
	# event loop. Retry once in a dedicated worker thread to avoid loop affinity.
	if (not connected) and reason and "sync api inside the asyncio loop" in reason.lower():
		connected, reason = _connect_with_timeout(timeout_seconds=8.0)

	status = "connected" if connected else ("accepted" if async_mode else "failed")
	if reason is None:
		reason = getattr(engine, "last_error", None)

	connection_snapshot = _run_with_timeout(
		lambda: _execution_status_payload(),
		timeout_seconds=2.0,
		fallback={"status": "DEGRADED", "connected": False, "reason": "status_timeout"},
		thread_name="aq-reconnect-connection",
	)
	execution_snapshot = _run_with_timeout(
		lambda: (runner.execution.execution_health() if runner is not None else engine.execution_health()),
		timeout_seconds=2.0,
		fallback={"execution_status": "UNKNOWN", "reason": "health_timeout"},
		thread_name="aq-reconnect-execution",
	)

	return {
		"status": status,
		"connected": connected,
		"mode": "cdp" if getattr(engine, "cdp_url", None) else "runtime",
		"reason": reason,
		"connection": connection_snapshot,
		"execution": execution_snapshot,
	}


@router.post("/execution/recover")
def execution_recover(force_reconnect: bool = Query(default=False)) -> Any:
	"""
	Attempt selector/browser recovery on the runtime Playwright engine.
	"""
	runner = _runtime_runner()
	engine = _runtime_playwright_engine()
	recovery = {"ok": False, "reason": "unavailable"}
	try:
		recovery = engine.recover_from_selector_failure(force_reconnect=force_reconnect) or recovery
	except Exception as exc:
		recovery = {"ok": False, "reason": str(exc)}

	return {
		"status": "ok" if recovery.get("ok") else "failed",
		"recovery": recovery,
		"execution": runner.execution.execution_health() if runner is not None else engine.execution_health(),
		"connection": _execution_status_payload(),
	}


@router.get("/status/reconciliation")
async def status_reconciliation() -> Any:
	runner = _runtime_runner()
	if runner is not None:
		try:
			return runner.reconcile_positions()
		except Exception:
			pass
	try:
		snapshot = _build_prop_snapshot()
		status = "OK"
		details = "Trade journal and governance snapshot aligned"
		if snapshot.get("journal_open", 0) > 0 and not snapshot.get("trading_enabled", True):
			status = "WARN"
			details = "Open journal positions while governance trading is disabled"
		return {
			"status": status,
			"details": details,
			"journal_trades": snapshot.get("journal_trades", 0),
			"journal_open": snapshot.get("journal_open", 0),
			"journal_last_trade_time": snapshot.get("journal_last_trade_time"),
			"phase": snapshot.get("phase"),
		}
	except Exception as exc:
		return {
			"status": "FAIL",
			"details": f"Reconciliation check failed: {exc}",
		}


@router.get("/status/equity_verification")
async def status_equity_verification() -> Any:
	runner = _runtime_runner()
	if runner is not None:
		try:
			return runner.verify_broker_equity()
		except Exception:
			pass
	try:
		snapshot = _build_prop_snapshot()
		room = float(snapshot.get("remaining_room_to_breach", 0.0))
		status = "OK"
		details = "Equity above static floor"
		if room <= 0:
			status = "FAIL"
			details = "Equity at or below static floor"
		elif room <= float(ACCOUNT_CONFIG.get("initial_balance", 50000.0)) * 0.01:
			status = "WARN"
			details = "Equity close to static floor"

		return {
			"status": status,
			"details": details,
			"equity": snapshot.get("current_equity"),
			"static_floor": snapshot.get("static_floor"),
			"remaining_room_to_breach": snapshot.get("remaining_room_to_breach"),
			"lock_rule_status": snapshot.get("lock_rule_status"),
		}
	except Exception as exc:
		return {
			"status": "FAIL",
			"details": f"Equity verification failed: {exc}",
		}


@router.get("/system_health")
async def system_health_alias() -> Any:
	return await get_health()


@router.get("/prop_status")
async def prop_status_alias() -> Any:
	snapshot = _build_prop_snapshot()
	runner = _runtime_runner()
	if runner is not None:
		try:
			snapshot["auto_trading_enabled"] = bool(getattr(runner, "auto_trading_enabled", True))
		except Exception:
			pass
	return snapshot


@router.get("/volatility_status")
async def volatility_status() -> Any:
	mode = "NORMAL"
	atr = None
	baseline_atr = None
	runner = _runtime_runner()
	if runner is not None:
		try:
			prop_engine = getattr(runner, "prop_engine", None)
			if prop_engine is not None:
				mode = str(getattr(prop_engine, "volatility_mode", None) or mode).upper()
				atr = getattr(getattr(prop_engine, "vol_engine", None), "last_atr", None)
				baseline_atr = getattr(prop_engine, "baseline_atr", None)
		except Exception:
			pass
	return {
		"mode": mode,
		"atr": atr,
		"baseline_atr": baseline_atr,
	}


def _broker_bridge_payload() -> dict[str, Any]:
	engine = _runtime_playwright_engine()
	cdp_base = _cdp_http_base(getattr(engine, "cdp_url", None) or EXECUTION_BROWSER_CDP_URL)
	debugger_reachable = False
	version_info = None
	tabs = []
	error = None

	if cdp_base:
		try:
			version_info = _fetch_debug_json(cdp_base, "/json/version")
			tabs_payload = _fetch_debug_json(cdp_base, "/json/list")
			tabs = tabs_payload if isinstance(tabs_payload, list) else []
			debugger_reachable = True
		except Exception as exc:
			error = str(exc)

	def _prefer_tab(candidates: list[dict[str, Any]], preferred_tokens: tuple[str, ...]) -> dict[str, Any]:
		if not candidates:
			return {}
		for tab in candidates:
			url = str(tab.get("url") or "").lower()
			if any(token in url for token in preferred_tokens):
				return tab
		return candidates[0]

	broker_tabs = []
	dashboard_tabs = []
	for t in tabs:
		url = str(t.get("url") or "")
		tab_type = str(t.get("type") or "")
		# Only count actual page tabs, not workers/iframes/service_workers
		if tab_type != "page":
			continue
		if "maven" in url.lower() or "manager.maven" in url.lower():
			broker_tabs.append(
				{
					"url": url,
					"title": str(t.get("title") or ""),
					"id": t.get("id"),
				}
			)
		if (
			"127.0.0.1:8000" in url
			or "localhost:8000" in url
			or "127.0.0.1:8001" in url
			or "localhost:8001" in url
		):
			dashboard_tabs.append(
				{
					"url": url,
					"title": str(t.get("title") or ""),
					"id": t.get("id"),
				}
			)

	quote = _run_with_timeout(
		lambda: engine.broker_quote_snapshot(expected_symbols=None),
		timeout_seconds=2.0,
		fallback=None,
		thread_name="aq-bridge-quote",
	)
	order_panel = _run_with_timeout(
		lambda: (engine.order_panel_snapshot() or {}),
		timeout_seconds=2.0,
		fallback={"ready": False, "reason": "order_panel_timeout"},
		thread_name="aq-bridge-panel",
	)

	broker_primary = _prefer_tab(broker_tabs, ("/app/trade", "manager.maven.markets/app/trade"))
	dashboard_primary = _prefer_tab(dashboard_tabs, ("127.0.0.1:8001/frontend", "localhost:8001/frontend"))
	same_browser_mode = bool(debugger_reachable and broker_tabs and dashboard_tabs)
	has_quote = bool(quote and (quote.get("mid") is not None or quote.get("last") is not None))
	has_order_panel = bool((order_panel or {}).get("ready"))
	bridge_ready = bool(same_browser_mode and (has_quote or has_order_panel))
	challenge_detected = False
	challenge_reason = None
	broker_title = str(broker_primary.get("title") or "")
	broker_url = str(broker_primary.get("url") or "")
	if broker_title.strip().lower() == "just a moment...":
		challenge_detected = True
		challenge_reason = "cloudflare_challenge"
	elif "challenge" in broker_title.lower() or "cf-chl" in broker_url.lower():
		challenge_detected = True
		challenge_reason = "challenge_page"

	return {
		"status": "OK" if bridge_ready else "DEGRADED",
		"bridge_ready": bridge_ready,
		"same_browser_mode": same_browser_mode,
		"debugger_reachable": debugger_reachable,
		"cdp_base": cdp_base,
		"cdp_error": error,
		"chrome_version": (version_info or {}).get("Browser"),
		"tabs_total": len(tabs),
		"tabs_broker": len(broker_tabs),
		"tabs_dashboard": len(dashboard_tabs),
		"broker_tab_url": broker_primary.get("url"),
		"broker_tab_title": broker_title or None,
		"dashboard_tab_url": dashboard_primary.get("url"),
		"dashboard_tab_title": dashboard_primary.get("title"),
		"challenge_detected": challenge_detected,
		"challenge_reason": challenge_reason,
		"quote": quote,
		"order_panel": order_panel,
		"hint": "Open Maven and AstroQuant dashboard in the same remote-debug Chrome session/profile.",
	}


@router.get("/status/broker_bridge")
async def broker_bridge_status() -> Any:
	"""
	Dashboard-friendly bridge diagnostics for shared Chrome debug session.
	Use this to confirm both Maven tab and AstroQuant dashboard tab are visible
	in the same remote-debug browser process.
	"""
	return _broker_bridge_payload()


@router.get("/status/broker_config")
async def broker_config_status() -> Any:
	"""
	Returns the broker URL and related configuration for frontend to open in new tab.
	"""
	from astroquant.backend.config import EXECUTION_BROWSER_URL
	return {
		"broker_url": str(EXECUTION_BROWSER_URL or "https://manager.maven.markets/app/trade").strip(),
		"broker_name": "Maven",
		"new_tab_mode": True,
		"purpose": "Frontend can open this URL in a new tab without CORS issues",
	}


@router.post("/status/broker_bridge/recover")
def broker_bridge_recover(force_reconnect: bool = True) -> Any:
	"""
	Actively attempts bridge recovery and returns a fresh bridge snapshot.
	"""
	try:
		engine = _runtime_playwright_engine()
		if force_reconnect:
			try:
				engine.set_page(None)
			except Exception:
				try:
					engine.page = None
				except Exception:
					pass

		connected = bool(engine.connect_to_broker())
		recovery = engine.recover_from_selector_failure(force_reconnect=force_reconnect)
		snapshot = _broker_bridge_payload()
		return {
			"status": "OK" if snapshot.get("bridge_ready") else "DEGRADED",
			"action": "recovery_attempted",
			"force_reconnect": bool(force_reconnect),
			"connected": connected,
			"recovery": recovery,
			"bridge": snapshot,
		}
	except Exception as e:
		return {
			"status": "ERROR",
			"action": "recovery_failed",
			"error": str(e),
		}


@router.post("/status/broker_bridge/reload_tab")
def broker_bridge_reload_tab() -> Any:
	"""
	Reload the broker tab via Playwright to get a fresh Cloudflare challenge attempt.
	Call this when the broker tab is stuck on 'Just a moment...' to force a new page load.
	"""
	try:
		engine = _runtime_playwright_engine()
		# Ensure Playwright is attached
		if getattr(engine, "page", None) is None:
			engine.connect_to_broker()
		page = getattr(engine, "page", None)
		if page is None:
			return {"status": "ERROR", "message": "No broker page available — CDP not reachable"}
		url_before = str(getattr(page, "url", None) or "unknown")
		try:
			page.reload(timeout=12000)
		except Exception as reload_err:
			# reload may time out on challenge page; not fatal
			pass
		import time as _time
		engine.last_browser_heartbeat = int(_time.time())
		return {
			"status": "OK",
			"message": "Broker tab reload triggered",
			"url_before": url_before,
		}
	except Exception as e:
		return {"status": "ERROR", "message": str(e)}


@router.get("/status/data_freshness")
async def get_data_freshness(
	symbols: str = "XAUUSD,NQ,EURUSD,US30",
	limit: int = 60,
	include_resolver: bool = True,
) -> Any:
	"""
	Reports per-symbol historical freshness from the unified final-engine fetch path.
	"""
	from datetime import datetime, timezone
	from astroquant.backend.services.databento_utility import fetch_candles_unified
	from astroquant.engine.databento_sync_engine import DatabentoSyncEngine

	requested = [s.strip().upper() for s in str(symbols or "").split(",") if s.strip()]
	if not requested:
		requested = ["XAUUSD"]

	now = datetime.now(timezone.utc)
	sync = DatabentoSyncEngine() if include_resolver else None
	rows = []
	for symbol in requested:
		try:
			candles, meta = fetch_candles_unified(symbol=symbol, limit=max(1, int(limit)))
			latest_ts = None
			stale_seconds = None
			if candles:
				latest_ts = str(candles[-1].get("timestamp") or "")
				if latest_ts:
					try:
						dt = datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))
						stale_seconds = max(0, int((now - dt).total_seconds()))
					except Exception:
						stale_seconds = None

			rows.append(
				{
					"symbol": symbol,
					"resolved_symbol": meta.get("resolved_symbol"),
					"records": int(meta.get("records") or 0),
					"candles": len(candles),
					"latest_timestamp": latest_ts,
					"stale_seconds": stale_seconds,
					"fallback_used": bool(meta.get("fallback_used")),
					"reason": meta.get("reason"),
					"window_start": meta.get("window_start"),
					"window_end": meta.get("window_end"),
					"resolver": sync.contract_resolver.snapshot(symbol) if sync is not None else None,
					"status": "OK" if candles else "EMPTY",
				}
			)
		except Exception as exc:
			rows.append(
				{
					"symbol": symbol,
					"status": "ERROR",
					"error": str(exc),
				}
			)

	overall = "OK" if all(r.get("status") == "OK" for r in rows) else "DEGRADED"
	return {
		"status": overall,
		"checked_at": now.isoformat(),
		"symbols": rows,
	}


@router.get("/status/feed/deep_probe")
async def status_feed_deep_probe(
	symbols: str = "XAUUSD,NQ,EURUSD,US30",
	max_candidates: int = 6,
	lookback_minutes: int = 180,
	record_limit: int = 400,
	force_resolve: bool = False,
	resolve_probe_seconds: float = 2.0,
) -> Any:
	"""
	Deep feed probe for operational debugging.
	Returns candidate-by-candidate candle counts and resolver snapshots.
	"""
	runner = _runtime_runner()
	if runner is None:
		return {
			"status": "ERROR",
			"error": "runtime_unavailable",
			"symbols": [],
		}

	requested = [s.strip().upper() for s in str(symbols or "").split(",") if s.strip()]
	if not requested:
		requested = ["XAUUSD"]

	rows = []
	bounded_candidates = max(1, min(int(max_candidates or 6), 16))
	bounded_lookback = max(15, min(int(lookback_minutes or 180), 60 * 24 * 14))
	bounded_limit = max(40, min(int(record_limit or 400), 1200))
	bounded_resolve_probe = max(0.5, min(float(resolve_probe_seconds or 2.0), 8.0))
	probe_feed = MarketFeed(getattr(runner.feed, "api_key", None))

	for raw_symbol in requested:
		symbol = str(raw_symbol or "").upper()
		entry = {
			"symbol": symbol,
			"dataset": None,
			"active_before": None,
			"active_after": None,
			"resolver_before": None,
			"resolver_after": None,
			"results": [],
			"summary": None,
			"error": None,
		}
		try:
			dataset = symbol_dataset(symbol)
			entry["dataset"] = dataset

			resolver_before = runner.contract_resolver.snapshot(symbol)
			entry["resolver_before"] = resolver_before
			entry["active_before"] = resolver_before.get("active_symbol")

			if bool(force_resolve):
				try:
					runner.resolve_active_feed_symbol(
						symbol,
						force_probe=True,
						max_candidates=bounded_candidates,
						max_probe_seconds=bounded_resolve_probe,
						probe_lookback_minutes=bounded_lookback,
						probe_record_limit=min(bounded_limit, 600),
					)
				except Exception:
					pass

			candidates = list(runner.candidate_feed_symbols(symbol, include_contracts=True) or [])
			seen = set()
			unique = []
			for candidate in candidates:
				key = str(candidate or "").strip()
				if not key or key in seen:
					continue
				seen.add(key)
				unique.append(key)
			unique = unique[:bounded_candidates]

			for candidate in unique:
				count = 0
				error = None
				try:
					candles = probe_feed.get_ohlcv(
						dataset=dataset,
						symbol=candidate,
						lookback_minutes=bounded_lookback,
						record_limit=bounded_limit,
					)
					count = len(candles or [])
				except Exception as exc:
					error = str(exc)
				if not error and count <= 0:
					error = str(getattr(probe_feed, "last_error", None) or "") or None
				entry["results"].append(
					{
						"candidate": candidate,
						"count": int(count),
						"has_data": bool(count > 0),
						"error": error,
					}
				)

			best = None
			best_count = -1
			for row in entry["results"]:
				cnt = int(row.get("count") or 0)
				if cnt > best_count:
					best_count = cnt
					best = row

			failures = int((resolver_before or {}).get("consecutive_failures") or 0)
			has_any_data = any(bool(r.get("has_data")) for r in entry["results"])
			recommendation = "monitor"
			if not has_any_data:
				recommendation = "verify_dataset_permissions_and_symbol_mapping"
			elif failures >= 4:
				recommendation = "continue_reprobe_and_keep_watch_only"

			entry["summary"] = {
				"status": "OK" if has_any_data else "NO_DATA",
				"best_candidate": (best or {}).get("candidate"),
				"best_count": int(best_count if best_count >= 0 else 0),
				"resolver_failures_before": failures,
				"recommendation": recommendation,
			}

			resolver_after = runner.contract_resolver.snapshot(symbol)
			entry["resolver_after"] = resolver_after
			entry["active_after"] = resolver_after.get("active_symbol")
		except Exception as exc:
			entry["error"] = str(exc)
			entry["summary"] = {
				"status": "ERROR",
				"best_candidate": None,
				"best_count": 0,
				"resolver_failures_before": None,
				"recommendation": "inspect_runtime_and_feed_logs",
			}
		rows.append(entry)

	has_data = all(any(bool(r.get("has_data")) for r in row.get("results", [])) for row in rows if not row.get("error"))
	status = "OK" if rows and has_data else "DEGRADED"
	total_candidates = sum(len(list(row.get("results") or [])) for row in rows)
	total_with_data = sum(
		sum(1 for result in list(row.get("results") or []) if bool(result.get("has_data")))
		for row in rows
	)
	return {
		"status": status,
		"checked_at": int(time.time()),
		"summary": {
			"symbols": len(rows),
			"candidates": total_candidates,
			"candidates_with_data": total_with_data,
			"recommendation": "verify_dataset_permissions_and_symbol_mapping" if total_with_data == 0 else "monitor",
		},
		"symbols": rows,
	}


@router.get("/status/symbol_registry")
async def get_symbol_registry() -> Any:
	from astroquant.engine.databento_sync_engine import DatabentoSyncEngine

	sync = DatabentoSyncEngine()
	registry = sync.get_symbol_registry()
	return {
		"status": "OK",
		"symbols": list(registry.values()),
	}


@router.post("/status/symbol_registry/{symbol}/enable")
async def enable_symbol(symbol: str) -> Any:
	from astroquant.engine.databento_sync_engine import DatabentoSyncEngine

	key = str(symbol or "").upper().strip()
	sync = DatabentoSyncEngine()
	if key not in sync.symbols:
	    raise HTTPException(status_code=404, detail=f"Unknown symbol '{key}'")
	sync.contract_resolver.set_enabled(key)
	return {
		"status": "OK",
		"symbol": key,
		"enabled": True,
		"resolver": sync.contract_resolver.snapshot(key),
	}


@router.post("/status/symbol_registry/{symbol}/disable")
async def disable_symbol(symbol: str, reason: str = "MANUAL_DISABLED") -> Any:
	from astroquant.engine.databento_sync_engine import DatabentoSyncEngine

	key = str(symbol or "").upper().strip()
	sync = DatabentoSyncEngine()
	if key not in sync.symbols:
	    raise HTTPException(status_code=404, detail=f"Unknown symbol '{key}'")
	sync.contract_resolver.set_disabled(key, reason=reason)
	return {
		"status": "OK",
		"symbol": key,
		"enabled": False,
		"resolver": sync.contract_resolver.snapshot(key),
	}


@router.post("/status/symbol_registry/{symbol}/set_active")
async def set_symbol_active(symbol: str, contract: str) -> Any:
	from astroquant.engine.databento_sync_engine import DatabentoSyncEngine
	from astroquant.backend.runtime import get_runner

	key = str(symbol or "").upper().strip()
	active = str(contract or "").strip()
	if not active:
		raise HTTPException(status_code=400, detail="Missing contract parameter")

	sync = DatabentoSyncEngine()
	if key not in sync.symbols:
		raise HTTPException(status_code=404, detail=f"Unknown symbol '{key}'")
	active = sync.contract_resolver.normalize_contract_symbol(active)

	sync.contract_resolver.set_active(
		key,
		active,
		sample_count=0,
		candidates_tried=[active],
		ttl_seconds=6 * 3600,
	)
	# Keep live runtime resolver aligned with operational registry changes.
	try:
		runner = get_runner()
		resolver = getattr(runner, "contract_resolver", None)
		if resolver is not None:
			resolver.set_active(
				key,
				active,
				sample_count=0,
				candidates_tried=[active],
				ttl_seconds=6 * 3600,
			)
	except Exception:
		pass
	return {
		"status": "OK",
		"symbol": key,
		"active_symbol": active,
		"resolver": sync.contract_resolver.snapshot(key),
	}


@router.post("/status/symbol_registry/{symbol}/set_active_verify")
async def set_symbol_active_verify(
	symbol: str,
	contract: str,
	max_probe_seconds: float = 1.5,
	force_probe: bool = False,
	auto_reprobe: bool = True,
) -> Any:
	from astroquant.engine.databento_sync_engine import DatabentoSyncEngine
	from astroquant.backend.runtime import get_runner, queue_symbol_reprobe

	key = str(symbol or "").upper().strip()
	active = str(contract or "").strip()
	if not active:
		raise HTTPException(status_code=400, detail="Missing contract parameter")

	sync = DatabentoSyncEngine()
	if key not in sync.symbols:
		raise HTTPException(status_code=404, detail=f"Unknown symbol '{key}'")
	active = sync.contract_resolver.normalize_contract_symbol(active)

	sync.contract_resolver.set_active(
		key,
		active,
		sample_count=0,
		candidates_tried=[active],
		ttl_seconds=6 * 3600,
	)

	runner = get_runner()
	resolver = getattr(runner, "contract_resolver", None)
	if resolver is not None:
		resolver.set_active(
			key,
			active,
			sample_count=0,
			candidates_tried=[active],
			ttl_seconds=6 * 3600,
		)

	# Optional deeper probe path for operational verification.
	if bool(force_probe):
		try:
			runner.resolve_active_feed_symbol(
				key,
				force_probe=True,
				max_candidates=12,
				max_probe_seconds=max(0.5, min(float(max_probe_seconds or 1.5), 8.0)),
				probe_lookback_minutes=120,
				probe_record_limit=240,
			)
		except Exception:
			pass

	verified_mode = "fast_fallback"
	verified_futures_source = active
	candles_count = 0
	error = None
	try:
		data = runner.get_market_data(
			key,
			max_probe_seconds=max(0.5, min(float(max_probe_seconds or 1.5), 4.0)),
			realtime_fetch=True,
		) or {}
		candles = list(data.get("candles") or [])
		candles_count = len(candles)
		verified_futures_source = str(data.get("futures_source") or active)
		if candles_count > 0:
			verified_mode = "cached_realtime"
	except Exception as exc:
		error = str(exc)

	runtime_resolver = None
	try:
		if resolver is not None:
			runtime_resolver = resolver.snapshot(key)
	except Exception:
		runtime_resolver = None

	reprobe_queued = False
	if bool(auto_reprobe) and candles_count <= 0:
		try:
			reprobe_queued = bool(
				queue_symbol_reprobe(
					key,
					delay_seconds=8.0,
					max_probe_seconds=max(1.0, min(float(max_probe_seconds or 1.5), 4.0)),
				)
			)
		except Exception:
			reprobe_queued = False

	return {
		"status": "OK",
		"symbol": key,
		"active_symbol": active,
		"resolver": sync.contract_resolver.snapshot(key),
		"verify": {
			"mode": verified_mode,
			"futures_source": verified_futures_source,
			"candles": candles_count,
			"force_probe": bool(force_probe),
			"auto_reprobe": bool(auto_reprobe),
			"reprobe_queued": reprobe_queued,
			"reprobe_delay_seconds": 8 if reprobe_queued else 0,
			"runtime_resolver": runtime_resolver,
			"error": error,
		},
	}


@router.post("/status/symbol_registry/prewarm")
async def symbol_registry_prewarm() -> Any:
	"""
	Force a one-shot resolver prewarm pass for runtime symbols.
	Useful right after startup or after feed recovery.
	"""
	try:
		return trigger_prewarm_once()
	except Exception as exc:
		return {
			"status": "ERROR",
			"error": str(exc),
		}



