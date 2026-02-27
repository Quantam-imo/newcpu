
import asyncio
from datetime import datetime, timezone
import warnings

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from backend.routers import market, status, admin
from backend.services.mentor_service import MentorService
from ai.mentor_engine import AIMentor
from execution.execution_manager import get_execution_manager
from execution.symbol_mapper import to_execution_symbol

warnings.filterwarnings(
    "ignore",
    message="remove second argument of ws_handler",
    category=DeprecationWarning,
)


app = FastAPI(title="AstroQuant Phase 1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(status.router)
app.include_router(market.router)
app.include_router(admin.router)

mentor_service = MentorService()
mentor_engine = AIMentor()
execution_manager = get_execution_manager()


@app.get("/mentor/live/{symbol}")
def mentor_live(symbol: str):
    return mentor_service.build(symbol)


@app.get("/ai/mentor")
def get_ai_mentor(symbol: str = Query("GC.FUT")):
    live = mentor_service.build(symbol)
    pressure_label = str(live.get("iceberg", {}).get("pressure", "")).lower()
    buy_pressure = int(live.get("iceberg", {}).get("buy_count", 0) or 0)
    sell_pressure = int(live.get("iceberg", {}).get("sell_count", 0) or 0)

    if buy_pressure == 0 and sell_pressure == 0:
        base_flow = int(live.get("confidence_breakdown", {}).get("OrderFlow", 10) or 10)
        if pressure_label.startswith("buy"):
            buy_pressure = base_flow + 7
            sell_pressure = max(1, base_flow + 2)
        elif pressure_label.startswith("sell"):
            sell_pressure = base_flow + 7
            buy_pressure = max(1, base_flow + 2)
        else:
            buy_pressure = base_flow + 4
            sell_pressure = base_flow + 4

    market_data = {
        "symbol": live.get("symbol", symbol),
        "price": live.get("liquidity", {}).get("equilibrium"),
        "equilibrium": live.get("liquidity", {}).get("equilibrium"),
        "range_low": live.get("liquidity", {}).get("range_low"),
        "range_high": live.get("liquidity", {}).get("range_high"),
        "zone": live.get("liquidity", {}).get("zone"),
        "execution_zone": live.get("liquidity", {}).get("zone"),
        "htf_bias": live.get("context", {}).get("htf_bias"),
        "ltf_structure": live.get("context", {}).get("ltf_structure"),
        "liquidity": live.get("context", {}).get("liquidity"),
        "kill_zone": live.get("context", {}).get("kill_zone"),
    }

    signal_data = {
        "fvg": live.get("context", {}).get("cycle_phase") in ["Expansion", "Impulse"],
        "order_block": live.get("liquidity", {}).get("zone"),
        "breaker": live.get("governance", {}).get("mode"),
        "bos": live.get("context", {}).get("ltf_structure"),
        "absorption": live.get("iceberg", {}).get("zone") not in [None, "No clear zone"],
        "buy_volume": buy_pressure,
        "sell_volume": sell_pressure,
        "institutional_side": "Buy" if str(live.get("iceberg", {}).get("pressure", "")).lower().startswith("buy") else "Sell",
        "pressure": live.get("iceberg", {}).get("pressure"),
        "zone": live.get("iceberg", {}).get("zone"),
        "gann_day_count": live.get("gann", {}).get("day_count"),
        "gann_bar_count": live.get("gann", {}).get("bar_count"),
        "gann_angle": live.get("gann", {}).get("next_cycle"),
        "gann_square": live.get("gann", {}).get("square_level"),
        "astro_cycle": live.get("astro", {}).get("phase"),
        "astro_alignment": live.get("astro", {}).get("window"),
        "astro_phase": live.get("astro", {}).get("phase"),
        "astro_window": live.get("astro", {}).get("window"),
        "news_bias": live.get("news", {}).get("reaction_bias"),
        "volatility": live.get("astro", {}).get("volatility_bias"),
        "trade_halt": live.get("news", {}).get("trade_halt"),
        "high_impact": live.get("news", {}).get("high_impact"),
        "risk": 0.5 if live.get("risk_mode") == "Normal" else 0.25,
        "risk_mode": live.get("risk_mode"),
        "rr": "1:3" if (live.get("confidence", 0) or 0) >= 80 else "1:2",
        "daily_limit": "1.5%",
        "confidence": live.get("confidence", 0),
        "htf_bias": live.get("context", {}).get("htf_bias"),
        "ltf_structure": live.get("context", {}).get("ltf_structure"),
    }

    return mentor_engine.generate(market_data, signal_data)


@app.websocket("/ws/chart/{symbol}")
async def chart_stream(websocket: WebSocket, symbol: str, tf: str = Query("5m"), interval: int = Query(3)):
    await websocket.accept()
    safe_interval = max(1, min(interval, 10))

    try:
        while True:
            try:
                payload = market.analyze(symbol, tf)
                last_bar_time = None
                last_close = None
                live_price = None
                broker_symbol = None
                prices = payload.get("fusion", {}).get("prices", [])
                if prices:
                    last_bar_time = prices[-1].get("time")
                    last_close = prices[-1].get("close")

                try:
                    feed = execution_manager.get_broker_feed_status() or {}
                    feed_price = (feed.get("price") or {})
                    feed_symbol = str(feed_price.get("symbol") or "").strip()
                    expected_exec_symbol = to_execution_symbol(symbol)
                    mapped_feed_symbol = to_execution_symbol(feed_symbol) if feed_symbol else ""

                    if expected_exec_symbol and mapped_feed_symbol and mapped_feed_symbol == expected_exec_symbol:
                        live_price = feed_price.get("mid")
                        if live_price is None:
                            bid = feed_price.get("bid")
                            ask = feed_price.get("ask")
                            if isinstance(bid, (int, float)) and isinstance(ask, (int, float)):
                                live_price = (bid + ask) / 2.0
                        broker_symbol = feed_symbol
                except Exception:
                    live_price = None

                await websocket.send_json(
                    {
                        "type": "analyze_tick",
                        "symbol": symbol,
                        "tf": tf,
                        "server_time": datetime.now(timezone.utc).isoformat(),
                        "last_bar_time": last_bar_time,
                        "last_close": last_close,
                        "live_price": live_price,
                        "broker_symbol": broker_symbol,
                        "bar_count": len(prices),
                    }
                )
            except WebSocketDisconnect:
                break
            except Exception as stream_error:
                try:
                    await websocket.send_json(
                        {
                            "type": "stream_error",
                            "symbol": symbol,
                            "tf": tf,
                            "message": str(stream_error),
                        }
                    )
                except WebSocketDisconnect:
                    break

            await asyncio.sleep(safe_interval)
    except WebSocketDisconnect:
        return


@app.websocket("/ws/broker-feed")
async def broker_feed_stream(websocket: WebSocket, interval: float = Query(1.0, ge=0.3, le=5.0)):
    await websocket.accept()
    safe_interval = max(0.3, min(interval, 5.0))

    try:
        while True:
            try:
                payload = {
                    "type": "broker_feed_tick",
                    "server_time": datetime.now(timezone.utc).isoformat(),
                    "broker_feed": execution_manager.get_broker_feed_status(),
                    "broker_brain": execution_manager.get_broker_brain_status(),
                }
                await websocket.send_json(payload)
            except WebSocketDisconnect:
                break
            except Exception as stream_error:
                try:
                    await websocket.send_json(
                        {
                            "type": "stream_error",
                            "server_time": datetime.now(timezone.utc).isoformat(),
                            "message": str(stream_error),
                        }
                    )
                except WebSocketDisconnect:
                    break

            await asyncio.sleep(safe_interval)
    except WebSocketDisconnect:
        return

# Serve static frontend files
frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend"))
app.mount("/frontend", StaticFiles(directory=frontend_path), name="frontend")
app.mount("/", StaticFiles(directory=frontend_path, html=True), name="root")
