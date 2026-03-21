from fastapi import WebSocket, WebSocketDisconnect
from fastapi import APIRouter
import asyncio
from astroquant.backend.main import runner

router = APIRouter()

class HealthPanelConnectionManager:
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

manager = HealthPanelConnectionManager()

@router.websocket("/ws/health_panel")
async def health_panel_ws(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(2)
            # Fetch system health status
            health_status = runner.feed.health() if hasattr(runner, 'feed') else {}
            await websocket.send_json({"health": health_status})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
