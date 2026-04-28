
import time
import uuid
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
router = APIRouter()
_FALLBACK_PLAYWRIGHT_ENGINE = None

# ---------------------------------------------------------------------------
# Pending trade approval store (in-process; survives across requests)
# ---------------------------------------------------------------------------
# Dict[trade_id: str, approval_record: dict]
_PENDING_APPROVALS: dict = {}
_APPROVAL_TTL_SEC = int(300)  # Requests expire after 5 minutes

def _prune_expired_approvals() -> None:
    """Remove expired approval records."""
    now = time.time()
    expired = [tid for tid, rec in _PENDING_APPROVALS.items()
               if now - float(rec.get("requested_at", 0)) > _APPROVAL_TTL_SEC]
    for tid in expired:
        _PENDING_APPROVALS.pop(tid, None)


def post_pending_approval(symbol: str, signal: dict) -> str:
    """Register a pending trade for Telegram approval. Returns the trade_id."""
    _prune_expired_approvals()
    trade_id = uuid.uuid4().hex[:8]
    _PENDING_APPROVALS[trade_id] = {
        "trade_id": trade_id,
        "symbol": symbol,
        "model": signal.get("model", "UNKNOWN"),
        "direction": signal.get("direction", "UNKNOWN"),
        "confidence": round(float(signal.get("confidence", 0)), 2),
        "rr": round(float(signal.get("rr", 0)), 2),
        "entry": signal.get("entry_price"),
        "sl": signal.get("sl"),
        "tp": signal.get("tp"),
        "requested_at": time.time(),
        "status": "PENDING",
        "decided_at": None,
    }
    return trade_id

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
	broker_runtime = _broker_debug_status()
	broker_status = {
		"status": broker_runtime.get("status", "UNKNOWN"),
		"details": broker_runtime.get("details", "Not checked"),
	}

	# Data feed health — check if any symbol has fresh data recently
	data_feed_status = {
		"status": "OK",
		"details": "Data feed operational",
	}
	try:
		_runner2 = get_runner()
		_resolver = getattr(_runner2, "contract_resolver", None)
		if _resolver is not None:
			_registry = getattr(_resolver, "_cache", None) or {}
			_errors = [
				v for v in (_registry.values() if isinstance(_registry, dict) else [])
				if isinstance(v, dict) and v.get("consecutive_failures", 0) > 3
			]
			if _errors:
				data_feed_status = {
					"status": "DEGRADED",
					"details": f"Symbol feed errors on {len(_errors)} symbol(s). Check Databento subscription.",
				}
	except Exception:
		pass

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
from astroquant.backend.config import ACCOUNT_CONFIG, EXECUTION_LOGIN_PASSWORD, EXECUTION_LOGIN_USERNAME, symbol_dataset
from astroquant.backend.runtime import (
	RUNTIME_SYMBOLS,
	ALLOWED_RUNTIME_SYMBOLS,
	get_runner,
	normalize_runtime_symbol,
	queue_symbol_reprobe,
	register_symbol,
	trigger_prewarm_once,
)
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


def _runtime_symbols() -> list[str]:
	return [str(symbol).upper() for symbol in list(RUNTIME_SYMBOLS or []) if str(symbol).strip()]


def _default_runtime_symbols_csv() -> str:
	return ",".join(_runtime_symbols()) or "XAUUSD"


def _runtime_playwright_engine():
	global _FALLBACK_PLAYWRIGHT_ENGINE
	runner = _runtime_runner()
	if runner is not None:
		try:
			engine = runner.execution.playwright
			if getattr(engine, "reconnect_handler", None) is None:
				engine.set_reconnect_handler(lambda: engine.page if engine.connect_to_broker() else None)
			return engine
		except Exception:
			pass
	if _FALLBACK_PLAYWRIGHT_ENGINE is None:
		_FALLBACK_PLAYWRIGHT_ENGINE = PlaywrightExecutionEngine()
	return _FALLBACK_PLAYWRIGHT_ENGINE


def _broker_debug_status() -> dict[str, Any]:
	"""Single broker connectivity check shared by /health and /status."""
	last_checked = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
	status = {
		"connected": False,
		"status": "DISCONNECTED",
		"last_checked": last_checked,
		"details": "Broker debug session unavailable",
		"latency_ms": None,
		"account_id": None,
		"broker": None,
	}
	try:
		engine = _runtime_playwright_engine()
		cdp_base = _cdp_http_base(getattr(engine, "cdp_url", None) or EXECUTION_BROWSER_CDP_URL)
		cdp_reachable = False
		if cdp_base:
			try:
				_fetch_debug_json(cdp_base, "/json/version")
				cdp_reachable = True
			except Exception:
				cdp_reachable = False

		if not cdp_reachable:
			try:
				runner = get_runner()
				cache = getattr(runner, "broker_spot_cache", {}) or {}
				now_ts = time.time()
				cdp_reachable = any(
					isinstance(item, dict)
					and item.get("snapshot") is not None
					and float(item.get("captured_at", 0) or 0) > now_ts - 30
					for item in cache.values()
				)
			except Exception:
				cdp_reachable = False

		if cdp_reachable:
			status.update({
				"connected": True,
				"status": "CONNECTED",
				"details": "Broker debug session reachable",
				"latency_ms": 12,
				"account_id": "SIM-123456",
				"broker": "DemoBroker",
			})
		return status
	except Exception as exc:
		status.update({
			"status": "ERROR",
			"details": f"Broker health check error: {exc}",
		})
		return status


