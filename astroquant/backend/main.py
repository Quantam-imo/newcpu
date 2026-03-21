from dotenv import load_dotenv
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")



from astroquant.backend import router_market, router_status, router_admin
from astroquant.backend.services.websocket_service import router as websocket_router
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# Serve frontend static files automatically
FRONTEND_DIR = BASE_DIR / "astroquant" / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8080",
        "http://localhost:8080",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure router_market is included for /market/orderflow_summary
app.include_router(router_market.router)
app.include_router(router_status.router)
app.include_router(router_admin.router)
app.include_router(websocket_router)

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
    api_key = os.environ.get("DATABENTO_API_KEY")
    status = {
        "configured": bool(api_key),
        "healthy": False,
        "reason": "Missing DATABENTO_API_KEY" if not api_key else "OK",
        "last_error": None,
        "auth_cooldown_seconds": 0
    }
    if api_key:
        import databento as db
        from datetime import datetime, timedelta, timezone
        client = db.Historical(api_key)
        errors = []
        # 1. Try live window (last 5 min)
        try:
            now = datetime.now(timezone.utc)
            start_time = (now - timedelta(minutes=5)).replace(second=0, microsecond=0).isoformat()
            end_time = now.replace(second=0, microsecond=0).isoformat()
            client.timeseries.get_range(
                dataset="GLBX.MDP3",
                schema="ohlcv-1m",
                symbols=["GC.FUT"],
                start=start_time,
                end=end_time
            )
            status["healthy"] = True
            status["reason"] = "Databento API reachable (live window)"
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            error_str = str(e)
            # Special handling for data_start_after_available_end
            if "data_start_after_available_end" in error_str:
                status["healthy"] = False
                status["reason"] = "No recent data available from Databento (live window exceeds available dataset)."
                status["last_error"] = f"Live window: {e}\n{tb}"
                status["no_recent_data"] = True
            else:
                status["healthy"] = False
                status["reason"] = "Databento API error (live window)"
                status["last_error"] = f"Live window: {e}\n{tb}"
            errors.append(f"Live window error: {e}\n{tb}")
        # 2. Try historical window (known-good)
        try:
            hist_start = "2024-03-10T00:00:00+00:00"
            hist_end = "2024-03-10T00:05:00+00:00"
            client.timeseries.get_range(
                dataset="GLBX.MDP3",
                schema="ohlcv-1m",
                symbols=["GC.FUT"],
                start=hist_start,
                end=hist_end
            )
            status["historical_healthy"] = True
            status["historical_reason"] = "Databento API reachable (historical window)"
        except Exception as e:
            tb = traceback.format_exc()
            errors.append(f"Historical window error: {e}\n{tb}")
            status["historical_healthy"] = False
            status["historical_reason"] = f"Databento API error (historical window): {e}"
            status["historical_last_error"] = f"Historical window: {e}\n{tb}"
        if errors:
            status["all_errors"] = errors
    return status

@app.get("/")
def root():
    return {"status": "ok"}
