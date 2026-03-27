"""
WebSocket Router for Real-Time Gann Updates

Provides live streaming of:
- Square-of-9 levels
- Spiral resonance coordinates
- Price-degree conversions
- Dynamic targets
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio
import json
from typing import List, Dict
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

class GannConnectionManager:
    """Manages WebSocket connections for Gann updates"""
    
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, symbol: str):
        """Register new WebSocket connection"""
        await websocket.accept()
        if symbol not in self.active_connections:
            self.active_connections[symbol] = []
        self.active_connections[symbol].append(websocket)
        logger.info(f"Gann WebSocket: {symbol} connected. Total: {len(self.active_connections.get(symbol, []))}")
    
    async def disconnect(self, websocket: WebSocket, symbol: str):
        """Unregister WebSocket connection"""
        if symbol in self.active_connections:
            self.active_connections[symbol].remove(websocket)
            if not self.active_connections[symbol]:
                del self.active_connections[symbol]
        logger.info(f"Gann WebSocket: {symbol} disconnected. Remaining: {len(self.active_connections.get(symbol, []))}")
    
    async def broadcast(self, data: dict, symbol: str):
        """Broadcast message to all connections for a symbol"""
        if symbol not in self.active_connections:
            return
        
        disconnected = []
        for connection in self.active_connections[symbol]:
            try:
                await connection.send_json(data)
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected
        for connection in disconnected:
            await self.disconnect(connection, symbol)

manager = GannConnectionManager()

@router.websocket("/ws/gann/{symbol}")
async def gann_websocket(websocket: WebSocket, symbol: str):
    """
    WebSocket endpoint for real-time Gann analysis streaming
    
    Sends updates with:
    - Current price
    - Square-of-9 levels
    - Spiral coordinates
    - Dynamic targets
    - Harmonic angles
    """
    await manager.connect(websocket, symbol)
    
    try:
        # Import here to avoid circular imports
        from astroquant.engine.gann.gann_master_engine import GannMasterEngine
        from astroquant.engine.gann.gann_square_of_9_engine import GannSquareOf9Engine
        from astroquant.engine.gann.gann_spiral_engine import GannSpiralEngine
        
        gann = GannMasterEngine()
        sq9 = GannSquareOf9Engine()
        spiral = GannSpiralEngine()
        
        # Simulate live price updates
        price = 2050.5
        
        while True:
            # Receive client message (price or request)
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                message = json.loads(data)
                
                if "price" in message:
                    price = message["price"]
                
            except asyncio.TimeoutError:
                pass  # No new message, continue with updates
            except Exception as e:
                logger.error(f"WebSocket receive error: {e}")
                break
            
            # Calculate Gann analysis
            try:
                # Square-of-9 levels
                sq9_result = sq9.nearest(price)
                
                # Spiral coordinates
                spiral_result = spiral.coordinates(price)

                # Harmonic/aux analysis from master engine signals
                gann_master = gann.analyze([
                    {"open": price, "high": price + 1.0, "low": price - 1.0, "close": price}
                    for _ in range(8)
                ])
                harmony_result = {
                    "price_time": (gann_master.get("signals") or {}).get("price_time"),
                    "angle": (gann_master.get("signals") or {}).get("angle"),
                    "vibration": (gann_master.get("signals") or {}).get("vibration"),
                }
                
                # Price to degree
                degree = (price * 360 / 360) % 360
                
                # Send update
                update = {
                    "timestamp": asyncio.get_event_loop().time(),
                    "symbol": symbol,
                    "price": price,
                    "gann": {
                        "square_of_9": {
                            "level": sq9_result.get("level", 0),
                            "distance": sq9_result.get("distance", 0),
                            "bias": sq9_result.get("bias", "AT_LEVEL")
                        } if sq9_result else {},
                        "spiral": {
                            "x": spiral_result.get("x", 0),
                            "y": spiral_result.get("y", 0),
                            "theta": spiral_result.get("theta", 0),
                            "radius": spiral_result.get("radius", 0)
                        } if spiral_result else {},
                        "degree": degree,
                        "harmonic": harmony_result if harmony_result else {}
                    }
                }
                
                await manager.broadcast(update, symbol)
                
            except Exception as e:
                logger.error(f"Gann calculation error: {e}")
                error_update = {
                    "error": str(e),
                    "symbol": symbol,
                    "timestamp": asyncio.get_event_loop().time()
                }
                await manager.broadcast(error_update, symbol)
            
            # Update interval (100ms)
            await asyncio.sleep(0.1)
    
    except WebSocketDisconnect:
        await manager.disconnect(websocket, symbol)
        logger.info(f"Gann WebSocket: {symbol} disconnected")
    except Exception as e:
        logger.error(f"Gann WebSocket error: {e}")
        try:
            await manager.disconnect(websocket, symbol)
        except:
            pass


@router.get("/ws/gann/test")
async def gann_ws_test():
    """HTML test page for WebSocket Gann updates"""
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Gann WebSocket Test</title>
        <style>
            body { font-family: monospace; background: #1a1a1a; color: #00ff00; padding: 20px; }
            .container { max-width: 800px; margin: 0 auto; }
            h1 { color: #ffaa00; }
            .status { padding: 10px; background: #2a2a2a; margin: 10px 0; border-radius: 5px; }
            .connected { border-left: 4px solid #00ff00; }
            .disconnected { border-left: 4px solid #ff0000; }
            .update { padding: 5px; margin: 5px 0; background: #0a0a0a; }
            input { width: 100%; padding: 8px; margin: 10px 0; background: #2a2a2a; color: #00ff00; border: 1px solid #00ff00; }
            button { padding: 8px 15px; background: #ffaa00; color: black; border: none; cursor: pointer; margin: 5px 5px 5px 0; }
            button:hover { background: #ffcc00; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>⚙️ Gann WebSocket Test</h1>
            
            <div id="status" class="status disconnected">
                Status: <span id="statusText">Disconnected</span>
            </div>
            
            <label>Symbol:</label>
            <input id="symbol" type="text" value="GC.FUT" />
            
            <label>Price:</label>
            <input id="price" type="number" value="2050.5" step="0.1" />
            
            <button onclick="connect()">Connect</button>
            <button onclick="disconnect()">Disconnect</button>
            <button onclick="sendPrice()">Send Price Update</button>
            <button onclick="clearLog()">Clear Log</button>
            
            <h3>Updates:</h3>
            <div id="log" style="height: 400px; overflow-y: auto; background: #0a0a0a; padding: 10px; border: 1px solid #00ff00;"></div>
        </div>
        
        <script>
            let ws = null;
            let connected = false;
            
            function updateStatus(isConnected) {
                connected = isConnected;
                const statusDiv = document.getElementById('status');
                const statusText = document.getElementById('statusText');
                
                if (isConnected) {
                    statusDiv.className = 'status connected';
                    statusText.innerText = 'Connected ✓';
                } else {
                    statusDiv.className = 'status disconnected';
                    statusText.innerText = 'Disconnected ✗';
                }
            }
            
            function log(message) {
                const logDiv = document.getElementById('log');
                const timestamp = new Date().toLocaleTimeString();
                const entry = document.createElement('div');
                entry.className = 'update';
                entry.textContent = `[${timestamp}] ${message}`;
                logDiv.appendChild(entry);
                logDiv.scrollTop = logDiv.scrollHeight;
            }
            
            function clearLog() {
                document.getElementById('log').innerHTML = '';
            }
            
            function connect() {
                const symbol = document.getElementById('symbol').value || 'GC.FUT';
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const wsUrl = `${protocol}//${window.location.host}/ws/gann/${symbol}`;
                
                try {
                    ws = new WebSocket(wsUrl);
                    
                    ws.onopen = function() {
                        updateStatus(true);
                        log(`✓ Connected to ${symbol}`);
                    };
                    
                    ws.onmessage = function(event) {
                        const data = JSON.parse(event.data);
                        if (data.error) {
                            log(`❌ Error: ${data.error}`);
                        } else {
                            const sq9 = data.gann.square_of_9;
                            const spiral = data.gann.spiral;
                            log(
                                `Price: ${data.price.toFixed(2)} | ` +
                                `SQ9: ${sq9.level?.toFixed(1) || 'N/A'} (${sq9.bias || '?'}) | ` +
                                `Spiral: (${spiral.x?.toFixed(1)}, ${spiral.y?.toFixed(1)}) | ` +
                                `Deg: ${data.gann.degree.toFixed(1)}°`
                            );
                        }
                    };
                    
                    ws.onerror = function(error) {
                        log(`❌ WebSocket Error: ${error}`);
                        updateStatus(false);
                    };
                    
                    ws.onclose = function() {
                        updateStatus(false);
                        log(`✗ Disconnected`);
                    };
                } catch (e) {
                    log(`❌ Connection failed: ${e.message}`);
                }
            }
            
            function disconnect() {
                if (ws) {
                    ws.close();
                }
            }
            
            function sendPrice() {
                if (!connected) {
                    log('❌ Not connected');
                    return;
                }
                
                const price = parseFloat(document.getElementById('price').value);
                ws.send(JSON.stringify({ price: price }));
                log(`📤 Sent price: ${price}`);
            }
        </script>
    </body>
    </html>
    """)
