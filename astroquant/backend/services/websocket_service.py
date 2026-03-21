from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
from astroquant.backend.services.databento_live_service import DatabentoLiveService
from astroquant.backend.database import get_connection

# Define router at the top so all decorators work
router = APIRouter()

# --- WebSocket endpoint: Delta panel ---
@router.websocket("/ws/delta/{symbol}")
async def websocket_delta(websocket: WebSocket, symbol: str):
    await manager.connect(websocket)
    import logging
    try:
        while True:
            await asyncio.sleep(1)
            try:
                # Replace with actual delta data fetch logic
                from astroquant.engine.delta.delta_reader import get_delta_percent
                delta_percent = get_delta_percent(symbol)
                await websocket.send_json({"delta_percent": delta_percent})
            except Exception as e:
                logging.error(f"Error fetching delta for {symbol}: {e}")
                await websocket.send_json({"error": str(e)})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logging.info(f"WebSocket disconnected: /ws/delta/{symbol}")
    except Exception as e:
        manager.disconnect(websocket)
        logging.error(f"WebSocket error in /ws/delta/{symbol}: {e}")
        await websocket.send_json({"error": str(e)})

# --- WebSocket endpoint: Iceberg panel ---
@router.websocket("/ws/iceberg/{symbol}")
async def websocket_iceberg(websocket: WebSocket, symbol: str):
    await manager.connect(websocket)
    import logging
    try:
        while True:
            await asyncio.sleep(2)
            try:
                # Replace with actual iceberg data fetch logic
                from astroquant.engine.iceberg.iceberg_reader import get_iceberg_events
                events = get_iceberg_events(symbol)
                await websocket.send_json({"events": events})
            except Exception as e:
                logging.error(f"Error fetching iceberg for {symbol}: {e}")
                await websocket.send_json({"error": str(e)})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logging.info(f"WebSocket disconnected: /ws/iceberg/{symbol}")
    except Exception as e:
        manager.disconnect(websocket)
        logging.error(f"WebSocket error in /ws/iceberg/{symbol}: {e}")
        await websocket.send_json({"error": str(e)})

# --- WebSocket endpoint: DOM Lite panel ---
@router.websocket("/ws/dom_lite/{symbol}")
async def websocket_dom_lite(websocket: WebSocket, symbol: str):
    await manager.connect(websocket)
    import logging
    try:
        while True:
            await asyncio.sleep(1)
            try:
                # Replace with actual DOM Lite data fetch logic
                from astroquant.engine.dom_lite.dom_lite_reader import get_dom_lite
                dom_data = get_dom_lite(symbol)
                await websocket.send_json(dom_data)
            except Exception as e:
                logging.error(f"Error fetching dom_lite for {symbol}: {e}")
                await websocket.send_json({"error": str(e)})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logging.info(f"WebSocket disconnected: /ws/dom_lite/{symbol}")
    except Exception as e:
        manager.disconnect(websocket)
        logging.error(f"WebSocket error in /ws/dom_lite/{symbol}: {e}")
        await websocket.send_json({"error": str(e)})

# --- WebSocket endpoint: Confluence panel ---
@router.websocket("/ws/confluence/{symbol}")
async def websocket_confluence(websocket: WebSocket, symbol: str):
    await manager.connect(websocket)
    import logging
    try:
        while True:
            await asyncio.sleep(2)
            try:
                # Replace with actual confluence data fetch logic
                from astroquant.engine.confluence.confluence_reader import get_confluence_scores
                conf_data = get_confluence_scores(symbol)
                await websocket.send_json(conf_data)
            except Exception as e:
                logging.error(f"Error fetching confluence for {symbol}: {e}")
                await websocket.send_json({"error": str(e)})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logging.info(f"WebSocket disconnected: /ws/confluence/{symbol}")
    except Exception as e:
        manager.disconnect(websocket)
        logging.error(f"WebSocket error in /ws/confluence/{symbol}: {e}")
        await websocket.send_json({"error": str(e)})


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