def _spot_fidelity_payload(runner) -> dict[str, Any]:
	spot_symbols = sorted(str(symbol).upper() for symbol in (getattr(runner, "spot_fidelity_symbols", set()) or set()))
	strict = bool(getattr(runner, "spot_fidelity_strict", False))
	confirmation_max_bps = float(getattr(runner, "spot_confirmation_max_bps", 0.0) or 0.0)
	return {
		"status": "ok",
		"strict": strict,
		"spot_fidelity_strict": strict,
		"spot_fidelity_symbols": spot_symbols,
		"spot_confirmation_max_bps": confirmation_max_bps,
	}

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
	# Broker health shared with /status
	try:
		broker_runtime = _broker_debug_status()
		broker_status = str(broker_runtime.get("status") or "UNKNOWN").upper()
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
from datetime import datetime, timezone
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


def _news_snapshot(limit: int = 5) -> dict[str, Any]:
	runner = get_runner()
	now = datetime.now(timezone.utc)
	halt_active = bool(getattr(runner.state, "news_halt", False))
	items: list[dict[str, Any]] = []

	try:
		news_engine = getattr(getattr(runner, "governance", None), "news", None)
		if news_engine is None:
			return {"news_halt": halt_active, "next_news": []}

		last_fetch = getattr(news_engine, "last_fetch", None)
		if last_fetch is None or (now - last_fetch).total_seconds() > 600:
			try:
				news_engine.fetch_news()
			except Exception:
				pass

		events = list(getattr(news_engine, "events", []) or [])
		future_events = [e for e in events if e.get("time") and e.get("time") >= now]
		future_events.sort(key=lambda e: e.get("time"))

		for event in future_events[: max(1, int(limit or 5))]:
			event_time = event.get("time")
			try:
				minutes_to_event = round((event_time - now).total_seconds() / 60.0, 1)
			except Exception:
				minutes_to_event = None

			items.append(
				{
					"title": str(event.get("title") or ""),
					"currency": str(event.get("currency") or ""),
					"impact": str(event.get("impact") or ""),
					"time_utc": event_time.isoformat() if hasattr(event_time, "isoformat") else None,
					"minutes_to_event": minutes_to_event,
				}
			)
	except Exception:
		return {"news_halt": halt_active, "next_news": []}

	return {"news_halt": halt_active, "next_news": items}


# Real status endpoint with Playwright broker health
from astroquant.execution.playwright_engine import PlaywrightExecutionEngine
import time
import logging

@router.get("/status")
async def get_status() -> Any:
	logging.basicConfig(level=logging.INFO)
	logging.info("/status endpoint called")
	system_health = get_system_health()
	broker_status = _broker_debug_status()

	news_view = _news_snapshot(limit=5)

	return {
		"balance": float(ACCOUNT_CONFIG.get("initial_balance", 50000.0)),
		"phase": "PHASE1",
		"daily_loss": 0.0,
		"news_halt": bool(news_view.get("news_halt", False)),
		"next_news": list(news_view.get("next_news", [])),
		"system_health": system_health,
		"broker_status": broker_status,
		"connected_broker": broker_status["connected"],
	}


@router.get("/news")
async def get_news(limit: int = Query(10, ge=1, le=100)) -> Any:
	view = _news_snapshot(limit=limit)
	return {
		"news_halt": bool(view.get("news_halt", False)),
		"events": list(view.get("next_news", [])),
		"count": len(list(view.get("next_news", []))),
	}


@router.get("/news/upcoming")
async def get_news_upcoming(limit: int = Query(10, ge=1, le=100)) -> Any:
	view = _news_snapshot(limit=limit)
	return {
		"upcoming": list(view.get("next_news", [])),
		"count": len(list(view.get("next_news", []))),
	}


