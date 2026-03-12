@router.websocket("/ws/chart/{symbol}")
async def websocket_chart(websocket: WebSocket, symbol: str):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(1)
            # Fetch chart data for symbol
            from backend.main import runner
            candles = []
            try:
                _, candles = runner.get_futures_candles(symbol, lookback_minutes=60, record_limit=50, prefer_cached=True)
            except Exception:
                candles = []
            await websocket.send_json({"candles": candles})
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@router.websocket("/ws/ai_mentor/{symbol}")
async def websocket_ai_mentor(websocket: WebSocket, symbol: str):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(1)
            # Fetch AI mentor signals for symbol
            from backend.main import mentor_engine
            signals = []
            try:
                signals = mentor_engine.get_signals(symbol)
            except Exception:
                signals = []
            await websocket.send_json({"signals": signals})
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@router.websocket("/ws/health")
async def websocket_health(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(2)
            # Fetch system health status
            from backend.main import runner
            health = {}
            try:
                health = runner.feed.health()
            except Exception:
                health = {"status": "error"}
            await websocket.send_json({"health": health})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
from fastapi import WebSocket, WebSocketDisconnect
from fastapi import APIRouter
import asyncio
from backend.database.db import get_connection

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@router.websocket("/ws/orderflow/{symbol}")
async def websocket_endpoint(websocket: WebSocket, symbol: str):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(1)
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT price, size, side, trade_time FROM time_and_sales WHERE symbol = ? ORDER BY trade_time DESC LIMIT 20", (symbol,))
            trades = cursor.fetchall()
            conn.close()
            await websocket.send_json({"trades": trades})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