# --- WebSocket endpoint: Live chart candles ---
@router.websocket("/ws/chart_live/{symbol}")
async def websocket_chart_live(websocket: WebSocket, symbol: str):
    await manager.connect(websocket)
    from astroquant.backend.services.databento_live_service import DatabentoLiveService
    import logging
    service = DatabentoLiveService()
    async def send_candle(candle):
        await websocket.send_json({"candle": candle})
    try:
        await service.stream_ohlcv_1s(symbol, send_candle)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logging.info(f"WebSocket disconnected: /ws/chart_live/{symbol}")
    except Exception as e:
        manager.disconnect(websocket)
        logging.error(f"WebSocket error in /ws/chart_live/{symbol}: {e}")
        await websocket.send_json({"error": str(e)})

# --- WebSocket endpoint: Chart history (periodic) ---
@router.websocket("/ws/chart/{symbol}")
async def websocket_chart(websocket: WebSocket, symbol: str):
    await manager.connect(websocket)
    import logging
    try:
        while True:
            await asyncio.sleep(1)
            from astroquant.backend.main import runner
            candles = []
            try:
                _, candles = runner.get_futures_candles(symbol, lookback_minutes=60, record_limit=50, prefer_cached=True)
            except Exception as e:
                logging.error(f"Error fetching futures candles for {symbol}: {e}")
                candles = []
            await websocket.send_json({"candles": candles})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logging.info(f"WebSocket disconnected: /ws/chart/{symbol}")
    except Exception as e:
        manager.disconnect(websocket)
        logging.error(f"WebSocket error in /ws/chart/{symbol}: {e}")
        await websocket.send_json({"error": str(e)})

# --- WebSocket endpoint: AI mentor signals ---
@router.websocket("/ws/ai_mentor/{symbol}")
async def websocket_ai_mentor(websocket: WebSocket, symbol: str):
    await manager.connect(websocket)
    import logging
    try:
        while True:
            await asyncio.sleep(1)
            from astroquant.backend.main import mentor_engine
            signals = []
            try:
                signals = mentor_engine.get_signals(symbol)
            except Exception as e:
                logging.error(f"Error fetching mentor signals for {symbol}: {e}")
                signals = []
            await websocket.send_json({"signals": signals})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logging.info(f"WebSocket disconnected: /ws/ai_mentor/{symbol}")
    except Exception as e:
        manager.disconnect(websocket)
        logging.error(f"WebSocket error in /ws/ai_mentor/{symbol}: {e}")
        await websocket.send_json({"error": str(e)})

# --- WebSocket endpoint: System health ---
@router.websocket("/ws/health")
async def websocket_health(websocket: WebSocket):
    await manager.connect(websocket)
    import logging
    try:
        while True:
            await asyncio.sleep(2)
            from astroquant.backend.main import runner
            health = {}
            try:
                health = runner.feed.health()
            except Exception as e:
                logging.error(f"Error fetching system health: {e}")
                health = {"status": "error"}
            await websocket.send_json({"health": health})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logging.info("WebSocket disconnected: /ws/health")
    except Exception as e:
        manager.disconnect(websocket)
        logging.error(f"WebSocket error in /ws/health: {e}")
        await websocket.send_json({"error": str(e)})

@router.websocket("/ws/orderflow/{symbol}")
async def websocket_orderflow(websocket: WebSocket, symbol: str):
    await manager.connect(websocket)
    import logging
    try:
        while True:
            await asyncio.sleep(1)
            try:
                # Fetch recent trades for the symbol from the database
                from astroquant.backend.database import get_connection
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT price, size, side, trade_time FROM time_and_sales WHERE symbol = ? ORDER BY trade_time DESC LIMIT 20",
                    (symbol,)
                )
                trades = cursor.fetchall()
                conn.close()
                # Format as list of lists for frontend compatibility
                trades_list = [[row[0], row[1], row[2], row[3]] for row in trades]
                await websocket.send_json({"trades": trades_list})
            except Exception as e:
                logging.error(f"Error fetching orderflow for {symbol}: {e}")
                await websocket.send_json({"error": str(e)})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logging.info(f"WebSocket disconnected: /ws/orderflow/{symbol}")
    except Exception as e:
        manager.disconnect(websocket)
        logging.error(f"WebSocket error in /ws/orderflow/{symbol}: {e}")
        await websocket.send_json({"error": str(e)})
