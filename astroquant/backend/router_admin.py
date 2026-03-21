# Minimal placeholder router for admin endpoints
from fastapi import APIRouter
router = APIRouter(prefix="/admin", tags=["admin"])
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from astroquant.backend.admin_control_store import AdminControlStore


ROLE_ORDER = {
	"VIEWER": 1,
	"OPERATOR": 2,
	"ADMIN": 3,
	"SUPERADMIN": 4,
}


class UserUpsertRequest(BaseModel):
	username: str = Field(min_length=2, max_length=64)
	role: str = Field(default="VIEWER")
	phase: str = Field(default="PHASE1")
	auto_trading_enabled: bool = Field(default=True)
	risk_multiplier: float = Field(default=1.0, ge=0.0, le=5.0)
	banned: bool = Field(default=False)


class UserBanRequest(BaseModel):
	username: str = Field(min_length=2, max_length=64)
	banned: bool = Field(default=True)


class PropRulesRequest(BaseModel):
	profit_target_pct: float = Field(ge=0.1, le=100.0)
	daily_dd_pct: float = Field(ge=0.1, le=50.0)
	overall_dd_pct: float = Field(ge=0.1, le=90.0)
	lock_level: float = Field(ge=0.0)
	min_profitable_days: int = Field(ge=1, le=365)
	leverage_limit: float = Field(ge=1.0, le=500.0)


class EngineControlsRequest(BaseModel):
	ict_enabled: bool = True
	iceberg_enabled: bool = True
	gann_enabled: bool = True
	astro_enabled: bool = True
	confluence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
	confidence_threshold: float = Field(default=55.0, ge=0.0, le=100.0)


class ExecutionControlsRequest(BaseModel):
	spread_max_limit: float = Field(default=2.5, ge=0.0, le=100.0)
	slippage_tolerance: float = Field(default=0.5, ge=0.0, le=100.0)
	cooldown_seconds: int = Field(default=300, ge=0, le=86400)
	max_trades_per_day: int = Field(default=20, ge=1, le=2000)
	max_concurrent_trades: int = Field(default=2, ge=1, le=100)
	execution_timeout_seconds: int = Field(default=10, ge=1, le=600)


class RiskLimitsRequest(BaseModel):
	max_lot_size: float = Field(default=10.0, ge=0.01, le=1000.0)
	max_risk_per_trade: float = Field(default=1.0, ge=0.01, le=10.0)
	daily_max_trades: int = Field(default=20, ge=1, le=2000)
	risk_multiplier_phase1: float = Field(default=1.0, ge=0.0, le=5.0)
	risk_multiplier_phase2: float = Field(default=1.0, ge=0.0, le=5.0)
	risk_multiplier_funded: float = Field(default=1.0, ge=0.0, le=5.0)


class SymbolActivationRequest(BaseModel):
	symbol: str = Field(min_length=2, max_length=32)
	enabled: bool = True


class EmergencyAutoTradingRequest(BaseModel):
	enabled: bool = True


class ChallengeBootstrapRequest(BaseModel):
	account_size: float = Field(default=50000.0)
	strict_mode: bool = Field(default=True)


