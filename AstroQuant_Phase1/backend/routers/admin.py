
from fastapi import APIRouter, Depends, HTTPException, Query
router = APIRouter()
import os
from backend.security import require_admin_key
from pydantic import BaseModel, Field

@router.get("/auto-trading/status")
def auto_trading_status():
    global trader
    if trader and trader.running:
        return {"status": "Running"}
    return {"status": "Stopped"}

from backend.simulation.stress_engine import StressEngine
from backend.risk.prop_mode_lock import PropModeLock
from backend.multi_symbol_trader import MultiSymbolTrader
from execution.execution_manager import get_execution_manager
import threading

prop_lock = PropModeLock()
trader = None
trader_thread = None
execution_manager = get_execution_manager()
model_override_state = {
    "mode": "NORMAL",
    "min_confidence": execution_manager.governance.min_confidence_required,
}


class ManualTradeRequest(BaseModel):
    symbol: str = Field(default="XAUUSD")
    direction: str = Field(default="BUY")
    confidence: int = Field(default=75, ge=0, le=100)
    risk_percent: float = Field(default=0.2, ge=0.0, le=3.0)
    allow_concurrent: bool = Field(default=False)


class BroadcastAlertRequest(BaseModel):
    message: str = Field(min_length=3, max_length=500)
    severity: str = Field(default="INFO")


class ModelOverrideRequest(BaseModel):
    mode: str = Field(default="NORMAL")


@router.get("/execution/status")
def execution_status():
    browser_connected = False
    if trader and hasattr(trader, "running"):
        browser_connected = bool(trader.running)
    return {"browser_connected": browser_connected}


@router.get("/telegram/status")
def telegram_status():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    return {"active": bool(token and chat)}


@router.get("/clawbot/status")
def clawbot_status():
    return {"active": True}


@router.get("/engine/health")
def engine_health():
    cpu_count = os.cpu_count() or 1
    load_1m = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0
    cpu_percent = round(min((load_1m / cpu_count) * 100, 100), 1)

    mem_total_kb = 0
    mem_available_kb = 0
    try:
        with open("/proc/meminfo", "r") as file:
            for line in file:
                if line.startswith("MemTotal:"):
                    mem_total_kb = int(line.split()[1])
                if line.startswith("MemAvailable:"):
                    mem_available_kb = int(line.split()[1])
        if mem_total_kb > 0:
            used_ratio = 1 - (mem_available_kb / mem_total_kb)
            ram_percent = round(max(0, min(used_ratio * 100, 100)), 1)
        else:
            ram_percent = 0
    except Exception:
        ram_percent = 0

    return {"cpu": cpu_percent, "ram": ram_percent, "feed": "Live"}


@router.get("/broker-feed/status")
def broker_feed_status(_auth: None = Depends(require_admin_key)):
    return execution_manager.get_broker_feed_status()


@router.get("/broker-brain/status")
def broker_brain_status(_auth: None = Depends(require_admin_key)):
    return execution_manager.get_broker_brain_status()


@router.get("/broker-feed/recent")
def broker_feed_recent(limit: int = Query(20, ge=1, le=200), _auth: None = Depends(require_admin_key)):
    return {
        "count": limit,
        "items": execution_manager.get_broker_feed_recent(limit=limit),
    }

@router.post("/set-phase/{phase}")
def set_phase(phase: str, _auth: None = Depends(require_admin_key)):
    success = prop_lock.set_phase(phase)
    return {"success": success, "active_phase": prop_lock.phase}

@router.get("/stress-test")
def stress_test(_auth: None = Depends(require_admin_key)):
    engine = StressEngine()
    result = engine.run()
    return result

@router.post("/auto-trading/start")
def start_auto_trading(_auth: None = Depends(require_admin_key)):
    global trader, trader_thread
    if trader and trader.running:
        return {"status": "Already running"}
    trader = MultiSymbolTrader()
    trader_thread = threading.Thread(target=trader.run, daemon=True)
    trader_thread.start()
    return {"status": "Started"}

@router.post("/auto-trading/stop")
def stop_auto_trading(_auth: None = Depends(require_admin_key)):
    global trader
    if trader:
        trader.stop()
        return {"status": "Stopped"}
    return {"status": "Not running"}


@router.post("/manual-trade")
def manual_trade(request: ManualTradeRequest, _auth: None = Depends(require_admin_key)):
    direction = str(request.direction or "").strip().upper()
    if direction not in {"BUY", "SELL"}:
        raise HTTPException(status_code=400, detail="direction must be BUY or SELL")

    signal = {
        "direction": direction,
        "confidence": int(request.confidence),
        "risk_percent": float(request.risk_percent),
        "sentiment": 65 if direction == "BUY" else -65,
    }

    try:
        success = bool(
            execution_manager.execute_trade(
                signal,
                symbol=request.symbol,
                allow_concurrent=bool(request.allow_concurrent),
            )
        )
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"manual trade failed: {error}") from error

    return {
        "status": "executed" if success else "blocked",
        "symbol": request.symbol,
        "direction": direction,
        "confidence": int(request.confidence),
    }


@router.post("/alerts/broadcast")
def alerts_broadcast(request: BroadcastAlertRequest, _auth: None = Depends(require_admin_key)):
    severity = str(request.severity or "INFO").strip().upper()
    if severity not in {"INFO", "WARN", "CRITICAL"}:
        severity = "INFO"

    message = str(request.message).strip()
    formatted = f"📣 Operator Alert [{severity}]\n{message}"
    execution_manager.telegram.send(formatted)

    return {
        "status": "sent",
        "severity": severity,
        "length": len(message),
    }


@router.post("/model-override")
def model_override(request: ModelOverrideRequest, _auth: None = Depends(require_admin_key)):
    mode = str(request.mode or "NORMAL").strip().upper()
    mode_thresholds = {
        "SAFE": 65,
        "NORMAL": 55,
        "AGGRESSIVE": 45,
    }
    if mode not in mode_thresholds:
        raise HTTPException(status_code=400, detail="mode must be SAFE, NORMAL, or AGGRESSIVE")

    threshold = int(mode_thresholds[mode])
    execution_manager.governance.min_confidence_required = threshold

    model_override_state["mode"] = mode
    model_override_state["min_confidence"] = threshold

    return {
        "status": "updated",
        "mode": mode,
        "min_confidence": threshold,
    }


@router.get("/model-override/status")
def model_override_status(_auth: None = Depends(require_admin_key)):
    return {
        "mode": model_override_state.get("mode", "NORMAL"),
        "min_confidence": int(execution_manager.governance.min_confidence_required),
    }
