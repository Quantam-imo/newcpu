import os
from fastapi import APIRouter, Response, Request
from typing import Any
import sqlite3
import time
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone

router = APIRouter()

# Last-known-good chart data endpoint for institutional reliability
@router.get("/chart/last_known")
def get_last_known_chart(symbol: str = "GC.FUT", timeframe: str = "1", limit: int = 80) -> Any:
	"""
	Returns the last-known-good chart data for a symbol/timeframe from Redis or a fallback file.
	"""
	from astroquant.engine.candle.candle_reader import get_candle_series
	import json
	# Try Redis first only if quickly reachable.
	if _redis_reachable():
		try:
			candles = get_candle_series(symbol, timeframe, limit)
			if candles and len(candles):
				return {
					"candles": candles,
					"meta": {"count": len(candles), "source": "redis"},
					"overlays": {},
					"signals": []
				}
		except Exception:
			pass
	# Fallback: try to load from a file (e.g., data/last_known_chart_{symbol}_{timeframe}.json)
	fname = f"data/last_known_chart_{symbol}_{timeframe}.json"
	if os.path.exists(fname):
		try:
			with open(fname, "r", encoding="utf-8") as f:
				payload = json.load(f)
			if payload and isinstance(payload, dict) and payload.get("candles"):
				return payload
		except Exception:
			pass
	# If all else fails, return empty
	return {
		"candles": [],
		"meta": {"count": 0, "source": "none"},
		"overlays": {},
		"signals": []
	}
from typing import Any