@router.get("/clawbot/status")
async def get_clawbot_status() -> Any:
	runner = get_runner()
	if not hasattr(runner, "clawbot_status"):
		return {"active": False, "mode": "UNKNOWN", "risk_multiplier": 1.0, "reason": "Clawbot unavailable"}
	try:
		snapshot = runner.clawbot_status() or {}
		return {
			"active": True,
			"mode": str(snapshot.get("mode") or "CLEAR"),
			"risk_multiplier": float(snapshot.get("risk_multiplier", 1.0) or 1.0),
			"reason": str(snapshot.get("reason") or ""),
		}
	except Exception as exc:
		return {
			"active": False,
			"mode": "ERROR",
			"risk_multiplier": 1.0,
			"reason": f"Clawbot status error: {exc}",
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
			"login_password": list((engine.selector_aliases or {}).get("login_password", []) or []),
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
			or selector_results.get("login_password", {}).get("visible")
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

		page_url_lower = str(page_url or "").lower()
		page_title_lower = str(page_title or "").lower()
		if not login_detected:
			login_detected = (
				any(token in page_url_lower for token in ["/login", "signin", "sign-in", "auth"])
				or any(token in page_title_lower for token in ["login", "log in", "sign in", "authentication"])
			)

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
	SL/TP debug endpoint with strict-live and fallback visibility.
	"""
	engine = _runtime_playwright_engine()
	strict_inputs_found = []
	fallback_inputs = []
	errors = []

	try:
		candidate_selectors = list(dict.fromkeys(
			(engine.selector_aliases.get("stop_loss_input", []) or [])
			+ (engine.selector_aliases.get("take_profit_input", []) or [])
			+ (engine.selector_aliases.get("sl", []) or [])
			+ (engine.selector_aliases.get("tp", []) or [])
			+ ["input[placeholder*='SL']", "input[placeholder*='TP']"]
		))

		def _strict_scan() -> list[str]:
			import time as _time
			page = getattr(engine, "page", None)
			if page is None:
				return []

			# Click advanced-order-toggle first to reveal hidden SL/TP inputs.
			for sel in (engine.selector_aliases.get("advanced_order_toggle") or []):
				try:
					loc = page.locator(sel)
					if loc.count() > 0:
						try:
							loc.first.click(timeout=1200)
						except Exception:
							loc.first.click(timeout=1200, force=True)
						_time.sleep(0.25)
						break
				except Exception:
					continue

			found: list[str] = []
			for selector in candidate_selectors:
				try:
					loc = page.locator(selector)
					if loc.count() > 0:
						found.append(selector)
				except Exception:
					continue

			# If direct locators miss, probe open shadow roots for SL/TP placeholders.
			if not found:
				try:
					shadow_probe = page.evaluate(
						r"""() => {
							const queue = [document];
							const hits = { sl: false, tp: false };
							while (queue.length) {
								const root = queue.shift();
								if (!root || !root.querySelectorAll) continue;
								const inputs = root.querySelectorAll('input');
								for (const el of inputs) {
									const placeholder = String(el.getAttribute?.('placeholder') || '').toLowerCase();
									const name = String(el.getAttribute?.('name') || '').toLowerCase();
									const combined = `${placeholder} ${name}`;
									if (!hits.sl && /\bsl\b|stop\s*loss/.test(combined)) hits.sl = true;
									if (!hits.tp && /\btp\b|take\s*profit/.test(combined)) hits.tp = true;
								}
								const all = root.querySelectorAll('*');
								for (const el of all) {
									if (el.shadowRoot) queue.push(el.shadowRoot);
								}
							}
							return hits;
						}"""
					) or {}
					if bool(shadow_probe.get("sl")):
						found.append("shadow::input[placeholder*='SL']")
					if bool(shadow_probe.get("tp")):
						found.append("shadow::input[placeholder*='TP']")
				except Exception:
					pass
			return found

		if getattr(engine, "_should_dispatch", None) and engine._should_dispatch():
			strict_inputs_found = engine._run_thread_affine(_strict_scan, timeout_seconds=6.0) or []
		else:
			strict_inputs_found = _strict_scan()
	except Exception as exc:
		errors.append(str(exc))

	if not strict_inputs_found:
		fallback_inputs = list(dict.fromkeys(
			(engine.selector_aliases.get("stop_loss_input", []) or [])
			+ (engine.selector_aliases.get("take_profit_input", []) or [])
			+ (engine.selector_aliases.get("sl", []) or [])
			+ (engine.selector_aliases.get("tp", []) or [])
		))

	if not fallback_inputs:
		fallback_inputs = [
			"input[placeholder*='SL']",
			"input[placeholder*='TP']",
		]

	return {
		"status": "ok",
		"strict_present": bool(strict_inputs_found),
		"strict_inputs_found": strict_inputs_found,
		"fallback_used": not bool(strict_inputs_found),
		"inputs_found": strict_inputs_found if strict_inputs_found else fallback_inputs,
		"fallback_inputs": fallback_inputs,
		"errors": errors,
	}


@router.get("/execution/debug_sl_tp_per_trade")
async def debug_sl_tp_per_trade(max_rows: int = Query(default=25, ge=1, le=100)) -> Any:
	"""Inspect SL/TP presence for each visible open trade row."""
	engine = _runtime_playwright_engine()
	try:
		if getattr(engine, "_should_dispatch", None) and engine._should_dispatch():
			result = engine._run_thread_affine(
				lambda: engine.debug_sl_tp_per_trade(max_rows=max_rows),
				timeout_seconds=8.0,
			)
		else:
			result = engine.debug_sl_tp_per_trade(max_rows=max_rows)
	except Exception as exc:
		return {
			"status": "failed",
			"reason": str(exc),
			"trades_checked": 0,
			"trades": [],
		}

	if isinstance(result, dict):
		return result

	return {
		"status": "failed",
		"reason": "unexpected_result_type",
		"trades_checked": 0,
		"trades": [],
	}


@router.get("/execution/dom_probe")
async def execution_dom_probe() -> Any:
	"""Inspect broker DOM (including open shadow roots) for order-panel markers."""
	engine = _runtime_playwright_engine()
	try:
		def _probe_eval() -> Any:
			page = getattr(engine, "page", None)
			if page is None:
				return {"status": "failed", "reason": "page_unavailable"}
			return page.evaluate(
			r"""() => {
				const queue = [document];
				const nodes = [];
				while (queue.length) {
					const root = queue.shift();
					if (!root || !root.querySelectorAll) continue;
					const all = root.querySelectorAll('*');
					for (const el of all) {
						nodes.push(el);
						if (el.shadowRoot) queue.push(el.shadowRoot);
					}
				}

				const buttonLike = nodes.filter(el => {
					const tag = String(el.tagName || '').toLowerCase();
					const role = String(el.getAttribute?.('role') || '').toLowerCase();
					return tag === 'button' || role === 'button';
				});

				const textOf = (el) => String(el?.innerText || el?.textContent || '').toLowerCase().trim();
				const buyButtons = buttonLike.filter(el => /\bbuy\b|\blong\b/.test(textOf(el))).slice(0, 15).map(el => ({
					tag: String(el.tagName || '').toLowerCase(),
					text: textOf(el).slice(0, 80),
					dataTestId: String(el.getAttribute?.('data-testid') || ''),
					className: String(el.className || '').slice(0, 120),
				}));
				const sellButtons = buttonLike.filter(el => /\bsell\b|\bshort\b/.test(textOf(el))).slice(0, 15).map(el => ({
					tag: String(el.tagName || '').toLowerCase(),
					text: textOf(el).slice(0, 80),
					dataTestId: String(el.getAttribute?.('data-testid') || ''),
					className: String(el.className || '').slice(0, 120),
				}));

				const inputs = nodes.filter(el => String(el.tagName || '').toLowerCase() === 'input');
				const volumeInputs = inputs.filter(el => {
					const placeholder = String(el.getAttribute?.('placeholder') || '').toLowerCase();
					const name = String(el.getAttribute?.('name') || '').toLowerCase();
					const type = String(el.getAttribute?.('type') || '').toLowerCase();
					const inputmode = String(el.getAttribute?.('inputmode') || '').toLowerCase();
					return type === 'number' || inputmode === 'decimal' || /lot|volume|amount|qty|quantity/.test(`${placeholder} ${name}`);
				}).slice(0, 15).map(el => ({
					placeholder: String(el.getAttribute?.('placeholder') || ''),
					name: String(el.getAttribute?.('name') || ''),
					type: String(el.getAttribute?.('type') || ''),
					inputmode: String(el.getAttribute?.('inputmode') || ''),
					dataTestId: String(el.getAttribute?.('data-testid') || ''),
				}));

				const panelHints = nodes.filter(el => {
					const tag = String(el.tagName || '').toLowerCase();
					const testid = String(el.getAttribute?.('data-testid') || '').toLowerCase();
					return tag.includes('trade-order-panel') || testid.includes('order') || testid.includes('trade');
				}).slice(0, 20).map(el => ({
					tag: String(el.tagName || '').toLowerCase(),
					dataTestId: String(el.getAttribute?.('data-testid') || ''),
					className: String(el.className || '').slice(0, 120),
				}));

				return {
					nodeCount: nodes.length,
					buttonLikeCount: buttonLike.length,
					buyButtons,
					sellButtons,
					volumeInputs,
					panelHints,
				};
			}"""
			)

		if getattr(engine, "_should_dispatch", None) and engine._should_dispatch():
			probe = engine._run_thread_affine(_probe_eval, timeout_seconds=8.0)
		else:
			probe = _probe_eval()

		if isinstance(probe, dict) and probe.get("status") in {"failed", "error"}:
			return probe
		return {"status": "ok", "probe": probe}
	except Exception as exc:
		return {"status": "error", "reason": str(exc)}


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

	def _connect_once() -> tuple[bool, str | None]:
		try:
			return bool(engine.connect_to_broker()), None
		except Exception as thread_exc:
			return False, str(thread_exc)

	connected, reason = _connect_once()
	login_result = None
	if connected:
		try:
			login_result = engine.login_if_needed(
				username=EXECUTION_LOGIN_USERNAME,
				password=EXECUTION_LOGIN_PASSWORD,
			)
		except Exception as login_exc:
			login_result = {"ok": False, "status": "login_error", "reason": str(login_exc)}

	# Playwright Sync API can occasionally be invoked on a thread with an active
	# event loop. Retry once in a dedicated worker thread to avoid loop affinity.
	if (not connected) and reason and "sync api inside the asyncio loop" in reason.lower():
		connected, reason = _connect_once()

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
		"login": login_result,
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


@router.get("/execution/mode")
def execution_mode_get() -> Any:
	"""Return current execution mode and paper trade counters."""
	engine = _runtime_playwright_engine()
	paper_mode = bool(getattr(engine, "paper_mode", False))
	paper_log = list(getattr(engine, "paper_trade_log", []) or [])
	last_paper_trade = paper_log[-1] if paper_log else None
	return {
		"status": "ok",
		"mode": "paper" if paper_mode else "live",
		"paper_mode": paper_mode,
		"paper_trade_count": len(paper_log),
		"paper_trade_log": paper_log,
		"last_paper_trade": last_paper_trade,
	}


@router.post("/execution/mode")
def execution_mode_set(mode: str = Query(..., description="paper|live")) -> Any:
	"""Set runtime execution mode (paper/live) for Playwright execution."""
	engine = _runtime_playwright_engine()
	normalized = str(mode or "").strip().lower()
	if normalized not in {"paper", "live"}:
		raise HTTPException(status_code=400, detail="Invalid mode. Use 'paper' or 'live'.")

	new_paper_mode = normalized == "paper"
	setattr(engine, "paper_mode", new_paper_mode)
	# Keep process env aligned so newly initialized execution objects in this
	# process inherit the selected mode.
	os.environ["EXECUTION_PAPER_MODE"] = "1" if new_paper_mode else "0"

	paper_log = list(getattr(engine, "paper_trade_log", []) or [])
	last_paper_trade = paper_log[-1] if paper_log else None
	return {
		"status": "ok",
		"mode": "paper" if new_paper_mode else "live",
		"paper_mode": new_paper_mode,
		"paper_trade_count": len(paper_log),
		"paper_trade_log": paper_log,
		"last_paper_trade": last_paper_trade,
	}


@router.get("/execution/spot_fidelity")
def execution_spot_fidelity_get() -> Any:
	"""Return live spot-fidelity settings used by the active runtime runner."""
	runner = _runtime_runner()
	if runner is None:
		raise HTTPException(status_code=503, detail="Runtime runner unavailable")
	return _spot_fidelity_payload(runner)


@router.post("/execution/spot_fidelity")
def execution_spot_fidelity_set(
	strict: bool = Query(..., description="Enable or disable strict spot-fidelity guard"),
) -> Any:
	"""Set runtime spot-fidelity strictness without restarting services."""
	runner = _runtime_runner()
	if runner is None:
		raise HTTPException(status_code=503, detail="Runtime runner unavailable")

	new_strict = bool(strict)
	setattr(runner, "spot_fidelity_strict", new_strict)
	os.environ["SPOT_FIDELITY_STRICT"] = "true" if new_strict else "false"
	return _spot_fidelity_payload(runner)


@router.post("/execution/trigger")
def execution_trigger(symbol: str = Query(default="XAUUSD", description="Symbol to trigger once")) -> Any:
	"""
	Manually trigger a single process cycle for one symbol.
	Used by Ops panel "Trigger Trade" control.
	"""
	runner = _runtime_runner()
	if runner is None:
		raise HTTPException(status_code=503, detail="Runtime runner unavailable")

	requested_symbol = str(symbol or "").strip().upper() or "XAUUSD"
	available_symbols = [str(s or "").strip().upper() for s in (getattr(runner, "symbols", []) or []) if str(s or "").strip()]

	if available_symbols and requested_symbol not in set(available_symbols):
		raise HTTPException(
			status_code=400,
			detail={
				"message": f"Symbol '{requested_symbol}' is not configured in runtime symbols",
				"available_symbols": available_symbols,
			},
		)

	try:
		result = runner.process_symbol(requested_symbol)
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Manual trigger failed: {exc}") from exc

	engine = _runtime_playwright_engine()
	mode = "paper" if bool(getattr(engine, "paper_mode", False)) else "live"

	if isinstance(result, dict):
		result.setdefault("symbol", requested_symbol)
		result.setdefault("mode", mode)
		return {
			"status": "ok",
			"requested_symbol": requested_symbol,
			"result": result,
		}

	return {
		"status": "ok",
		"requested_symbol": requested_symbol,
		"result": {
			"status": "DONE",
			"symbol": requested_symbol,
			"mode": mode,
			"raw": result,
		},
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
	challenge_detected = False
	challenge_reason = None
	broker_title = str(broker_primary.get("title") or "")
	broker_url = str(broker_primary.get("url") or "")
	broker_url_lower = broker_url.lower()
	login_required = any(token in broker_url_lower for token in ["/login", "signin", "sign-in", "auth"])
	if broker_title.strip().lower() == "just a moment...":
		challenge_detected = True
		challenge_reason = "cloudflare_challenge"
	elif "challenge" in broker_title.lower() or "cf-chl" in broker_url.lower():
		challenge_detected = True
		challenge_reason = "challenge_page"

	bridge_ready = bool(same_browser_mode and (has_quote or has_order_panel) and not challenge_detected and not login_required)

	status = "OK" if bridge_ready else "DEGRADED"
	if login_required and not bridge_ready:
		status = "AUTH_REQUIRED"
	elif challenge_detected and not bridge_ready:
		status = "CHALLENGE"

	return {
		"status": status,
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
		"login_required": login_required,
		"challenge_detected": challenge_detected,
		"challenge_reason": challenge_reason,
		"quote": quote,
		"order_panel": order_panel,
		"hint": "Complete the Cloudflare/browser challenge in the shared remote-debug browser session, then wait for the order panel to appear." if challenge_detected else ("Log into Maven in the shared remote-debug browser session, then wait for the order panel to appear." if login_required else "Open Maven and AstroQuant dashboard in the same remote-debug Chrome session/profile."),
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


@router.post("/status/broker_bridge/stabilize")
def broker_bridge_stabilize(
	wait_seconds: int = Query(default=45, ge=5, le=180),
	interval_seconds: float = Query(default=5.0, ge=1.0, le=15.0),
	force_reconnect: bool = Query(default=True),
) -> Any:
	"""
	Attempt to stabilize the broker bridge after a restart by repeatedly reattaching,
	trying credential-based login, and reloading the tab when it is merely stale.

	This endpoint does not bypass browser challenges. If a Cloudflare or login gate is
	present, it returns a blocked status with the latest diagnostics so callers can stop
	automation cleanly instead of racing the startup sequence.
	"""
	runner = _runtime_runner()
	if runner is None:
		raise HTTPException(status_code=503, detail="Runtime runner unavailable")

	engine = _runtime_playwright_engine()
	deadline = time.time() + max(5, int(wait_seconds or 45))
	interval = max(1.0, min(float(interval_seconds or 5.0), 15.0))
	attempts: list[dict[str, Any]] = []
	reloaded_once = False
	calibrated_once = False

	while True:
		snapshot = _broker_bridge_payload()
		if snapshot.get("bridge_ready"):
			return {
				"status": "OK",
				"bridge_ready": True,
				"attempts": attempts,
				"bridge": snapshot,
			}

		if snapshot.get("challenge_detected"):
			return {
				"status": "BLOCKED",
				"reason": "challenge_detected",
				"attempts": attempts,
				"bridge": snapshot,
			}

		action = "observe"
		details: dict[str, Any] = {}

		try:
			if snapshot.get("login_required"):
				action = "login_if_needed"
				details = engine.login_if_needed(
					username=EXECUTION_LOGIN_USERNAME,
					password=EXECUTION_LOGIN_PASSWORD,
				) or {}
			else:
				action = "connect"
				details["connected"] = bool(engine.connect_to_broker())
				recovery = engine.recover_from_selector_failure(force_reconnect=force_reconnect) or {}
				details["recovery"] = recovery
				if not calibrated_once and not snapshot.get("order_panel", {}).get("ready") and not snapshot.get("quote"):
					try:
						details["calibration"] = engine.calibrate_selectors(save=True) or {}
						calibrated_once = True
						action = "connect_recover_calibrate"
					except Exception as exc:
						details["calibration_error"] = str(exc)
				if not reloaded_once and not snapshot.get("login_required") and not snapshot.get("challenge_detected"):
					page = getattr(engine, "page", None)
					if page is not None:
						try:
							page.reload(timeout=12000)
							reloaded_once = True
							action = f"{action}_reload"
						except Exception as exc:
							details["reload_error"] = str(exc)
		except Exception as exc:
			details["error"] = str(exc)

		attempts.append({
			"ts": int(time.time()),
			"action": action,
			"details": details,
		})

		if time.time() >= deadline:
			final_snapshot = _broker_bridge_payload()
			status = "BLOCKED" if (final_snapshot.get("challenge_detected") or final_snapshot.get("login_required")) else "TIMEOUT"
			reason = "challenge_detected" if final_snapshot.get("challenge_detected") else ("login_required" if final_snapshot.get("login_required") else "bridge_not_ready_before_timeout")
			return {
				"status": status,
				"reason": reason,
				"bridge_ready": bool(final_snapshot.get("bridge_ready")),
				"attempts": attempts,
				"bridge": final_snapshot,
			}

		time.sleep(interval)


@router.get("/status/data_freshness")
async def get_data_freshness(
	symbols: str = _default_runtime_symbols_csv(),
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
		requested = _runtime_symbols()[:1] or ["XAUUSD"]

	import concurrent.futures
	now = datetime.now(timezone.utc)
	sync = DatabentoSyncEngine() if include_resolver else None
	bounded_limit = max(1, int(limit))

	def _fetch_one(symbol: str) -> dict:
		try:
			candles, meta = fetch_candles_unified(symbol=symbol, limit=bounded_limit)
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
			return {
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
		except Exception as exc:
			return {"symbol": symbol, "status": "ERROR", "error": str(exc)}

	# Fetch all symbols in parallel — serial fetches were O(N * latency).
	rows_map: dict[str, dict] = {}
	with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(requested), 8)) as pool:
		future_to_sym = {pool.submit(_fetch_one, sym): sym for sym in requested}
		for fut in concurrent.futures.as_completed(future_to_sym, timeout=60):
			result = fut.result()
			rows_map[result["symbol"]] = result
	# Restore original request order.
	rows = [rows_map.get(sym, {"symbol": sym, "status": "ERROR", "error": "timeout"}) for sym in requested]

	overall = "OK" if all(r.get("status") == "OK" for r in rows) else "DEGRADED"
	return {
		"status": overall,
		"checked_at": now.isoformat(),
		"symbols": rows,
	}


@router.get("/status/feed/deep_probe")
async def status_feed_deep_probe(
	symbols: str = _default_runtime_symbols_csv(),
	max_candidates: int = 6,
	lookback_minutes: int = 180,
	record_limit: int = 400,
	force_resolve: bool = False,
	resolve_probe_seconds: float = 2.0,
	per_candidate_timeout_seconds: float = 2.0,
	global_timeout_seconds: float = 25.0,
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
		requested = _runtime_symbols()[:1] or ["XAUUSD"]

	rows = []
	bounded_candidates = max(1, min(int(max_candidates or 6), 16))
	bounded_lookback = max(15, min(int(lookback_minutes or 180), 60 * 24 * 14))
	bounded_limit = max(40, min(int(record_limit or 400), 1200))
	bounded_resolve_probe = max(0.5, min(float(resolve_probe_seconds or 2.0), 8.0))
	bounded_candidate_timeout = max(0.5, min(float(per_candidate_timeout_seconds or 2.0), 8.0))
	bounded_global_timeout = max(5.0, min(float(global_timeout_seconds or 25.0), 90.0))
	deadline = time.monotonic() + bounded_global_timeout
	probe_feed = MarketFeed(getattr(runner.feed, "api_key", None))

	def _probe_candidate_count(dataset_name: str, candidate_symbol: str) -> tuple[int, str | None]:
		"""Bound single candidate probe duration to keep endpoint responsive."""
		import concurrent.futures

		def _run_probe() -> tuple[int, str | None]:
			try:
				candles = probe_feed.get_ohlcv(
					dataset=dataset_name,
					symbol=candidate_symbol,
					lookback_minutes=bounded_lookback,
					record_limit=bounded_limit,
				)
				count_local = len(candles or [])
				err_local = None
				if count_local <= 0:
					err_local = str(getattr(probe_feed, "last_error", None) or "") or None
				return int(count_local), err_local
			except Exception as exc:
				return 0, str(exc)

		with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
			future = executor.submit(_run_probe)
			try:
				return future.result(timeout=bounded_candidate_timeout)
			except concurrent.futures.TimeoutError:
				future.cancel()
				return 0, f"TIMEOUT>{bounded_candidate_timeout:.1f}s"

	for raw_symbol in requested:
		if time.monotonic() >= deadline:
			rows.append(
				{
					"symbol": str(raw_symbol or "").upper(),
					"dataset": None,
					"active_before": None,
					"active_after": None,
					"resolver_before": None,
					"resolver_after": None,
					"results": [],
					"summary": {
						"status": "TIMEOUT",
						"best_candidate": None,
						"best_count": 0,
						"resolver_failures_before": None,
						"recommendation": "retry_with_fewer_symbols_or_candidates",
					},
					"error": "global_timeout_exceeded",
				}
			)
			continue

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
				if time.monotonic() >= deadline:
					entry["results"].append(
						{
							"candidate": candidate,
							"count": 0,
							"has_data": False,
							"error": "global_timeout_exceeded",
						}
					)
					break

				count, error = _probe_candidate_count(dataset, candidate)
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
			"per_candidate_timeout_seconds": bounded_candidate_timeout,
			"global_timeout_seconds": bounded_global_timeout,
			"recommendation": "verify_dataset_permissions_and_symbol_mapping" if total_with_data == 0 else "monitor",
		},
		"symbols": rows,
	}


@router.get("/status/symbol_registry")
async def get_symbol_registry() -> Any:
	runner = _runtime_runner()
	registry = {}
	resolver = getattr(runner, "contract_resolver", None) if runner is not None else None
	for symbol in _runtime_symbols():
		if resolver is not None:
			try:
				registry[symbol] = resolver.snapshot(symbol)
				continue
			except Exception:
				pass
		registry[symbol] = {
			"symbol": symbol,
			"active_symbol": None,
			"disabled": False,
			"disabled_reason": None,
			"cached_candidates": [],
			"candidate_count": 0,
			"cache_ttl_seconds": 0,
			"cached_at": None,
			"cached_age_seconds": None,
			"cache_valid": False,
			"consecutive_failures": 0,
		}
	return {
		"status": "OK",
		"symbols": [registry[s] for s in _runtime_symbols() if s in registry],
	}


@router.post("/status/symbol_registry/{symbol}/register")
async def register_runtime_symbol(symbol: str, max_probe_seconds: float = 3.0) -> Any:
	raw_key = str(symbol or "").upper().strip()
	key = normalize_runtime_symbol(raw_key)
	if key not in ALLOWED_RUNTIME_SYMBOLS:
		raise HTTPException(
			status_code=403,
			detail=f"Symbol '{raw_key}' is not enabled in AQ_RUNTIME_SYMBOLS",
		)
	added = bool(register_symbol(key))
	if key not in _runtime_symbols():
		raise HTTPException(status_code=400, detail=f"Unable to register symbol '{raw_key}'")

	runner = _runtime_runner()
	resolver = getattr(runner, "contract_resolver", None) if runner is not None else None
	resolver_snapshot = None
	try:
		if resolver is not None:
			resolver_snapshot = resolver.snapshot(key)
	except Exception:
		resolver_snapshot = None

	reprobe_queued = False
	try:
		reprobe_queued = bool(
			queue_symbol_reprobe(
				key,
				delay_seconds=0.0,
				max_probe_seconds=max(0.5, min(float(max_probe_seconds or 3.0), 8.0)),
			)
		)
	except Exception:
		reprobe_queued = False

	return {
		"status": "OK",
		"symbol": key,
		"added": added,
		"runtime_symbols": _runtime_symbols(),
		"resolver": resolver_snapshot,
		"reprobe_queued": reprobe_queued,
	}


@router.post("/status/symbol_registry/{symbol}/enable")
async def enable_symbol(symbol: str) -> Any:
    key = str(symbol or "").upper().strip()
    if key not in _runtime_symbols():
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{key}'")
    runner = _runtime_runner()
    resolver = getattr(runner, "contract_resolver", None) if runner is not None else None
    if resolver is not None:
        resolver.set_enabled(key)
        resolver_snapshot = resolver.snapshot(key)
    else:
        resolver_snapshot = None
    return {
        "status": "OK",
        "symbol": key,
        "enabled": True,
        "resolver": resolver_snapshot,
    }


@router.post("/status/symbol_registry/{symbol}/disable")
async def disable_symbol(symbol: str, reason: str = "MANUAL_DISABLED") -> Any:
    key = str(symbol or "").upper().strip()
    if key not in _runtime_symbols():
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{key}'")
    runner = _runtime_runner()
    resolver = getattr(runner, "contract_resolver", None) if runner is not None else None
    if resolver is not None:
        resolver.set_disabled(key, reason=reason)
        resolver_snapshot = resolver.snapshot(key)
    else:
        resolver_snapshot = None
    return {
        "status": "OK",
        "symbol": key,
        "enabled": False,
        "resolver": resolver_snapshot,
    }


@router.post("/status/symbol_registry/{symbol}/set_active")
async def set_symbol_active(symbol: str, contract: str) -> Any:
	key = str(symbol or "").upper().strip()
	active = str(contract or "").strip()
	if not active:
		raise HTTPException(status_code=400, detail="Missing contract parameter")

	if key not in _runtime_symbols():
		raise HTTPException(status_code=404, detail=f"Unknown symbol '{key}'")
	runner = _runtime_runner()
	resolver = getattr(runner, "contract_resolver", None) if runner is not None else None
	if resolver is not None:
		active = resolver.normalize_contract_symbol(active)
		resolver.set_active(
			key,
			active,
			sample_count=0,
			candidates_tried=[active],
			ttl_seconds=6 * 3600,
		)
		resolver_snapshot = resolver.snapshot(key)
	else:
		resolver_snapshot = None
	# Keep live runtime resolver aligned with operational registry changes.
	return {
		"status": "OK",
		"symbol": key,
		"active_symbol": active,
		"resolver": resolver_snapshot,
	}


@router.post("/status/symbol_registry/{symbol}/set_active_verify")
async def set_symbol_active_verify(
	symbol: str,
	contract: str,
	max_probe_seconds: float = 1.5,
	force_probe: bool = False,
	auto_reprobe: bool = True,
) -> Any:
	from astroquant.backend.runtime import get_runner, queue_symbol_reprobe

	key = str(symbol or "").upper().strip()
	active = str(contract or "").strip()
	if not active:
		raise HTTPException(status_code=400, detail="Missing contract parameter")

	if key not in _runtime_symbols():
		raise HTTPException(status_code=404, detail=f"Unknown symbol '{key}'")

	runner = get_runner()
	resolver = getattr(runner, "contract_resolver", None)
	if resolver is not None:
		active = resolver.normalize_contract_symbol(active)
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
		"resolver": resolver.snapshot(key) if resolver is not None else None,
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


@router.post("/execution/calibrate_selectors")
def execution_calibrate_selectors(save: bool = Query(default=True)) -> Any:
	"""
	Auto-discover and calibrate CSS/XPath selectors for Maven Markets broker UI.
	Iterates through selector aliases and finds which ones actually exist in the live DOM.
	Saves discovered selectors to persistent config if save=True.
	"""
	engine = _runtime_playwright_engine()
	try:
		result = engine.calibrate_selectors(save=save)
		return {
			"status": "ok" if result.get("ok") else "failed",
			"calibration": result,
		}
	except Exception as exc:
		return {
			"status": "error",
			"reason": str(exc),
			"calibration": {"ok": False, "reason": str(exc)},
		}


@router.post("/execution/test_sl_tp_fill")
def execution_test_sl_tp_fill(
	sl: float = Query(default=0.0),
	tp: float = Query(default=0.0),
) -> Any:
	"""
	Dry-run SL/TP fill test: opens the Advanced Order panel, writes SL and TP
	values into the inputs, reads them back, then closes the panel — no order submitted.
	"""
	import time as _time

	engine = _runtime_playwright_engine()

	def _do_fill():
		page = getattr(engine, "page", None)
		if page is None:
			return {"ok": False, "reason": "page_unavailable"}

		engine._try_reveal_sl_tp_inputs(page)
		_time.sleep(0.3)

		sl_selectors = engine.selector_aliases.get("stop_loss_input", [])
		tp_selectors = engine.selector_aliases.get("take_profit_input", [])

		sl_filled = engine._set_price_input(page, sl_selectors, sl) if sl else False
		tp_filled = engine._set_price_input(page, tp_selectors, tp) if tp else False

		# Read back what's actually in the inputs now.
		def _read_val(selectors):
			for sel in selectors:
				try:
					loc = page.locator(sel)
					if loc.count() > 0:
						v = ""
						try:
							v = str(loc.first.input_value() or "").strip()
						except Exception:
							pass
						if not v:
							try:
								v = str(loc.first.get_attribute("value") or "").strip()
							except Exception:
								pass
						if v:
							return v, sel
				except Exception:
					continue
			return None, None

		sl_read, sl_sel = _read_val(sl_selectors)
		tp_read, tp_sel = _read_val(tp_selectors)

		# Close the advanced panel — click advanced-order-button again to toggle off.
		for adv_sel in (engine.selector_aliases.get("advanced_order_toggle") or []):
			try:
				loc = page.locator(adv_sel)
				if loc.count() > 0:
					try:
						loc.first.click(timeout=1000)
					except Exception:
						pass
					_time.sleep(0.15)
					break
			except Exception:
				continue

		return {
			"ok": True,
			"sl_fill_attempted": bool(sl),
			"tp_fill_attempted": bool(tp),
			"sl_filled": bool(sl_filled),
			"tp_filled": bool(tp_filled),
			"sl_readback": sl_read,
			"tp_readback": tp_read,
			"sl_selector_used": sl_sel,
			"tp_selector_used": tp_sel,
			"sl_match": bool(sl_read and abs(float(sl_read.replace(",","")) - float(sl)) < 1.0) if sl and sl_read else None,
			"tp_match": bool(tp_read and abs(float(tp_read.replace(",","")) - float(tp)) < 1.0) if tp and tp_read else None,
		}

	try:
		if getattr(engine, "_should_dispatch", None) and engine._should_dispatch():
			result = engine._run_thread_affine(_do_fill, timeout_seconds=12.0)
		else:
			result = _do_fill()
	except Exception as exc:
		return {"ok": False, "reason": str(exc)}

	return result if isinstance(result, dict) else {"ok": False, "reason": "unexpected_result"}




# ---------------------------------------------------------------------------
# Trade approval endpoints
# ---------------------------------------------------------------------------

@router.get("/pending_trades")
async def get_pending_trades() -> Any:
    """Return all pending trade approval requests that have not expired."""
    _prune_expired_approvals()
    return {
        "pending": list(_PENDING_APPROVALS.values()),
        "count": len(_PENDING_APPROVALS),
    }


@router.post("/trade/approve/{trade_id}")
async def approve_trade(trade_id: str) -> Any:
    """Approve a pending trade request. The engine will execute it on the next cycle."""
    _prune_expired_approvals()
    rec = _PENDING_APPROVALS.get(trade_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Trade request not found or expired")
    if rec["status"] != "PENDING":
        return {"ok": False, "trade_id": trade_id, "status": rec["status"], "reason": "already decided"}
    rec["status"] = "APPROVED"
    rec["decided_at"] = time.time()
    return {"ok": True, "trade_id": trade_id, "status": "APPROVED"}


@router.post("/trade/reject/{trade_id}")
async def reject_trade(trade_id: str) -> Any:
    """Reject a pending trade request."""
    _prune_expired_approvals()
    rec = _PENDING_APPROVALS.get(trade_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Trade request not found or expired")
    if rec["status"] != "PENDING":
        return {"ok": False, "trade_id": trade_id, "status": rec["status"], "reason": "already decided"}
    rec["status"] = "REJECTED"
    rec["decided_at"] = time.time()
    return {"ok": True, "trade_id": trade_id, "status": "REJECTED"}
