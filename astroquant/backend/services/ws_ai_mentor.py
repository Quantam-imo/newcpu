from fastapi import WebSocket, WebSocketDisconnect
from fastapi import APIRouter
import asyncio
from astroquant.backend.main import mentor_engine, runner

router = APIRouter()

class AIMentorConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)

manager = AIMentorConnectionManager()

@router.websocket("/ws/ai_mentor/{symbol}")
async def ai_mentor_ws(websocket: WebSocket, symbol: str):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(1)
            # Fetch AI mentor signals for the selected symbol
            candles = runner.get_futures_candles(symbol, lookback_minutes=180, record_limit=120)[1]
            signals = mentor_engine.get_signals(symbol, candles) if hasattr(mentor_engine, 'get_signals') else {}
            await websocket.send_json({"symbol": symbol, "signals": signals})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