# Explicit OPTIONS handler for CORS preflight (must be after router = APIRouter())
@router.options("/chart/data")
def options_chart_data(response: Response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return Response(status_code=204)


# Real endpoint for chart data

import logging
from astroquant.engine.candle.candle_reader import get_candle_series, get_latest_candle
from astroquant.backend.config import TRADING_FUTURES_SYMBOLS, TRADING_SYMBOL_ALIASES, symbol_dataset
from astroquant.backend.runtime import get_runner, normalize_runtime_symbol
from astroquant.backend.config import ACCOUNT_CONFIG
from astroquant.backend.governance.prop_governance import PropConfig, PropGovernance
from astroquant.engine.market_feed import MarketFeed


_PROP_BEHAVIOR_OVERRIDES: dict[str, dict] = {}
_REDIS_UNAVAILABLE_UNTIL = 0.0


def _redis_reachable(host: str = "127.0.0.1", port: int = 6379, timeout_seconds: float = 0.15) -> bool:
	"""
	Fast Redis availability probe used to avoid repeated multi-second connection
	retries in request paths when Redis is down.
	"""
	global _REDIS_UNAVAILABLE_UNTIL
	now = time.time()
	if now < _REDIS_UNAVAILABLE_UNTIL:
		return False
	try:
		with socket.create_connection((host, port), timeout=timeout_seconds):
			return True
	except Exception:
		# Back off for a minute before probing again.
		_REDIS_UNAVAILABLE_UNTIL = now + 60.0
		return False


def _normalize_trading_symbol(symbol: str) -> str:
	key = str(symbol or "").strip().upper()
	if key in TRADING_SYMBOL_ALIASES:
		return TRADING_SYMBOL_ALIASES[key]
	return key


def _market_data_for_api(runner, symbol: str, prefer_realtime: bool = True) -> tuple[dict, str]:
	"""
	Hybrid fetch for API endpoints:
	- If resolver has a cached active contract, use realtime fetch.
	- Otherwise return fast fallback payload immediately.
	"""
	try:
		resolver = getattr(runner, "contract_resolver", None)
		cached_active = resolver.get_cached(symbol, max_age_seconds=6 * 3600) if resolver else None
	except Exception:
		cached_active = None

	if prefer_realtime and cached_active:
		try:
			data = runner.get_market_data(
				symbol,
				max_probe_seconds=1.0,
				realtime_fetch=True,
			)
			if data:
				return data, "cached_realtime"
		except Exception:
			pass

	data = runner.get_market_data(
		symbol,
		max_probe_seconds=1.0,
		realtime_fetch=False,
	) or {}
	return data, "fast_fallback"


def _behavior_override(symbol: str) -> dict | None:
	key = str(symbol or "").upper().strip()
	row = _PROP_BEHAVIOR_OVERRIDES.get(key)
	if not row:
		return None
	expires_at = float(row.get("expires_at") or 0.0)
	if expires_at > 0 and expires_at <= time.time():
		_PROP_BEHAVIOR_OVERRIDES.pop(key, None)
		return None
	return row


def _compute_auto_behavior(
	symbol: str,
	equity: float,
	daily_loss: float,
	drawdown: float,
	phase: str = "PHASE1",
	volatility_mode: str = "NORMAL",
	news_mode: str = "NORMAL",
) -> tuple[dict, dict]:
	canonical = normalize_runtime_symbol(symbol)
	governance = PropGovernance(PropConfig(account_size=float(ACCOUNT_CONFIG.get("initial_balance", 50000.0))))
	profile = governance.compute_auto_behavior_profile(
		equity=float(equity),
		daily_loss=float(daily_loss),
		drawdown=float(drawdown),
		news_mode=str(news_mode or "NORMAL"),
		phase=str(phase or "PHASE1"),
		volatility_mode=str(volatility_mode or "NORMAL"),
	)
	override = _behavior_override(canonical)
	if override:
		if override.get("mode") is not None:
			profile["mode"] = override.get("mode")
		if override.get("risk_multiplier") is not None:
			profile["risk_multiplier"] = float(override.get("risk_multiplier"))
		if override.get("hard_block") is not None:
			profile["hard_block"] = bool(override.get("hard_block"))
		if override.get("reasons"):
			profile["reasons"] = list(override.get("reasons"))

	expires = float(override.get("expires_at") or 0.0) if override else 0.0
	override_view = {
		"enabled": bool(override),
		"mode": override.get("mode") if override else None,
		"risk_multiplier": override.get("risk_multiplier") if override else None,
		"hard_block": override.get("hard_block") if override else None,
		"reasons": list(override.get("reasons") or []) if override else [],
		"expires_at": int(expires) if expires > 0 else None,
	}
	return profile, override_view


@router.get("/chart/data")
def get_chart_data(symbol: str = "GC.FUT", timeframe: str = "1", limit: int = 80, schema: str = "ohlcv-1m", dataset: str = "GLBX.MDP3") -> Any:
	from astroquant.backend.services.databento_utility import fetch_candles_unified
	import json

	def _candle_age_seconds(row: dict) -> float | None:
		ts = row.get("time") or row.get("timestamp")
		if ts is None:
			return None
		try:
			if isinstance(ts, (int, float)):
				dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
			else:
				dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
			return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
		except Exception:
			return None

	symbol = _normalize_trading_symbol(symbol)
	if symbol not in set(TRADING_FUTURES_SYMBOLS):
		return {
			"candles": [],
			"meta": {
				"source": "none",
				"count": 0,
				"status": "UNSUPPORTED_SYMBOL",
				"supported_symbols": list(TRADING_FUTURES_SYMBOLS),
			},
			"overlays": {},
			"signals": [],
		}

	error_msgs = []
	if _redis_reachable():
		try:
			candles = get_candle_series(symbol, timeframe, limit)
		except Exception as exc:
			candles = []
			error_msgs.append(f"Redis error: {exc}")
	else:
		candles = []
		error_msgs.append("Redis unavailable: fast-skip")

	meta = {"source": "redis", "count": len(candles)} if candles else {}

	# Fast-path: serve disk cache immediately if it was written within the last 15 minutes.
	# This avoids the 10-15 second Databento cold-start when the data was recently fetched.
	# Disk cache is written every time a successful Databento fetch completes, so a <15 min
	# cache means data is effectively live (the page auto-refreshes every 3-9 seconds anyway).
	_DISK_CACHE_FAST_SECONDS = 3600  # 1 hour (cache is refreshed on every successful Databento fetch)
	if not candles:
		import json as _json
		_cache_path = f"data/last_known_chart_{symbol}_{timeframe}.json"
		try:
			if os.path.exists(_cache_path):
				_stat = os.stat(_cache_path)
				_age = time.time() - _stat.st_mtime
				if _age < _DISK_CACHE_FAST_SECONDS:
					with open(_cache_path, "r", encoding="utf-8") as _f:
						_cached = _json.load(_f)
					_lk = list(_cached.get("candles") or [])
					if _lk:
						candles = _lk
						meta = {
							"source": "disk_cache_fast",
							"count": len(candles),
							"cache_age_seconds": int(_age),
							"degraded_data": _age > 300,  # flag as degraded if >5 min old
						}
		except Exception:
			pass

	if not candles:
		try:
			pool = ThreadPoolExecutor(max_workers=1)
			future = pool.submit(fetch_candles_unified, symbol=symbol, limit=limit)
			candles, fetch_meta = future.result(timeout=15.0)
			meta = {
				"source": "databento_final_engine",
				"count": len(candles),
				"fetch": fetch_meta,
			}
			if candles:
				try:
					os.makedirs("data", exist_ok=True)
					cache_path = f"data/last_known_chart_{symbol}_{timeframe}.json"
					with open(cache_path, "w", encoding="utf-8") as f:
						json.dump(
							{
								"candles": candles,
								"meta": {
									"source": "databento_final_engine",
									"count": len(candles),
									"cached_at": int(time.time()),
								},
								"overlays": {},
								"signals": [],
							},
							f,
						)
				except Exception:
					pass
		except FuturesTimeoutError:
			error_msgs.append("Databento unified fetch timeout")
			candles = []
			meta = {"source": "none", "count": 0}
		except Exception as exc:
			error_msgs.append(f"Databento unified fetch error: {exc}")
			candles = []
			meta = {"source": "none", "count": 0}
		finally:
			try:
				pool.shutdown(wait=False, cancel_futures=True)
			except Exception:
				pass

	# Hard fallback: return last-known-good payload so chart never blocks.
	if not candles:
		last_known = get_last_known_chart(symbol=symbol, timeframe=timeframe, limit=limit) or {}
		lk_candles = list(last_known.get("candles") or [])
		if lk_candles:
			candles = lk_candles
			meta = {
				"source": "last_known",
				"count": len(candles),
				"fallback": dict(last_known.get("meta") or {}),
			}

	# If candles exist but are stale, try direct market-feed refresh from active resolver symbol.
	if candles:
		try:
			age_seconds = _candle_age_seconds(candles[-1])
			if age_seconds is not None and age_seconds > (6 * 3600):
				runner = get_runner()
				canonical = normalize_runtime_symbol(symbol)
				active_symbol = runner.resolve_active_feed_symbol(canonical)
				dataset_name = symbol_dataset(canonical)
				fresh = runner.feed.get_ohlcv(
					dataset=dataset_name,
					symbol=active_symbol,
					lookback_minutes=max(60, min(int(limit or 80) * 3, 720)),
					record_limit=max(120, min(int(limit or 80) * 3, 1200)),
				)
				if fresh:
					candles = list(fresh)[-max(1, int(limit or 80)):]
					meta = {
						"source": "market_feed_direct",
						"count": len(candles),
						"active_symbol": active_symbol,
						"dataset": dataset_name,
					}
		except Exception as exc:
			error_msgs.append(f"Stale refresh fallback error: {exc}")

	if error_msgs:
		meta["errors"] = error_msgs

	return {
		"candles": candles,
		"meta": meta,
		"overlays": {},
		"signals": [],
	}

# Minimal /equity endpoint for dashboard integration
@router.get("/equity")
def get_equity(request: Request):
	base = float(ACCOUNT_CONFIG.get("initial_balance", 50000.0))
	target = round(base * 1.08, 2)
	equity = base
	primary_account = "PRIMARY"

	conn = None
	try:
		from astroquant.backend.database import get_connection
		conn = get_connection()
		cur = conn.cursor()
		try:
			cur.execute("SELECT SUM(balance) FROM accounts WHERE active=1")
			value = cur.fetchone()[0]
			if value is not None:
				equity = float(value)
		except Exception:
			pass
		try:
			cur.execute("SELECT base_balance, target_balance, primary_account FROM portfolio_meta LIMIT 1")
			row = cur.fetchone()
			if row:
				base = float(row[0] or base)
				target = float(row[1] or target)
				primary_account = str(row[2] or primary_account)
		except Exception:
			pass
	except Exception:
		try:
			journal_path = "ai_trade_journal.db"
			if os.path.exists(journal_path):
				jconn = sqlite3.connect(journal_path)
				try:
					jcur = jconn.cursor()
					jcur.execute("SELECT COALESCE(SUM(COALESCE(pnl, 0)), 0.0) FROM trades")
					total_pnl = float((jcur.fetchone() or [0.0])[0] or 0.0)
					equity = base + total_pnl
				finally:
					jconn.close()
		except Exception:
			pass
	finally:
		if conn is not None:
			try:
				conn.close()
			except Exception:
				pass

	return {
		"equity": equity,
		"base": base,
		"target": target,
		"primary_account": primary_account
	}

# Minimal /market/orderflow_summary endpoint for chart/dashboard integration
@router.get("/market/orderflow_summary")
def get_orderflow_summary(symbol: str = "GC.FUT", timeframe: str = "1m"):
	runtime_symbol = normalize_runtime_symbol(symbol)
	try:
		runner = get_runner()
		market_data, mode = _market_data_for_api(runner, runtime_symbol)
		absorption_levels = list(market_data.get("absorption_levels") or [])
		buy_aggression = float(market_data.get("buy_volume") or 0.0)
		sell_aggression = float(market_data.get("sell_volume") or 0.0)
		delta = float(market_data.get("delta") or 0.0)
		candles = list(market_data.get("candles") or [])
		dom_spread = max((float(c.get("high", 0.0)) - float(c.get("low", 0.0)) for c in candles), default=0.0)
		iceberg_count = len(absorption_levels)
		confidence = min(100.0, abs(delta) / max(1.0, buy_aggression + sell_aggression) * 100.0) if (buy_aggression + sell_aggression) > 0 else 0.0
		regime_mode = "BULLISH" if delta >= 0 else "BEARISH"
		alert_level = "HIGH" if iceberg_count > 0 or abs(delta) > 1000 else "LOW"
		absorption = "BULLISH" if (iceberg_count > 0 and delta >= 0) else ("BEARISH" if iceberg_count > 0 else "NEUTRAL")
		imbalance = "BUY" if delta > 0 else ("SELL" if delta < 0 else "NONE")
		return {
			"summary": {
				"regime_mode": regime_mode,
				"alert_level": alert_level,
				"signal_strength": confidence,
				"buy_aggression": buy_aggression,
				"sell_aggression": sell_aggression,
				"delta": delta,
				"cumulative_delta": delta,
				"imbalance": imbalance,
				"dom_spread": dom_spread,
				"iceberg_count": iceberg_count,
				"absorption": absorption,
				"confidence": confidence,
				"market_data_mode": mode,
				"narrative": f"Orderflow {runtime_symbol}: {regime_mode}, absorption={iceberg_count}, delta={delta:.2f}",
			}
		}
	except Exception:
		pass

	from astroquant.engine.candle.candle_reader import get_candle_series
	candles = get_candle_series(symbol, timeframe, limit=120)
	buy_aggression = sum(c["volume"] for c in candles if c["close"] > c["open"])
	sell_aggression = sum(c["volume"] for c in candles if c["close"] < c["open"])
	delta = buy_aggression - sell_aggression
	cumulative_delta = sum(c["close"] - c["open"] for c in candles)
	dom_spread = max(c["high"] - c["low"] for c in candles) if candles else 0.0
	iceberg_count = sum(1 for c in candles if c["volume"] > 1000)
	confidence = min(100.0, (buy_aggression + sell_aggression) / max(1, len(candles)))
	regime_mode = "BULLISH" if delta > 0 else "BEARISH"
	alert_level = "LOW" if abs(delta) < 1000 else "HIGH"
	absorption = "NEUTRAL"
	imbalance = "NONE"
	narrative = f"Orderflow: {regime_mode}, delta={delta}, volume={buy_aggression+sell_aggression}"
	signal_strength = confidence
	return {
		"summary": {
			"regime_mode": regime_mode,
			"alert_level": alert_level,
			"signal_strength": signal_strength,
			"buy_aggression": buy_aggression,
			"sell_aggression": sell_aggression,
			"delta": delta,
			"cumulative_delta": cumulative_delta,
			"imbalance": imbalance,
			"dom_spread": dom_spread,
			"iceberg_count": iceberg_count,
			"absorption": absorption,
			"confidence": confidence,
			"narrative": narrative
		}
	}


@router.get("/delta/{symbol}")
def market_delta_legacy(symbol: str):
	"""
	Backward-compatible delta endpoint used by older frontend bundles.
	Returns delta_percent in [0, 1] style to match legacy UI expectation.
	"""
	try:
		summary_payload = get_orderflow_summary(symbol=symbol)
		summary = (summary_payload or {}).get("summary") or {}
		delta = float(summary.get("delta") or 0.0)
		buy = float(summary.get("buy_aggression") or 0.0)
		sell = float(summary.get("sell_aggression") or 0.0)
		total = buy + sell
		delta_percent = (delta / total) if total > 0 else 0.0
		return {
			"symbol": normalize_runtime_symbol(symbol),
			"delta_percent": delta_percent,
			"summary": summary,
		}
	except Exception as exc:
		return {
			"symbol": normalize_runtime_symbol(symbol),
			"delta_percent": 0.0,
			"error": str(exc),
		}


@router.get("/market/offset_quality")
def market_offset_quality(symbol: str = "XAUUSD") -> Any:
	canonical_symbol = normalize_runtime_symbol(symbol)
	runner = get_runner()
	market_data, mode = _market_data_for_api(runner, canonical_symbol)
	basis_snapshot = runner.get_basis_snapshot(canonical_symbol)
	if str(basis_snapshot.get("status") or "").upper() == "UNINITIALIZED":
		basis_snapshot = market_data.get("basis") or basis_snapshot
	basis_policy = runner.basis_safety_policy(canonical_symbol, basis_snapshot=basis_snapshot)
	offset_guard = runner.offset_guard_snapshot(canonical_symbol, basis_snapshot=basis_snapshot)
	trade_quality = runner.trade_quality_snapshot(
		canonical_symbol,
		market_data=market_data,
		basis_snapshot=basis_snapshot,
		basis_policy=basis_policy,
		include_signal_candidates=False,
	)
	spot_quote = runner.get_broker_spot_quote(canonical_symbol) or {}
	broker_quote = dict(spot_quote.get("snapshot") or {})
	spot_price = spot_quote.get("price")
	futures_price = None
	try:
		candles = list(market_data.get("candles") or [])
		if candles:
			futures_price = float((candles[-1] or {}).get("close"))
	except Exception:
		futures_price = None
	offset_difference = None
	try:
		if futures_price is not None and spot_price is not None:
			offset_difference = float(futures_price) - float(spot_price)
	except Exception:
		offset_difference = None
	broker_symbol_price = broker_quote.get("mid")
	if broker_symbol_price is None:
		broker_symbol_price = broker_quote.get("last")
	if broker_symbol_price is None:
		broker_symbol_price = spot_price
	absorption_levels = list(market_data.get("absorption_levels") or [])
	return {
		"symbol": canonical_symbol,
		"market_data_mode": mode,
		"sources": {
			"futures_source": market_data.get("futures_source") or basis_snapshot.get("futures_source") or canonical_symbol,
			"broker_symbol": canonical_symbol,
			"spot_source": market_data.get("spot_source") or spot_quote.get("source"),
		},
		"basis": basis_snapshot,
		"basis_policy": basis_policy,
		"offset_guard": offset_guard,
		"trade_quality": trade_quality,
		"signal_detection": {
			"count": len(absorption_levels),
			"absorption": bool(absorption_levels),
			"levels": absorption_levels[-5:],
		},
		"prices": {
			"futures_price": futures_price,
			"offset_difference": offset_difference,
			"broker_xauusd_price": broker_symbol_price,
		},
		"broker_quote": broker_quote,
	}


def _registry_entry(canonical_symbol: str) -> dict:
	try:
		from astroquant.engine.databento_sync_engine import DatabentoSyncEngine

		sync = DatabentoSyncEngine()
		registry = sync.get_symbol_registry() or {}
		entry = dict(registry.get(canonical_symbol) or {})
		if not entry:
			return {}
		resolver = dict(entry.get("resolver") or {})
		if resolver:
			entry["resolver"] = resolver
		return entry
	except Exception:
		return {}


@router.get("/market/basis")
def market_basis(symbol: str = "XAUUSD", refresh: bool = False) -> Any:
	canonical_symbol = normalize_runtime_symbol(symbol)
	runner = get_runner()

	if bool(refresh):
		try:
			# Trigger a fast refresh pass; endpoint still returns quickly under fallback mode.
			runner.get_market_data(canonical_symbol, max_probe_seconds=1.0, realtime_fetch=True)
		except Exception:
			pass

	basis_snapshot = runner.get_basis_snapshot(canonical_symbol) or {}
	if str(basis_snapshot.get("status") or "").upper() == "UNINITIALIZED":
		try:
			market_data, _ = _market_data_for_api(runner, canonical_symbol)
			basis_snapshot = market_data.get("basis") or basis_snapshot
		except Exception:
			pass

	return {
		"symbol": canonical_symbol,
		**dict(basis_snapshot or {}),
	}


@router.get("/market/contracts")
def market_contracts(symbol: str = "XAUUSD") -> Any:
	canonical_symbol = normalize_runtime_symbol(symbol)
	runner = get_runner()

	resolver = {}
	try:
		resolver = dict(runner.contract_resolver.snapshot(canonical_symbol) or {})
	except Exception:
		resolver = {}

	registry_entry = _registry_entry(canonical_symbol)
	registry_resolver = dict(registry_entry.get("resolver") or {})
	if registry_resolver:
		# Keep canonical contract candidates from operational registry if runtime lacks them.
		resolver.setdefault("candidates_tried", registry_resolver.get("candidates_tried"))
		resolver.setdefault("ttl_seconds", registry_resolver.get("ttl_seconds"))

	active = resolver.get("active_symbol") or registry_entry.get("active_symbol")
	candidates = list(dict.fromkeys([c for c in list(resolver.get("candidates_tried") or []) if c]))
	if active and active not in candidates:
		candidates.insert(0, active)

	return {
		"symbol": canonical_symbol,
		"active_symbol": active,
		"resolver": resolver,
		"candidates": candidates,
	}


@router.post("/market/contracts/warmup")
def market_contracts_warmup(
	force_refresh: bool = True,
	max_candidates: int = 1,
	max_probe_seconds: float = 0.8,
) -> Any:
	runner = get_runner()
	try:
		warmed = runner.warmup_contracts(
			force_probe=bool(force_refresh),
			max_candidates=max(1, min(int(max_candidates or 1), 12)),
			max_probe_seconds=max(0.25, min(float(max_probe_seconds or 0.8), 10.0)),
		)
	except Exception as exc:
		return {
			"status": "ERROR",
			"error": str(exc),
			"symbols": {},
		}

	resolved = 0
	for row in (warmed or {}).values():
		active_symbol = str((row or {}).get("active_symbol") or "").strip()
		if active_symbol:
			resolved += 1
	total = len(warmed or {})
	return {
		"status": "OK",
		"symbols": warmed,
		"summary": {
			"resolved": resolved,
			"unresolved": max(0, total - resolved),
			"total": total,
		},
	}


@router.get("/market/context")
def market_context(symbol: str = "XAUUSD") -> Any:
	canonical_symbol = normalize_runtime_symbol(symbol)
	runner = get_runner()
	basis_snapshot = runner.get_basis_snapshot(canonical_symbol) or {}
	basis_policy = runner.basis_safety_policy(canonical_symbol, basis_snapshot=basis_snapshot)

	resolver_snapshot = {}
	try:
		resolver_snapshot = dict(runner.contract_resolver.snapshot(canonical_symbol) or {})
	except Exception:
		resolver_snapshot = {}

	watch_snapshot = {}
	try:
		watch_snapshot = dict(runner.resolver_watch_snapshot(canonical_symbol) or {})
	except Exception:
		watch_snapshot = {
			"symbol": canonical_symbol,
			"watch_only": False,
			"reason": None,
			"resolver_status": resolver_snapshot.get("last_status"),
			"resolver_failures": int(resolver_snapshot.get("consecutive_failures") or 0),
		}

	return {
		"symbol": canonical_symbol,
		"basis_policy": basis_policy,
		"resolver_watch": watch_snapshot,
	}


@router.get("/market/symbol_probe")
def market_symbol_probe(
	symbol: str = "XAUUSD",
	lookback_minutes: int = 240,
	include_contracts: bool = False,
	max_candidates: int = 4,
) -> Any:
	canonical_symbol = normalize_runtime_symbol(symbol)
	runner = get_runner()
	dataset = symbol_dataset(canonical_symbol)
	probe_feed = MarketFeed(getattr(runner.feed, "api_key", None))

	results = []
	active = None
	try:
		active = runner.resolve_active_feed_symbol(
			canonical_symbol,
			force_probe=False,
			max_candidates=max(1, min(int(max_candidates or 4), 12)),
			max_probe_seconds=1.5,
			probe_lookback_minutes=max(15, min(int(lookback_minutes or 240), 720)),
			probe_record_limit=240,
		)
	except Exception:
		active = None

	resolver_snapshot = {}
	try:
		resolver_snapshot = dict(runner.contract_resolver.snapshot(canonical_symbol) or {})
	except Exception:
		resolver_snapshot = {}

	candidates = []
	if bool(include_contracts):
		candidates = runner.candidate_feed_symbols(canonical_symbol, include_contracts=True)
	else:
		candidates = list(resolver_snapshot.get("candidates_tried") or [])
		if not candidates:
			candidates = runner.candidate_feed_symbols(canonical_symbol, include_contracts=True)

	unique = []
	seen = set()
	for candidate in candidates:
		key = str(candidate or "").strip()
		if not key or key in seen:
			continue
		seen.add(key)
		unique.append(key)
	unique = unique[: max(1, min(int(max_candidates or 4), 12))]

	bounded_lookback = max(15, min(int(lookback_minutes or 240), 60 * 24 * 14))
	for candidate in unique:
		count = 0
		error = None
		try:
			candles = probe_feed.get_ohlcv(
				dataset=dataset,
				symbol=candidate,
				lookback_minutes=bounded_lookback,
				record_limit=240,
			)
			count = len(candles or [])
		except Exception as exc:
			error = str(exc)
		if not error and count <= 0:
			error = str(getattr(probe_feed, "last_error", None) or "") or None
		results.append(
			{
				"candidate": candidate,
				"count": int(count),
				"active": bool(active and str(candidate) == str(active)),
				"error": error,
			}
		)

	return {
		"symbol": canonical_symbol,
		"dataset": dataset,
		"active_symbol": active,
		"results": results,
		"resolver": resolver_snapshot,
	}

@router.get("/dashboard/multi_symbol")
def get_multi_symbol_dashboard() -> Any:
	from astroquant.engine.databento_sync_engine import DatabentoSyncEngine

	runtime_symbols = ["XAUUSD", "NQ", "EURUSD", "US30"]
	runner = get_runner()
	registry_map: dict[str, dict] = {}
	try:
		sync = DatabentoSyncEngine()
		registry_map = sync.get_symbol_registry() or {}
	except Exception:
		registry_map = {}

	rows = []
	feed_healthy = False
	for symbol in runtime_symbols:
		canonical = normalize_runtime_symbol(symbol)
		try:
			# Keep dashboard scans responsive under feed degradation.
			market_data, mode = _market_data_for_api(runner, canonical, prefer_realtime=False)
		except Exception:
			market_data, mode = ({}, "fast_fallback")

		candles = list(market_data.get("candles") or [])
		futures_price = None
		if candles:
			try:
				futures_price = float((candles[-1] or {}).get("close"))
			except Exception:
				futures_price = None

		quote = {}
		broker_price = None
		try:
			quote = runner.get_broker_spot_quote(canonical) or {}
			broker_price = quote.get("price")
			if broker_price is None:
				snapshot = quote.get("snapshot") or {}
				broker_price = snapshot.get("mid") or snapshot.get("last")
		except Exception:
			quote = {}
			broker_price = None

		if futures_price is not None or broker_price is not None:
			feed_healthy = True

		offset_diff = None
		try:
			if futures_price is not None and broker_price is not None:
				offset_diff = float(broker_price) - float(futures_price)
		except Exception:
			offset_diff = None

		basis_status = "UNAVAILABLE"
		try:
			basis_status = str((runner.get_basis_snapshot(canonical) or {}).get("status") or "UNAVAILABLE")
		except Exception:
			basis_status = "UNAVAILABLE"

		registry = dict(registry_map.get(canonical) or {})
		resolver = registry.get("resolver") or registry
		status = str(resolver.get("last_status") or "UNKNOWN").upper()
		watch_only = status in {"UNRESOLVED", "MISS"}
		resolver_row = {
			"status": status,
			"watch_only": watch_only,
			"active_symbol": resolver.get("active_symbol"),
			"attempts": resolver.get("attempts"),
			"consecutive_failures": resolver.get("consecutive_failures"),
		}

		behavior, _ = _compute_auto_behavior(
			symbol=canonical,
			equity=float(ACCOUNT_CONFIG.get("initial_balance", 50000.0)),
			daily_loss=0.0,
			drawdown=0.0,
		)

		rows.append(
			{
				"symbol": canonical,
				"market": {
					"htf_bias": "NEUTRAL",
					"ltf_structure": "NEUTRAL",
					"news_state": "NORMAL",
				},
				"model": {"active_model": "CORE", "confidence": 0.0},
				"risk": {"risk_percent": float(ACCOUNT_CONFIG.get("risk_per_trade_phase1", 0.005)) * 100.0, "phase": "PHASE1"},
				"prop_behavior": {"mode": behavior.get("mode")},
				"basis": {"status": basis_status},
				"resolver": resolver_row,
				"broker_price": broker_price,
				"system_price": futures_price,
				"offset_diff": offset_diff,
				"futures_source": market_data.get("futures_source") or resolver.get("active_symbol"),
				"bridge": quote,
			}
		)

	return {
		"rows": rows,
		"feed": {"healthy": bool(feed_healthy)},
		"timestamp": int(time.time()),
	}


@router.get("/news_severity")
def get_news_severity() -> Any:
	return {
		"halt_active": False,
		"upcoming_title": None,
		"upcoming_currency": None,
		"minutes_to_news": None,
	}


@router.get("/model_stats")
def get_model_stats(symbol: str = "XAUUSD") -> Any:
	try:
		runner = get_runner()
		stats = dict(getattr(runner.state, "model_performance", {}) or {})
		if stats:
			return stats
	except Exception:
		pass
	return {"CORE": {"wins": 0, "losses": 0}}


@router.get("/journal")
def get_journal(symbol: str = "XAUUSD", limit: int = 120) -> Any:
	rows = []
	journal_path = "ai_trade_journal.db"
	if not os.path.exists(journal_path):
		return rows
	try:
		conn = sqlite3.connect(journal_path)
		try:
			cur = conn.cursor()
			cur.execute(
				"""
				SELECT timestamp, symbol, model, result, pnl, r_multiple, narrative
				FROM trades
				WHERE UPPER(COALESCE(symbol, '')) = ?
				ORDER BY id DESC
				LIMIT ?
				""",
				(str(symbol or "").upper(), max(1, min(int(limit or 120), 500))),
			)
			for row in cur.fetchall() or []:
				ts = row[0]
				try:
					if ts:
						ts = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
				except Exception:
					pass
				rows.append([
					ts,
					row[1],
					row[2],
					row[3],
					float(row[4] or 0.0),
					float(row[5] or 0.0),
					row[6],
				])
		finally:
			conn.close()
	except Exception:
		return []
	return rows


@router.get("/prop/auto_behavior")
def get_prop_auto_behavior(symbol: str = "XAUUSD") -> Any:
	canonical = normalize_runtime_symbol(symbol)
	profile, override = _compute_auto_behavior(
		symbol=canonical,
		equity=float(ACCOUNT_CONFIG.get("initial_balance", 50000.0)),
		daily_loss=0.0,
		drawdown=0.0,
	)
	return {
		"symbol": canonical,
		"behavior": profile,
		"override": override,
	}


@router.post("/prop/auto_behavior/simulate")
def simulate_prop_auto_behavior(payload: dict) -> Any:
	canonical = normalize_runtime_symbol(str((payload or {}).get("symbol") or "XAUUSD"))
	phase = str((payload or {}).get("phase") or "PHASE1")
	volatility_mode = str((payload or {}).get("volatility_mode") or "NORMAL")
	news_mode = str((payload or {}).get("news_mode") or "NORMAL")
	equity = float((payload or {}).get("equity") or ACCOUNT_CONFIG.get("initial_balance", 50000.0))
	daily_loss = float((payload or {}).get("daily_loss") or 0.0)
	drawdown = float((payload or {}).get("drawdown") or 0.0)

	base_profile, _ = _compute_auto_behavior(
		symbol=canonical,
		equity=equity,
		daily_loss=daily_loss,
		drawdown=drawdown,
		phase=phase,
		volatility_mode=volatility_mode,
		news_mode=news_mode,
	)
	return {
		"status": "OK",
		"symbol": canonical,
		"simulated": base_profile,
		"simulated_with_override": base_profile,
	}


@router.post("/prop/auto_behavior/override")
def set_prop_auto_behavior_override(payload: dict) -> Any:
	canonical = normalize_runtime_symbol(str((payload or {}).get("symbol") or "XAUUSD"))
	expires_minutes = max(1, min(int((payload or {}).get("expires_minutes") or 15), 24 * 60))
	mode = str((payload or {}).get("mode") or "BALANCED")
	risk_multiplier = float((payload or {}).get("risk_multiplier") or 1.0)
	hard_block = bool((payload or {}).get("hard_block"))
	reasons = list((payload or {}).get("reasons") or [])

	entry = {
		"mode": mode,
		"risk_multiplier": risk_multiplier,
		"hard_block": hard_block,
		"reasons": reasons,
		"expires_at": time.time() + (expires_minutes * 60),
	}
	_PROP_BEHAVIOR_OVERRIDES[canonical] = entry
	_, override = _compute_auto_behavior(
		symbol=canonical,
		equity=float(ACCOUNT_CONFIG.get("initial_balance", 50000.0)),
		daily_loss=0.0,
		drawdown=0.0,
	)
	return {
		"status": "OK",
		"symbol": canonical,
		"override": override,
	}


@router.post("/prop/auto_behavior/override/clear")
def clear_prop_auto_behavior_override(payload: dict | None = None) -> Any:
	symbol = str((payload or {}).get("symbol") or "XAUUSD")
	canonical = normalize_runtime_symbol(symbol)
	_PROP_BEHAVIOR_OVERRIDES.pop(canonical, None)
	_, override = _compute_auto_behavior(
		symbol=canonical,
		equity=float(ACCOUNT_CONFIG.get("initial_balance", 50000.0)),
		daily_loss=0.0,
		drawdown=0.0,
	)
	return {
		"status": "OK",
		"symbol": canonical,
		"override": override,
	}

# --- Symbol search/autocomplete endpoint ---
import json
from pathlib import Path

@router.get("/symbols")
def get_symbols(q: str = "", include_all: bool = False):
	"""
	Returns a list of symbols and metadata for search/autocomplete.
	Optional query param 'q' filters by symbol or description substring (case-insensitive).
	"""
	symbol_map_path = Path(__file__).parent.parent / "data/databento_symbol_map.json"
	try:
		with open(symbol_map_path, "r") as f:
			symbol_map = json.load(f)
	except Exception as e:
		return {"error": f"Failed to load symbol map: {e}"}

	q_lower = q.strip().lower()

	# Return permanent trading universe by default for UI stability.
	if not include_all:
		canonical = [
			{"key": "AQ.GC.FUT", "symbol": "GC.FUT", "exchange": "CME", "description": "COMEX Gold Futures Front Contract", "type": "futures", "priority": -10},
			{"key": "AQ.NQ.FUT", "symbol": "NQ.FUT", "exchange": "CME", "description": "Nasdaq 100 Futures Front Contract", "type": "futures", "priority": -9},
			{"key": "AQ.6E.FUT", "symbol": "6E.FUT", "exchange": "CME", "description": "Euro FX Futures Front Contract", "type": "futures", "priority": -8},
			{"key": "AQ.YM.FUT", "symbol": "YM.FUT", "exchange": "CBOT", "description": "Dow Futures Front Contract", "type": "futures", "priority": -7},
		]
		if q_lower:
			canonical = [
				row for row in canonical
				if (
					q_lower in row["key"].lower()
					or q_lower in row["symbol"].lower()
					or q_lower in row["exchange"].lower()
					or q_lower in row["description"].lower()
				)
			]
		return {"symbols": canonical}

	results = []
	for key, meta in symbol_map.items():
		symbol_value = str(meta.get("symbol", ""))
		exchange_value = str(meta.get("exchange", ""))
		desc_value = str(meta.get("description", ""))
		if (
			not q_lower
			or q_lower in key.lower()
			or q_lower in symbol_value.lower()
			or q_lower in exchange_value.lower()
			or q_lower in desc_value.lower()
		):
			results.append({
				"key": key,
				"symbol": symbol_value or key,
				"exchange": exchange_value,
				"description": desc_value,
				"type": meta.get("type", ""),
				"priority": meta.get("priority", 0)
			})

	# Canonical trading symbols used by chart/mentor paths.
	canonical = [
		{"key": "AQ.GC.FUT", "symbol": "GC.FUT", "exchange": "CME", "description": "COMEX Gold Futures Front Contract", "type": "futures", "priority": -10},
		{"key": "AQ.NQ.FUT", "symbol": "NQ.FUT", "exchange": "CME", "description": "Nasdaq 100 Futures Front Contract", "type": "futures", "priority": -9},
		{"key": "AQ.6E.FUT", "symbol": "6E.FUT", "exchange": "CME", "description": "Euro FX Futures Front Contract", "type": "futures", "priority": -8},
		{"key": "AQ.YM.FUT", "symbol": "YM.FUT", "exchange": "CBOT", "description": "Dow Futures Front Contract", "type": "futures", "priority": -7},
	]
	for row in canonical:
		if (
			not q_lower
			or q_lower in row["key"].lower()
			or q_lower in row["symbol"].lower()
			or q_lower in row["exchange"].lower()
			or q_lower in row["description"].lower()
		):
			results.append(row)

	# Deduplicate by symbol so canonical entries cleanly override weak map entries.
	unique = {}
	for row in results:
		symbol_key = str(row.get("symbol") or "").upper()
		if not symbol_key:
			continue
		prev = unique.get(symbol_key)
		if prev is None or int(row.get("priority", 0)) < int(prev.get("priority", 0)):
			unique[symbol_key] = row
	results = list(unique.values())

	# Permanent policy: hide BTC/MBT instruments from trading symbol autocomplete.
	blocked = {"BTC", "BTC.FUT", "MBT", "MBT.FUT"}
	results = [row for row in results if str(row.get("symbol") or "").upper() not in blocked]
	# Sort by priority, then symbol
	results.sort(key=lambda x: (x["priority"], x["symbol"]))
	return {"symbols": results}
