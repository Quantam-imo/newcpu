from dotenv import load_dotenv
import os
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")



from astroquant.backend import router_market, router_status, router_admin
from astroquant.backend.config import ADMIN_API_TOKEN
from astroquant.backend.config import ACCOUNT_CONFIG
from astroquant.backend.governance.prop_governance import PropConfig, PropGovernance
from astroquant.backend.services.websocket_service import router as websocket_router
from astroquant.backend.router_model_weights import router as router_model_weights
from astroquant.backend.router_spread_offset import router as router_spread_offset
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from astroquant.backend.router_export import router as router_export
from astroquant.backend.router_gann_websocket import router as router_gann_ws
from astroquant.backend.runtime import get_runner


def _is_production_env() -> bool:
    value = str(
        os.getenv("APP_ENV")
        or os.getenv("ENV")
        or os.getenv("ENVIRONMENT")
        or ""
    ).strip().lower()
    return value in {"prod", "production"}


def _security_posture() -> dict:
    env_name = str(
        os.getenv("APP_ENV")
        or os.getenv("ENV")
        or os.getenv("ENVIRONMENT")
        or ""
    ).strip().lower() or "dev"

    admin_token = str(os.getenv("ADMIN_API_TOKEN", "")).strip()
    mentor_password = str(os.getenv("MENTOR_ADMIN_PASSWORD", "")).strip()
    telegram_token = str(os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    telegram_chat_id = str(os.getenv("TELEGRAM_CHAT_ID", "")).strip()
    databento_key = str(os.getenv("DATABENTO_API_KEY", "")).strip()

    admin_secure = bool(admin_token and admin_token != "dev-admin-token")
    mentor_secure = bool(mentor_password and mentor_password != "AQ-ADMIN")
    telegram_configured = bool(telegram_token and telegram_chat_id)
    databento_configured = bool(databento_key)

    blockers = []
    if _is_production_env():
        if not admin_secure:
            blockers.append("ADMIN_API_TOKEN must be configured with a secure non-default value")
        if not mentor_secure:
            blockers.append("MENTOR_ADMIN_PASSWORD must be configured with a secure non-default value")
        if not databento_configured:
            blockers.append("DATABENTO_API_KEY must be configured")

    return {
        "environment": env_name,
        "admin_token_secure": admin_secure,
        "mentor_admin_password_secure": mentor_secure,
        "telegram_configured": telegram_configured,
        "databento_configured": databento_configured,
        "admin_control_routes_enabled": admin_secure,
        "production_startup_guard_active": True,
        "production_ready": len(blockers) == 0,
        "production_blockers": blockers,
    }


def _ensure_secure_runtime_for_production() -> None:
    posture = _security_posture()
    if _is_production_env() and posture.get("production_blockers"):
        reasons = "; ".join(posture.get("production_blockers") or [])
        raise RuntimeError(f"Production startup blocked: {reasons}")


_ensure_secure_runtime_for_production()


app = FastAPI()


class NoCacheStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

# Serve frontend static files automatically
FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/frontend", NoCacheStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8080",
        "http://localhost:8080",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8001",
        "http://localhost:8001",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure router_market is included for /chart/data and /market/orderflow_summary
app.include_router(router_market.router)
app.include_router(router_status.router)
app.include_router(router_admin.router)
app.include_router(websocket_router)
app.include_router(router_model_weights)
app.include_router(router_spread_offset)
app.include_router(router_export)
app.include_router(router_gann_ws)

runner = get_runner()
try:
    if getattr(runner, "prop_engine", None) is None:
        runner.prop_engine = PropGovernance(
            PropConfig(
                account_size=float(ACCOUNT_CONFIG.get("initial_balance", 50000.0)),
                static_dd_pct=float(ACCOUNT_CONFIG.get("max_drawdown", 4000.0)) / max(1.0, float(ACCOUNT_CONFIG.get("initial_balance", 50000.0))),
                daily_dd_pct=float(ACCOUNT_CONFIG.get("daily_limit", 1500.0)) / max(1.0, float(ACCOUNT_CONFIG.get("initial_balance", 50000.0))),
                internal_daily_guard_pct=0.015,
            )
        )
    secure_admin_token = str(ADMIN_API_TOKEN or "").strip()
    if secure_admin_token and secure_admin_token != "dev-admin-token":
        app.include_router(router_admin.build_admin_router(runner, runner.prop_engine, secure_admin_token))
except Exception:
    logging.exception("Admin router setup failed; admin control routes may be unavailable")

# --- Mentor Endpoints (ported from legacy) ---
import types
import sys
from fastapi import Request

# Dynamically load legacy mentor logic
MENTOR_LEGACY_PATH = BASE_DIR / "astroquant" / "backend" / "main.py.legacy.bak"
if MENTOR_LEGACY_PATH.exists():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mentor_legacy", str(MENTOR_LEGACY_PATH))
    mentor_legacy = importlib.util.module_from_spec(spec)
    sys.modules["mentor_legacy"] = mentor_legacy
    spec.loader.exec_module(mentor_legacy)
else:
    mentor_legacy = None



# --- Mentor Endpoints (direct implementation, using APIRouter) ---
from fastapi import APIRouter
from astroquant.backend.ai.mentor_engine import MentorEngine

# Register only the external mentor router
from astroquant.backend import router_mentor
app.include_router(router_mentor.router)

@app.get("/status/feed")
def feed_status():
    return runner.feed_status()


@app.get("/status/security")
def security_status():
    return _security_posture()

@app.get("/")
def root():
    return RedirectResponse(url="/frontend/", status_code=307)
