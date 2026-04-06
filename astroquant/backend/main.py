from dotenv import load_dotenv
import os
import logging
import threading
import time as _time
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")



from astroquant.backend import router_market, router_status, router_admin, router_market_causality
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
    if not admin_secure:
        blockers.append("ADMIN_API_TOKEN must be configured with a secure non-default value")
    if not mentor_secure:
        blockers.append("MENTOR_ADMIN_PASSWORD must be configured with a secure non-default value")
    if not databento_configured:
        blockers.append("DATABENTO_API_KEY must be configured")

    running_in_production = _is_production_env()

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
        "running_in_production": running_in_production,
        "startup_blocked_now": bool(running_in_production and blockers),
    }


def _ensure_secure_runtime_for_production() -> None:
    posture = _security_posture()
    if _is_production_env() and posture.get("production_blockers"):
        reasons = "; ".join(posture.get("production_blockers") or [])
        raise RuntimeError(f"Production startup blocked: {reasons}")


_ensure_secure_runtime_for_production()


# ── Live candle CSV updater ────────────────────────────────────────────────────
# Runs in a background thread; fetches new completed candles from Databento
# Historical API and appends them to XAU_1h, XAU_4h, and XAU_1d CSV files so
# the MCL dashboard chart always reflects the latest XAUUSD price action.

_DATA_DIR = BASE_DIR.parent / "market-causality-lab" / "data"

