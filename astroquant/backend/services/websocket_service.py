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
