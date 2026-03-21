from fastapi import WebSocket, WebSocketDisconnect
from fastapi import APIRouter
import asyncio
from astroquant.backend.main import runner

router = APIRouter()

class ChartPanelConnectionManager:
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

manager = ChartPanelConnectionManager()

@router.websocket("/ws/chart_panel/{symbol}")
async def chart_panel_ws(websocket: WebSocket, symbol: str):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(1)
            # Fetch chart data for the selected symbol
            chart_data = runner.get_futures_candles(symbol, lookback_minutes=180, record_limit=120)
            candles = chart_data[1] if chart_data else []
            await websocket.send_json({"symbol": symbol, "candles": candles})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