def _update_csv_candles() -> None:
    """Fetch any new completed candles from Databento and append to CSV files."""
    import shutil
    import pandas as _pd
    try:
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        import databento as _db

        _api_key = str(os.getenv("DATABENTO_API_KEY", "")).strip()
        if not _api_key:
            return

        # Stay 2h behind now to avoid Databento available-end errors
        _end = _dt.now(_tz.utc) - _td(hours=2)

        # ── 1h ────────────────────────────────────────────────────────────────
        _f1h = _DATA_DIR / "XAU_1h_data.csv"
        _old1h = _pd.read_csv(_f1h, sep=";")
        _old1h["time"] = _pd.to_datetime(_old1h["Date"], format="%Y.%m.%d %H:%M", utc=True)
        _last1h = _old1h["time"].max()

        if _last1h is not None and _pd.notna(_last1h) and (_end - _last1h).total_seconds() >= 3600:
            _start = (_last1h + _td(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            _client = _db.Historical(_api_key)
            _raw = _client.timeseries.get_range(
                dataset="GLBX.MDP3",
                symbols=["GC.c.0"],
                stype_in="continuous",
                schema="ohlcv-1h",
                start=_start,
                end=_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            _new = _raw.to_df().reset_index().rename(columns={"ts_event": "time"})
            _new["time"] = _pd.to_datetime(_new["time"], utc=True)
            _new = _new[["time", "open", "high", "low", "close", "volume"]].dropna(subset=["time", "close"])
            # Scale fixed-point prices if needed
            if not _new.empty and float(_new["close"].iloc[0]) > 100000:
                for _c in ("open", "high", "low", "close"):
                    _new[_c] = _new[_c] / 1e9
            _new = _new[_new["time"] > _last1h]
            if not _new.empty:
                shutil.copy(_f1h, str(_f1h) + ".bak")
                _old1h_norm = _old1h.rename(
                    columns={"Date": "Date", "Open": "open", "High": "high",
                             "Low": "low", "Close": "close", "Volume": "volume"}
                )
                _combined = _pd.concat([_old1h_norm, _new], ignore_index=True)
                _combined = (_combined.sort_values("time")
                                      .drop_duplicates(subset=["time"])
                                      .reset_index(drop=True))
                _combined["Date"] = _combined["time"].dt.strftime("%Y.%m.%d %H:%M")
                _combined[["Date", "open", "high", "low", "close", "volume"]].rename(
                    columns={"open": "Open", "high": "High", "low": "Low",
                             "close": "Close", "volume": "Volume"}
                ).to_csv(_f1h, sep=";", index=False)
                logging.info("[candle_updater] 1h: appended %d rows, last=%s",
                             len(_new), _combined["Date"].iloc[-1])

                # ── 4h (resample from new 1h rows) ────────────────────────────
                _f4h = _DATA_DIR / "XAU_4h_data.csv"
                _old4h = _pd.read_csv(_f4h, sep=";")
                _old4h["time"] = _pd.to_datetime(_old4h["Date"], format="%Y.%m.%d %H:%M", utc=True)
                _last4h = _old4h["time"].max()

                _new4h_src = _new[_new["time"] > _last4h].copy().set_index("time")
                if not _new4h_src.empty:
                    _new4h = (_new4h_src
                              .resample("4h", closed="left", label="left")
                              .agg(open=("open", "first"), high=("high", "max"),
                                   low=("low", "min"), close=("close", "last"),
                                   volume=("volume", "sum"))
                              .dropna(subset=["open", "close"])
                              .reset_index())
                    # Drop incomplete (last) 4h bar unless it ended before _end
                    _new4h = _new4h[_new4h["time"] + _td(hours=4) <= _end + _td(minutes=30)]
                    if not _new4h.empty:
                        shutil.copy(_f4h, str(_f4h) + ".bak")
                        _old4h_norm = _old4h.rename(
                            columns={"Open": "open", "High": "high",
                                     "Low": "low", "Close": "close", "Volume": "volume"}
                        )
                        _combined4h = _pd.concat([_old4h_norm, _new4h], ignore_index=True)
                        _combined4h = (_combined4h.sort_values("time")
                                                  .drop_duplicates(subset=["time"])
                                                  .reset_index(drop=True))
                        _combined4h["Date"] = _combined4h["time"].dt.strftime("%Y.%m.%d %H:%M")
                        _combined4h[["Date", "open", "high", "low", "close", "volume"]].rename(
                            columns={"open": "Open", "high": "High", "low": "Low",
                                     "close": "Close", "volume": "Volume"}
                        ).to_csv(_f4h, sep=";", index=False)
                        logging.info("[candle_updater] 4h: appended %d rows, last=%s",
                                     len(_new4h), _combined4h["Date"].iloc[-1])

                # ── 1d (resample from new 1h rows) ────────────────────────────
                _f1d = _DATA_DIR / "XAU_1d_data.csv"
                _old1d = _pd.read_csv(_f1d, sep=";")
                _old1d["time"] = _pd.to_datetime(_old1d["Date"], format="%Y.%m.%d %H:%M", utc=True)
                _last1d = _old1d["time"].max()

                _new1d_src = _new[_new["time"] > _last1d].copy().set_index("time")
                if not _new1d_src.empty:
                    _new1d = (_new1d_src
                              .resample("1D", closed="left", label="left")
                              .agg(open=("open", "first"), high=("high", "max"),
                                   low=("low", "min"), close=("close", "last"),
                                   volume=("volume", "sum"))
                              .dropna(subset=["open", "close"])
                              .reset_index())
                    # Drop incomplete (today's) 1d bar
                    _new1d = _new1d[_new1d["time"] + _td(days=1) <= _end + _td(hours=1)]
                    # Drop Saturdays
                    _new1d = _new1d[_new1d["time"].dt.dayofweek != 5]
                    if not _new1d.empty:
                        shutil.copy(_f1d, str(_f1d) + ".bak")
                        _old1d_norm = _old1d.rename(
                            columns={"Open": "open", "High": "high",
                                     "Low": "low", "Close": "close", "Volume": "volume"}
                        )
                        _combined1d = _pd.concat([_old1d_norm, _new1d], ignore_index=True)
                        _combined1d = (_combined1d.sort_values("time")
                                                   .drop_duplicates(subset=["time"])
                                                   .reset_index(drop=True))
                        _combined1d["Date"] = _combined1d["time"].dt.strftime("%Y.%m.%d %H:%M")
                        _combined1d[["Date", "open", "high", "low", "close", "volume"]].rename(
                            columns={"open": "Open", "high": "High", "low": "Low",
                                     "close": "Close", "volume": "Volume"}
                        ).to_csv(_f1d, sep=";", index=False)
                        logging.info("[candle_updater] 1d: appended %d rows, last=%s",
                                     len(_new1d), _combined1d["Date"].iloc[-1])

    except Exception as _exc:
        logging.warning("[candle_updater] update skipped: %s", _exc)


def _candle_updater_loop() -> None:
    """Background thread: update CSVs every hour, aligned to the hour boundary."""
    # Wait until the next hour + 5 min (e.g. 14:05) before first update
    _time.sleep(60)  # short initial delay so server is fully up
    while True:
        _update_csv_candles()
        # Sleep until the next hour + 5 minutes
        _now = _time.time()
        _next_hour = ((_now // 3600) + 1) * 3600 + 300   # HH:05:00
        _time.sleep(max(60, _next_hour - _time.time()))


threading.Thread(target=_candle_updater_loop, daemon=True, name="candle_csv_updater").start()
logging.info("[candle_updater] background CSV updater started (runs every hour at HH:05)")

# ── end Live candle CSV updater ───────────────────────────────────────────────


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
app.include_router(router_market_causality.router)
app.include_router(router_status.router)
app.include_router(router_admin.router)
app.include_router(websocket_router)
app.include_router(router_model_weights)
app.include_router(router_spread_offset)
app.include_router(router_export)
app.include_router(router_gann_ws)

logging.info(
    "Core routers mounted: market,status,admin,websocket,model_weights,spread_offset,export,gann_ws"
)

runner = get_runner()
admin_control_enabled = False
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
        admin_control_enabled = True
except Exception:
    logging.exception("Admin router setup failed; admin control routes may be unavailable")

# Register only the external mentor router
from astroquant.backend import router_mentor
app.include_router(router_mentor.router)

posture = _security_posture()
logging.info(
    "Startup security posture: env=%s admin_control_routes_enabled=%s production_ready=%s",
    posture.get("environment"),
    admin_control_enabled,
    posture.get("production_ready"),
)

@app.get("/status/feed")
def feed_status():
    return runner.feed_status()


@app.get("/status/security")
def security_status():
    return _security_posture()

@app.get("/")
def root():
    return RedirectResponse(url="/frontend/", status_code=307)


@app.get("/market_causality_dashboard")
def market_causality_dashboard():
    """
    Serve the Market Causality Lab Intelligence Dashboard.
    
    This provides a professional, standalone frontend for displaying
    comprehensive MCL analysis with AI model integration, drift monitoring,
    and trade-level recommendations.
    
    The dashboard communicates with /market_causality/summary endpoint
    to fetch live analysis data.
    """
    from fastapi.responses import HTMLResponse
    from pathlib import Path
    
    # Load the MCL dashboard HTML from market-causality-lab
    mcl_dashboard_path = Path(__file__).resolve().parent.parent.parent / "market-causality-lab" / "dashboard" / "index.html"
    
    if mcl_dashboard_path.exists():
        with open(mcl_dashboard_path, "r") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        return HTMLResponse(
            content="""
            <html>
                <head>
                    <title>MCL Dashboard - Not Found</title>
                    <style>
                        body { font-family: Arial; padding: 40px; color: #666; }
                        h1 { color: #333; }
                        pre { background: #f5f5f5; padding: 10px; border-radius: 5px; }
                    </style>
                </head>
                <body>
                    <h1>Market Causality Lab Dashboard</h1>
                    <p>The MCL dashboard HTML file was not found.</p>
                    <p>Expected location: market-causality-lab/dashboard/index.html</p>
                    <p>The MCL analysis API is available at:</p>
                    <pre>/market_causality/summary?symbol=XAUUSD&timeframe=1d</pre>
                </body>
            </html>
            """,
            status_code=404
        )
