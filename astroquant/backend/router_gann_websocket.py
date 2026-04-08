"""
WebSocket Router for Real-Time Gann Updates

Provides live streaming of:
- Square-of-9 levels
- Spiral resonance coordinates
- Price-degree conversions
- Dynamic targets
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
import asyncio
import json
from typing import List, Dict
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_astro_live_data() -> dict:
    """Compute live planetary positions, aspects, moon phase, retrograde status, and astro signal."""
    try:
        import swisseph as swe
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        jd = swe.julday(now.year, now.month, now.day,
                        now.hour + now.minute / 60.0 + now.second / 3600.0)

        PLANET_IDS = {
            "sun": swe.SUN, "moon": swe.MOON, "mercury": swe.MERCURY,
            "venus": swe.VENUS, "mars": swe.MARS,
            "jupiter": swe.JUPITER, "saturn": swe.SATURN,
        }
        positions = {}
        speeds = {}
        for name, pid in PLANET_IDS.items():
            data = swe.calc_ut(jd, pid)
            positions[name] = round(data[0][0], 4)
            speeds[name] = round(data[0][3], 6)

        retrograde = {p: speeds[p] < 0.0 for p in speeds}

        # Aspects (orb 3°)
        ASPECT_ANGLES = {"CONJUNCTION": 0, "SEXTILE": 60, "SQUARE": 90, "TRINE": 120, "OPPOSITION": 180}
        ORB = 3
        keys = list(positions.keys())
        aspects = []
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                p1, p2 = keys[i], keys[j]
                diff = abs(positions[p1] - positions[p2])
                diff = min(diff, 360 - diff)
                for name, ang in ASPECT_ANGLES.items():
                    if abs(diff - ang) <= ORB:
                        aspects.append({"p1": p1, "p2": p2, "aspect": name, "orb": round(abs(diff - ang), 2)})

        # Moon phase
        sun_lon = positions["sun"]
        moon_lon = positions["moon"]
        phase_angle = (moon_lon - sun_lon) % 360
        if phase_angle < 45:
            moon_phase = "New Moon"
        elif phase_angle < 90:
            moon_phase = "Waxing Crescent"
        elif phase_angle < 135:
            moon_phase = "First Quarter"
        elif phase_angle < 180:
            moon_phase = "Waxing Gibbous"
        elif phase_angle < 225:
            moon_phase = "Full Moon"
        elif phase_angle < 270:
            moon_phase = "Waning Gibbous"
        elif phase_angle < 315:
            moon_phase = "Last Quarter"
        else:
            moon_phase = "Waning Crescent"

        # Upcoming moon events in next 30 days
        from datetime import timedelta
        moon_events = []
        for d in range(1, 31):
            jd_check = jd + d
            sun_c = swe.calc_ut(jd_check, swe.SUN)[0][0]
            moon_c = swe.calc_ut(jd_check, swe.MOON)[0][0]
            pa = (moon_c - sun_c) % 360
            dt = now + timedelta(days=d)
            dt_str = dt.strftime("%Y-%m-%d")
            if pa <= 5 or pa >= 355:
                if not any(e["date"] == dt_str for e in moon_events):
                    moon_events.append({"date": dt_str, "event": "New Moon", "angle": round(pa, 1)})
            elif 175 <= pa <= 185:
                if not any(e["date"] == dt_str for e in moon_events):
                    moon_events.append({"date": dt_str, "event": "Full Moon", "angle": round(pa, 1)})

        # Astro signal (simplified scoring)
        score_buy = 0
        score_sell = 0
        for asp in aspects:
            if asp["aspect"] == "TRINE":
                score_buy += 2
            elif asp["aspect"] in ("SQUARE", "OPPOSITION"):
                score_sell += 2
        if retrograde.get("mercury"):
            score_sell += 1
        astro_signal = "BUY" if score_buy > score_sell else ("SELL" if score_sell > score_buy else "NEUTRAL")

        # Gann-planet alignments: which planets sit near key Gann angles (±4°)
        KEY_GANN_ANGLES = [0, 45, 90, 135, 180, 225, 270, 315]
        gann_alignments = []
        for planet, lon in positions.items():
            for ka in KEY_GANN_ANGLES:
                diff = min(abs(lon % 360 - ka), 360 - abs(lon % 360 - ka))
                if diff <= 4:
                    gann_alignments.append({
                        "planet": planet,
                        "gann_angle": ka,
                        "planet_lon": round(lon, 2),
                        "orb": round(diff, 2),
                    })

        return {
            "positions": positions,
            "speeds": speeds,
            "retrograde": retrograde,
            "aspects": aspects,
            "moon_phase": moon_phase,
            "moon_phase_angle": round(phase_angle, 2),
            "moon_events": moon_events,
            "astro_signal": astro_signal,
            "gann_alignments": gann_alignments,
            "timestamp": now.isoformat(),
        }
    except Exception as e:
        logger.error(f"Astro live data error: {e}")
        return {"error": str(e)}


@router.get("/api/astro/live")
async def astro_live():
    """Live planetary positions, aspects, moon phase, retrograde, and Gann-planet alignments."""
    return JSONResponse(_get_astro_live_data())

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
        from astroquant.engine.gann.gann_master_engine import GannMasterEngine
        from astroquant.engine.gann.gann_square_of_9_engine import GannSquareOf9Engine
        from astroquant.engine.gann.gann_spiral_engine import GannSpiralEngine
        
        gann = GannMasterEngine()
        sq9 = GannSquareOf9Engine()
        spiral = GannSpiralEngine()
        
        try:
            from astroquant.engine.candle.candle_reader import get_latest_candle
            _c = get_latest_candle("XAUUSD", 1)
            price = float(_c["close"]) if _c else 4637.0
        except Exception:
            price = 4637.0

        async def _compute_and_broadcast():
            nonlocal price
            import time as _time
            try:
                sq9_result = sq9.nearest(price)
                spiral_result = spiral.coordinates(price)
                gann_master = gann.analyze([
                    {"open": price, "high": price + 1.0, "low": price - 1.0, "close": price}
                    for _ in range(8)
                ])
                harmony_result = {
                    "price_time": (gann_master.get("signals") or {}).get("price_time"),
                    "angle": (gann_master.get("signals") or {}).get("angle"),
                    "vibration": (gann_master.get("signals") or {}).get("vibration"),
                }
                degree = (price * 360 / 360) % 360
                _now_ts = _time.time()
                if not hasattr(gann_websocket, "_astro_cache") or \
                        _now_ts - gann_websocket._astro_cache.get("_ts", 0) > 60:
                    _astro = _get_astro_live_data()
                    _astro["_ts"] = _now_ts
                    gann_websocket._astro_cache = _astro
                else:
                    _astro = gann_websocket._astro_cache
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
                    },
                    "astro": {k: v for k, v in _astro.items() if k != "_ts"},
                }
                await manager.broadcast(update, symbol)
            except Exception as e:
                logger.error(f"Gann calculation error: {e}")
                await manager.broadcast({"error": str(e), "symbol": symbol,
                                         "timestamp": asyncio.get_event_loop().time()}, symbol)

        # Send initial update immediately on connect
        await _compute_and_broadcast()

        while True:
            # Non-blocking receive — waits 5s max then sends a new update regardless
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=5)
                message = json.loads(data)
                if "price" in message:
                    price = float(message["price"])
            except asyncio.TimeoutError:
                pass  # No client message — just push a fresh update
            except Exception as e:
                logger.error(f"WebSocket receive error: {e}")
                break

            await _compute_and_broadcast()
            # No extra sleep — the 5s receive timeout acts as the interval
    
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
