from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from astroquant.backend.execution.execution_guard import ExecutionGuard
from astroquant.backend.router_admin import build_admin_router
from astroquant.core.prop_profiles import PROP_PROFILES


class _DummyPlaywright:
	def __init__(self):
		self.slippage_limit = 0.5
		self.timeout_seconds = 10
		self.execution_guard = ExecutionGuard()


class _DummyExecution:
	def __init__(self):
		self.playwright = _DummyPlaywright()

	def execution_health(self):
		return {"execution_status": "OK"}

	def emergency_halt(self, _reason):
		self.playwright.execution_guard.halt(_reason)


class _DummyRisk:
	def __init__(self):
		self.max_lot_size = 10.0
		self.max_risk_per_trade = 0.01
		self.daily_loss_limit = 0.0
		self.max_drawdown_floor = 0.0


class _DummyRunner:
	def __init__(self):
		self.execution = _DummyExecution()
		self.risk = _DummyRisk()
		self.trade_cooldown_seconds = 300
		self.max_trades_per_day_limit = 20
		self.max_concurrent_trades_limit = 2
		self.max_spread_limit = 2.5
		self.phase_risk_multipliers = {"PHASE1": 1.0, "PHASE2": 1.0, "FUNDED": 1.0}
		self.engine_enable_flags = {"ICT": True, "ICEBERG": True, "GANN": True, "ASTRO": True}
		self.min_confidence_threshold = 55.0
		self.confluence_threshold = 0.5
		self.disabled_symbols = set()
		self.auto_trading_enabled = True
		self.strict_challenge_mode = True


class _DummyPropEngine:
	def __init__(self):
		self.phase = "PHASE1"
		self.config = SimpleNamespace(account_size=50000.0, internal_daily_guard_pct=0.015, static_dd_pct=0.08)
		self.phase_target_pct = 0.08
		self.min_profitable_days = 3
		self.funded_lock_level = 0.0
		self.static_floor = 0.0

	def apply_account_size(self, size):
		self.config.account_size = float(size)


def _client():
	app = FastAPI()
	runner = _DummyRunner()
	prop_engine = _DummyPropEngine()
	app.include_router(build_admin_router(runner, prop_engine, admin_token="test-token", default_role="ADMIN"))
	return TestClient(app)


def test_prop_profiles_include_5k_to_100k():
	sizes = {int(v["account_size"]) for v in PROP_PROFILES.values()}
	assert {5000, 10000, 15000, 20000, 25000, 30000, 50000, 100000}.issubset(sizes)


def test_challenge_bootstrap_accepts_5k_to_100k_profiles():
	client = _client()
	headers = {"x-admin-token": "test-token", "x-admin-role": "ADMIN"}

	for size in [5000, 10000, 25000, 50000, 100000]:
		r = client.post("/admin/control/challenge/bootstrap", json={"account_size": size, "strict_mode": True}, headers=headers)
		assert r.status_code == 200
		assert int(r.json()["account_size"]) == size


def test_challenge_bootstrap_rejects_unsupported_account_size():
	client = _client()
	headers = {"x-admin-token": "test-token", "x-admin-role": "ADMIN"}

	r = client.post("/admin/control/challenge/bootstrap", json={"account_size": 12345, "strict_mode": True}, headers=headers)
	assert r.status_code == 400
	assert "Supported account_size values" in r.json()["detail"]


def test_execution_guard_rejects_missing_or_invalid_sl_tp():
	guard = ExecutionGuard()

	ok, reason = guard.validate_sl_tp(None, 100.0, 90.0)
	assert ok is False
	assert reason == "SL or TP missing"

	ok, reason = guard.validate_sl_tp(90.0, 100.0, 90.0)
	assert ok is False
	assert reason == "Invalid SL/TP"


def test_maven_execution_engine_contains_core_bridge_markers():
	with open("astroquant/backend/router_status.py", "r", encoding="utf-8") as f:
		text = f.read()

	assert "manager.maven.markets/app/trade" in text
	assert "broker_bridge" in text