def build_admin_router(runner, prop_engine, admin_token: str, default_role: str = "ADMIN"):
	router = APIRouter(prefix="/admin/control", tags=["admin-control"])
	store = AdminControlStore("data/admin_control.db")

	def check_access(
		min_role: str,
		x_admin_token: str | None,
		x_admin_role: str | None,
	) -> str:
		if str(x_admin_token or "").strip() != str(admin_token or "").strip():
			raise HTTPException(status_code=401, detail="Invalid admin token")

		caller_role = str(x_admin_role or default_role or "VIEWER").upper().strip()
		if ROLE_ORDER.get(caller_role, 0) < ROLE_ORDER.get(min_role, 0):
			raise HTTPException(status_code=403, detail=f"{min_role} role required")
		return caller_role

	def actor_name(role: str, x_admin_user: str | None):
		user = str(x_admin_user or "").strip()
		return user if user else role.lower()

	def apply_runtime_controls():
		execution_cfg = store.get_execution_controls()
		risk_cfg = store.get_risk_limits()
		engine_cfg = store.get_engine_controls()
		prop_cfg = store.get_prop_rules()
		symbol_rows = store.get_symbols()

		runner.trade_cooldown_seconds = int(execution_cfg.get("cooldown_seconds") or 300)
		runner.max_trades_per_day_limit = int(execution_cfg.get("max_trades_per_day") or 20)
		runner.max_concurrent_trades_limit = int(execution_cfg.get("max_concurrent_trades") or 2)
		runner.max_spread_limit = float(execution_cfg.get("spread_max_limit") or 2.5)
		runner.execution.playwright.slippage_limit = float(execution_cfg.get("slippage_tolerance") or 0.5)
		runner.execution.playwright.timeout_seconds = int(execution_cfg.get("execution_timeout_seconds") or 10)

		runner.risk.max_lot_size = float(risk_cfg.get("max_lot_size") or 10.0)
		runner.risk.max_risk_per_trade = float(risk_cfg.get("max_risk_per_trade") or 1.0) / 100.0
		runner.risk.daily_loss_limit = float(prop_engine.config.account_size) * (float(prop_cfg.get("daily_dd_pct") or 1.5) / 100.0)
		runner.risk.max_drawdown_floor = float(prop_engine.config.account_size) * (1.0 - (float(prop_cfg.get("overall_dd_pct") or 8.0) / 100.0))
		runner.max_trades_per_day_limit = int(risk_cfg.get("daily_max_trades") or runner.max_trades_per_day_limit)
		runner.phase_risk_multipliers = {
			"PHASE1": float(risk_cfg.get("risk_multiplier_phase1") or 1.0),
			"PHASE2": float(risk_cfg.get("risk_multiplier_phase2") or 1.0),
			"FUNDED": float(risk_cfg.get("risk_multiplier_funded") or 1.0),
		}

		runner.engine_enable_flags = {
			"ICT": bool(engine_cfg.get("ict_enabled", 1)),
			"ICEBERG": bool(engine_cfg.get("iceberg_enabled", 1)),
			"GANN": bool(engine_cfg.get("gann_enabled", 1)),
			"ASTRO": bool(engine_cfg.get("astro_enabled", 1)),
		}
		runner.min_confidence_threshold = float(engine_cfg.get("confidence_threshold") or 55.0)
		runner.confluence_threshold = float(engine_cfg.get("confluence_threshold") or 0.5)

		prop_engine.phase_target_pct = float(prop_cfg.get("profit_target_pct") or 8.0) / 100.0
		prop_engine.config.internal_daily_guard_pct = float(prop_cfg.get("daily_dd_pct") or 1.5) / 100.0
		prop_engine.config.static_dd_pct = float(prop_cfg.get("overall_dd_pct") or 8.0) / 100.0
		prop_engine.min_profitable_days = int(prop_cfg.get("min_profitable_days") or 3)
		prop_engine.funded_lock_level = float(prop_cfg.get("lock_level") or prop_engine.funded_lock_level)
		prop_engine.static_floor = float(prop_engine.config.account_size) * (1.0 - prop_engine.config.static_dd_pct)

		disabled = set()
		for row in symbol_rows:
			if not bool(row.get("enabled")):
				disabled.add(str(row.get("symbol") or "").upper())
		runner.disabled_symbols = disabled

	def governance_snapshot():
		return {
			"users": store.list_users(),
			"prop_rules": store.get_prop_rules(),
			"engine_controls": store.get_engine_controls(),
			"execution_controls": store.get_execution_controls(),
			"risk_limits": store.get_risk_limits(),
			"symbol_activation": store.get_symbols(),
			"runtime": {
				"auto_trading_enabled": bool(getattr(runner, "auto_trading_enabled", True)),
				"disabled_symbols": sorted(list(getattr(runner, "disabled_symbols", set()))),
				"engine_flags": getattr(runner, "engine_enable_flags", {}),
				"execution_halted": str(runner.execution.execution_health().get("execution_status", "OK")).upper() == "HALTED",
			},
		}

	apply_runtime_controls()

	@router.get("/state")
	def admin_state(
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
	):
		check_access("VIEWER", x_admin_token, x_admin_role)
		return governance_snapshot()

	@router.get("/users")
	def list_users(
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
	):
		check_access("VIEWER", x_admin_token, x_admin_role)
		return {"items": store.list_users()}

	@router.post("/users/upsert")
	def upsert_user(
		data: UserUpsertRequest,
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
		x_admin_user: str | None = Header(default=None),
	):
		role = check_access("ADMIN", x_admin_token, x_admin_role)
		store.upsert_user(
			username=data.username,
			role=data.role,
			phase=data.phase,
			auto_trading_enabled=data.auto_trading_enabled,
			risk_multiplier=data.risk_multiplier,
			banned=data.banned,
		)
		store.audit("USER", "UPSERT", actor_name(role, x_admin_user), data.model_dump())
		return {"status": "ok", "user": data.username}

	@router.post("/users/ban")
	def ban_user(
		data: UserBanRequest,
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
		x_admin_user: str | None = Header(default=None),
	):
		role = check_access("ADMIN", x_admin_token, x_admin_role)
		updated = store.set_user_ban(data.username, data.banned)
		store.audit("USER", "BAN" if data.banned else "UNBAN", actor_name(role, x_admin_user), data.model_dump())
		return {"status": "ok" if updated else "not_found", "username": data.username, "banned": data.banned}

	@router.get("/prop_rules")
	def get_prop_rules(
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
	):
		check_access("VIEWER", x_admin_token, x_admin_role)
		return store.get_prop_rules()

	@router.post("/prop_rules")
	def set_prop_rules(
		data: PropRulesRequest,
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
		x_admin_user: str | None = Header(default=None),
	):
		role = check_access("ADMIN", x_admin_token, x_admin_role)
		store.upsert_singleton("prop_rules", data.model_dump())
		apply_runtime_controls()
		store.audit("PROP_RULE", "UPDATE", actor_name(role, x_admin_user), data.model_dump())
		return {"status": "updated", "rules": store.get_prop_rules()}

	@router.get("/engine_controls")
	def get_engine_controls(
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
	):
		check_access("VIEWER", x_admin_token, x_admin_role)
		return store.get_engine_controls()

	@router.post("/engine_controls")
	def set_engine_controls(
		data: EngineControlsRequest,
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
		x_admin_user: str | None = Header(default=None),
	):
		role = check_access("ADMIN", x_admin_token, x_admin_role)
		store.upsert_singleton("engine_controls", data.model_dump())
		apply_runtime_controls()
		store.audit("ENGINE_CTRL", "UPDATE", actor_name(role, x_admin_user), data.model_dump())
		return {"status": "updated", "controls": store.get_engine_controls()}

	@router.get("/execution_controls")
	def get_execution_controls(
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
	):
		check_access("VIEWER", x_admin_token, x_admin_role)
		return store.get_execution_controls()

	@router.post("/execution_controls")
	def set_execution_controls(
		data: ExecutionControlsRequest,
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
		x_admin_user: str | None = Header(default=None),
	):
		role = check_access("ADMIN", x_admin_token, x_admin_role)
		store.upsert_singleton("execution_controls", data.model_dump())
		apply_runtime_controls()
		store.audit("EXEC_CTRL", "UPDATE", actor_name(role, x_admin_user), data.model_dump())
		return {"status": "updated", "controls": store.get_execution_controls()}

	@router.get("/risk_limits")
	def get_risk_limits(
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
	):
		check_access("VIEWER", x_admin_token, x_admin_role)
		return store.get_risk_limits()

	@router.post("/risk_limits")
	def set_risk_limits(
		data: RiskLimitsRequest,
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
		x_admin_user: str | None = Header(default=None),
	):
		role = check_access("ADMIN", x_admin_token, x_admin_role)
		store.upsert_singleton("risk_limits", data.model_dump())
		apply_runtime_controls()
		store.audit("RISK_LIMIT", "UPDATE", actor_name(role, x_admin_user), data.model_dump())
		return {"status": "updated", "limits": store.get_risk_limits()}

	@router.get("/symbols")
	def list_symbols(
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
	):
		check_access("VIEWER", x_admin_token, x_admin_role)
		return {"items": store.get_symbols()}

	@router.post("/symbols")
	def set_symbol_activation(
		data: SymbolActivationRequest,
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
		x_admin_user: str | None = Header(default=None),
	):
		role = check_access("ADMIN", x_admin_token, x_admin_role)
		symbol = str(data.symbol).upper().strip()
		store.set_symbol(symbol, data.enabled)
		apply_runtime_controls()
		store.audit("SYMBOL", "ENABLE" if data.enabled else "DISABLE", actor_name(role, x_admin_user), data.model_dump())
		return {"status": "updated", "symbol": symbol, "enabled": data.enabled}

	@router.post("/emergency/kill")
	def emergency_kill(
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
		x_admin_user: str | None = Header(default=None),
	):
		role = check_access("OPERATOR", x_admin_token, x_admin_role)
		runner.execution.emergency_halt("Emergency kill switch activated by operator")
		runner.auto_trading_enabled = False
		store.audit("EMERGENCY", "KILL_SWITCH", actor_name(role, x_admin_user), {"ts": int(datetime.now(timezone.utc).timestamp())})
		return {"status": "halted", "auto_trading_enabled": False}

	@router.post("/emergency/restart_execution")
	def emergency_restart_execution(
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
		x_admin_user: str | None = Header(default=None),
	):
		role = check_access("OPERATOR", x_admin_token, x_admin_role)
		runner.execution.playwright.execution_guard.reset()
		runner.auto_trading_enabled = True
		store.audit("EMERGENCY", "RESTART_EXECUTION", actor_name(role, x_admin_user), {"ts": int(datetime.now(timezone.utc).timestamp())})
		return {"status": "restarted", "auto_trading_enabled": True}

	@router.post("/emergency/auto_trading")
	def emergency_auto_trading(
		data: EmergencyAutoTradingRequest,
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
		x_admin_user: str | None = Header(default=None),
	):
		role = check_access("OPERATOR", x_admin_token, x_admin_role)
		runner.auto_trading_enabled = bool(data.enabled)
		action = "ENABLE_AUTO_TRADING" if data.enabled else "DISABLE_AUTO_TRADING"
		store.audit("EMERGENCY", action, actor_name(role, x_admin_user), data.model_dump())
		return {"status": "ok", "auto_trading_enabled": bool(data.enabled)}

	@router.post("/enforce/reload")
	def reload_enforcement(
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
	):
		check_access("ADMIN", x_admin_token, x_admin_role)
		apply_runtime_controls()
		return {"status": "reloaded", "runtime": governance_snapshot().get("runtime", {})}

	@router.post("/challenge/bootstrap")
	def challenge_bootstrap(
		data: ChallengeBootstrapRequest,
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
		x_admin_user: str | None = Header(default=None),
	):
		role = check_access("ADMIN", x_admin_token, x_admin_role)

		account_size = float(data.account_size)
		if account_size not in {20000.0, 50000.0}:
			raise HTTPException(status_code=400, detail="Supported account_size values: 20000 or 50000")

		if hasattr(prop_engine, "apply_account_size"):
			prop_engine.apply_account_size(account_size)

		phase = str(getattr(prop_engine, "phase", "PHASE1") or "PHASE1").upper()
		phase_target = 8.0 if phase == "PHASE1" else (5.0 if phase == "PHASE2" else 0.0)
		lock_level = round(account_size * 1.04, 2)

		store.upsert_singleton("prop_rules", {
			"profit_target_pct": phase_target,
			"daily_dd_pct": 2.0 if phase != "FUNDED" else 2.5,
			"overall_dd_pct": 8.0,
			"lock_level": lock_level,
			"min_profitable_days": 3,
			"leverage_limit": 20.0,
		})

		store.upsert_singleton("engine_controls", {
			"ict_enabled": True,
			"iceberg_enabled": True,
			"gann_enabled": True,
			"astro_enabled": False,
			"confluence_threshold": 0.5,
			"confidence_threshold": 75.0 if phase == "PHASE1" else (77.0 if phase == "PHASE2" else 72.0),
		})

		store.upsert_singleton("execution_controls", {
			"spread_max_limit": 2.5,
			"slippage_tolerance": 0.5,
			"cooldown_seconds": 300,
			"max_trades_per_day": 3 if phase == "PHASE1" else 2,
			"max_concurrent_trades": 1,
			"execution_timeout_seconds": 10,
		})

		store.upsert_singleton("risk_limits", {
			"max_lot_size": 10.0,
			"max_risk_per_trade": 0.5 if phase == "PHASE1" else (0.4 if phase == "PHASE2" else 0.6),
			"daily_max_trades": 3 if phase == "PHASE1" else 2,
			"risk_multiplier_phase1": 1.0,
			"risk_multiplier_phase2": 1.0,
			"risk_multiplier_funded": 1.0,
		})

		runner.strict_challenge_mode = bool(data.strict_mode)
		apply_runtime_controls()
		payload = {
			"phase": phase,
			"account_size": account_size,
			"strict_mode": bool(runner.strict_challenge_mode),
			"max_trades_per_day": int(runner.max_trades_per_day_limit),
			"confidence_threshold": float(runner.min_confidence_threshold),
		}
		store.audit("CHALLENGE", "BOOTSTRAP", actor_name(role, x_admin_user), payload)
		return {"status": "ok", **payload}

	@router.get("/audit")
	def audit_log(
		limit: int = Query(default=200, ge=1, le=1000),
		category: str | None = Query(default=None),
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
	):
		check_access("VIEWER", x_admin_token, x_admin_role)
		return {"items": store.list_audit(limit=limit, category=category)}

	@router.get("/risk_violations")
	def risk_violations(
		limit: int = Query(default=100, ge=1, le=1000),
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
	):
		check_access("VIEWER", x_admin_token, x_admin_role)
		return {"items": store.list_audit(limit=limit, category="RISK_VIOLATION")}

	@router.get("/rejected_trades")
	def rejected_trades(
		limit: int = Query(default=100, ge=1, le=1000),
		x_admin_token: str | None = Header(default=None),
		x_admin_role: str | None = Header(default=None),
	):
		check_access("VIEWER", x_admin_token, x_admin_role)
		return {"items": store.list_audit(limit=limit, category="REJECTED_TRADE")}

	return router
