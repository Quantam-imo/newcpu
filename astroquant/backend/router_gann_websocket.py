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
from typing import List, Dict, Optional
import logging
import time as _time

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


# ── Lunar Expansion Engine cache ──────────────────────────────────────────────
_lunar_cache: dict = {"state": None, "ts": 0.0, "prev_phase": None}
_LUNAR_CACHE_TTL = 60.0  # seconds


def _get_lunar_phase_data() -> dict:
    """Compute or return cached lunar expansion state.
    Triggers Telegram alert when phase transitions into MOMENTUM.
    """
    global _lunar_cache
    now_ts = _time.time()

    if now_ts - _lunar_cache["ts"] < _LUNAR_CACHE_TTL and _lunar_cache["state"]:
        return _lunar_cache["state"]

    try:
        from astroquant.engine.gann.lunar_expansion_engine import compute_lunar_phase
        state = compute_lunar_phase(prev_phase=_lunar_cache.get("prev_phase"))

        payload = {
            "date":               state.date,
            "cycle_day":          state.cycle_day,
            "phase":              state.phase,
            "phase_description":  state.phase_description,
            "waxing":             state.waxing,
            "expansion_score":    state.expansion_score,
            "gann_angle":         state.gann_angle,
            "nearest_gann_key":   state.nearest_gann_key,
            "gann_key_orb":       state.gann_key_orb,
            "trade_bias":         state.trade_bias,
            "ict_filter_pass":    state.ict_filter_pass,
            "moon_phase_name":    state.moon_phase_name,
            "moon_phase_angle":   state.moon_phase_angle,
            "lesson_note":        state.lesson_note,
            "next_momentum_day":  state.next_momentum_day,
        }
        if state.extra:
            payload["extra"] = state.extra

        # Telegram alert on MOMENTUM entry
        if state.telegram_alert_due:
            try:
                from astroquant.engine.telegram_bot import send_telegram
                msg = (
                    f"⚠️ XAUUSD — Lunar MOMENTUM Phase\n"
                    f"Day {state.cycle_day:.1f} of {29.53} | {state.moon_phase_name}\n"
                    f"Expansion Score: {state.expansion_score:.2f}\n"
                    f"Gann Angle: {state.gann_angle}° (Key: {state.nearest_gann_key}°, orb {state.gann_key_orb}°)\n"
                    f"Lesson 1: Waxing energy peak — wait for liquidity sweep confirmation.\n"
                    f"Bias: {state.trade_bias}"
                )
                send_telegram(msg)
                logger.info("Lunar MOMENTUM Telegram alert sent")
            except Exception as tel_err:
                logger.warning(f"Telegram lunar alert failed: {tel_err}")

        _lunar_cache["state"] = payload
        _lunar_cache["ts"] = now_ts
        _lunar_cache["prev_phase"] = state.phase
        return payload

    except Exception as exc:
        logger.error(f"Lunar phase endpoint error: {exc}")
        return {"error": str(exc)}


@router.get("/api/astro/lunar-phase")
async def lunar_phase():
    """Gann Lesson 1 — Lunar Expansion Engine.

    Returns the current waxing moon cycle state with:
    - cycle_day: days since New Moon (0–29.53)
    - phase: SEED / EARLY_EXPANSION / MOMENTUM / EXHAUSTION / FULL_MOON_APEX / DRIFT
    - expansion_score: sin-wave energy (0→1→0), peaks at Full Moon
    - gann_angle: price-time degree on the 360° lunar Gann wheel
    - trade_bias: LONG_BIAS / AVOID / WATCH_SETUP / EXIT_PARTIAL / EXIT_FULL
    - ict_filter_pass: True when phase allows ICT entry setup
    - lesson_note: Gann Lesson 1 context for the current state
    """
    return JSONResponse(_get_lunar_phase_data())


# ── Node Engine cache ─────────────────────────────────────────────────────────
_node_cache: dict = {"state": None, "ts": 0.0}
_NODE_CACHE_TTL = 30.0


def _get_node_data(price: Optional[float] = None, timeframe: str = "swing") -> dict:
    """Compute or return cached Gann Node state (Lesson 2)."""
    global _node_cache
    now_ts = _time.time()
    if now_ts - _node_cache["ts"] < _NODE_CACHE_TTL and _node_cache["state"] and price is None:
        return _node_cache["state"]

    try:
        from astroquant.engine.gann.gann_node_engine import (
            compute_node, compute_ascendant_state, price_vibration_frequency
        )
        from astroquant.engine.gann.gann_369_engine import (
            compute_369_from_newmoon, build_369_summary, BASE_CYCLES_DAYS
        )

        # Get price from Redis if not provided
        if price is None:
            try:
                from astroquant.engine.candle.candle_reader import get_latest_candle
                _c = get_latest_candle("XAUUSD", 1)
                price = float(_c["close"]) if _c else 4800.0
            except Exception:
                price = 4800.0

        # Compute 3-6-9 states for multiple base cycles
        states = {}
        for cycle_name in ("lunar_phase", "weekly", "28_day"):
            try:
                states[cycle_name] = compute_369_from_newmoon(base_cycle=cycle_name)
            except Exception:
                pass

        primary_state = states.get("lunar_phase") or list(states.values())[0] if states else None
        time_fraction = primary_state.progress if primary_state else 0.5

        # Planetary positions for node detection
        astro = _get_astro_live_data()
        planetary_positions = astro.get("positions", {})

        node = compute_node(price, time_fraction, planetary_positions, timeframe)
        asc = compute_ascendant_state()
        vib = price_vibration_frequency(price)
        summary = build_369_summary(states) if states else {}

        payload = {
            # Node
            "node_type":           node.node_type,
            "node_active":         node.active,
            "time_aligned":        node.time_aligned,
            "price_aligned":       node.price_aligned,
            "planet_aligned":      node.planet_aligned,
            "price":               node.price,
            "price_degree":        node.price_degree,
            "nearest_key_angle":   node.nearest_key_angle,
            "price_angle_orb":     node.price_angle_orb,
            "time_fraction":       node.time_fraction,
            "nearest_time_node":   node.nearest_time_node,
            "time_node_orb":       node.time_node_orb,
            "aligning_planets":    node.aligning_planets,
            "planetary_governor":  node.planetary_governor,
            "node_message":        node.message,
            "node_rule":           node.rule,
            # 3-6-9
            "phase_369":           primary_state.phase_369 if primary_state else None,
            "phase_label":         primary_state.phase_label if primary_state else None,
            "phase_chakra":        primary_state.phase_chakra if primary_state else None,
            "market_state":        primary_state.market_state if primary_state else None,
            "progress":            primary_state.progress if primary_state else None,
            "bars_to_completion":  primary_state.bars_to_completion if primary_state else None,
            "vibration_harmonic":  primary_state.vibration_harmonic if primary_state else None,
            "nine_resonance":      primary_state.nine_resonance if primary_state else None,
            "reversal_imminent":   primary_state.reversal_imminent if primary_state else None,
            "lesson_note_369":     primary_state.lesson_note if primary_state else None,
            "confluence":          summary,
            # Ascendant (intraday)
            "ascendant_degree":    asc.degree,
            "asc_mins_to_90":      asc.minutes_to_next_90,
            "asc_mins_to_key":     asc.minutes_to_next_key,
            "asc_next_key":        asc.next_key_angle,
            # Vibration
            "price_root":          vib["root"],
            "vibration_resonance": vib["resonance_number"],
            "resonance_orb":       vib["resonance_orb"],
            "resonance_active":    vib["resonance_active"],
            "digital_root":        vib["digital_root"],
            "digital_root_369":    vib["digital_root_369"],
            "chakra_369":          vib["chakra_369"],
            "timestamp":           node.timestamp,
        }

        _node_cache["state"] = payload
        _node_cache["ts"] = now_ts
        return payload

    except Exception as exc:
        logger.error(f"Node engine error: {exc}")
        return {"error": str(exc)}


@router.get("/api/astro/nodes")
async def gann_nodes(price: Optional[float] = None, timeframe: str = "swing"):
    """Gann Lesson 2 — Law of Vibration: Node Engine.

    Nodes = pressure points (NOT price levels).
    TIME + PRICE convergence = MOVE. PRICE alone = NOISE.

    Returns:
    - node_type: MAJOR / MEDIUM / MINOR_TIME / NOISE / NONE
    - node_active: True when trading-grade node is active
    - node_rule: plain-English Gann rule for current state
    - phase_369: 3 (initiation) / 6 (expansion) / 9 (completion)
    - market_state: RISE / BALANCE / RELEASE
    - reversal_imminent: True when phase_369 = 9
    - ascendant_degree + asc_mins_to_key (intraday timing)
    - vibration data (digital root, chakra 3-6-9, resonance)
    """
    return JSONResponse(_get_node_data(price, timeframe))


# ── ASC + SQ9 Engine cache (Lesson 3) ────────────────────────────────────────
_asc_sq9_cache: dict = {"state": None, "ts": 0.0}
_ASC_SQ9_CACHE_TTL = 30.0  # seconds


def _get_asc_sq9_data(
    price: Optional[float] = None,
    anchor_asc_deg: Optional[float] = None,
    anchor_price: Optional[float] = None,
    elapsed_mins: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    prev_high: Optional[float] = None,
    prev_low: Optional[float] = None,
) -> dict:
    """Compute or return cached ASC + SQ9 signal (Lesson 3).
    Re-computes if any query parameter changes.
    """
    global _asc_sq9_cache
    now_ts = _time.time()

    has_params = any(v is not None for v in [price, anchor_asc_deg, anchor_price])
    if (
        not has_params
        and now_ts - _asc_sq9_cache["ts"] < _ASC_SQ9_CACHE_TTL
        and _asc_sq9_cache["state"]
    ):
        return _asc_sq9_cache["state"]

    try:
        from astroquant.engine.gann.gann_asc_sq9_engine import build_asc_sq9_api_payload
        from astroquant.engine.gann.gann_node_engine import compute_ascendant_state

        # Use live ASC as anchor if not provided
        if anchor_asc_deg is None:
            asc_state = compute_ascendant_state()
            anchor_asc_deg = float(asc_state.degree)

        _price = float(price) if price else 4800.0
        _anchor_price = float(anchor_price) if anchor_price else _price
        _elapsed = float(elapsed_mins) if elapsed_mins else 0.0
        _vol_ratio = float(volume_ratio) if volume_ratio else 1.0
        _ph = float(prev_high) if prev_high else None
        _pl = float(prev_low) if prev_low else None

        payload = build_asc_sq9_api_payload(
            price=_price,
            anchor_asc_deg=float(anchor_asc_deg),
            anchor_price=_anchor_price,
            elapsed_mins=_elapsed,
            volume_ratio=_vol_ratio,
            prev_high=_ph,
            prev_low=_pl,
        )

        if not has_params:
            _asc_sq9_cache["state"] = payload
            _asc_sq9_cache["ts"] = now_ts

        return payload

    except Exception as exc:
        logger.error(f"ASC+SQ9 endpoint error: {exc}")
        return {
            "error": str(exc),
            "signal": "NOISE",
            "lesson_note": "ASC+SQ9 engine unavailable",
        }


@router.get("/api/astro/asc-sq9")
async def asc_sq9_signal(
    price: Optional[float] = None,
    anchor_asc_deg: Optional[float] = None,
    anchor_price: Optional[float] = None,
    elapsed_mins: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    prev_high: Optional[float] = None,
    prev_low: Optional[float] = None,
):
    """Gann Lesson 3 — ASC + Square of 9 Tradeable Signal.

    Maps Ascendant degree movement to Square of 9 price levels.
    Generates ENTRY / WATCH / NOISE signal using ICT filters.

    Parameters:
    - price: Current market price (default: 4800)
    - anchor_asc_deg: ASC degree at swing-low anchor (default: current live ASC)
    - anchor_price: Price at anchor point (default: price)
    - elapsed_mins: Minutes since anchor (for intraday P(t))
    - volume_ratio: Current/average volume ratio (default: 1.0)
    - prev_high/prev_low: Prior session range for ICT liquidity sweep detection

    Returns:
    - signal: ENTRY | WATCH | NOISE
    - signal_strength: 0.0–1.0
    - asc: {current_deg, cumulative_movement, anchor_deg}
    - sq9: {nearest_level, distance, bias}
    - active_time_node: 45°/90°/180°/270°/360° if currently at one
    - all_time_nodes: full table of all 5 nodes with status (PASSED/ACTIVE/PENDING)
    - ict: {session, liquidity_swept, displacement, pass}
    - projections: {intraday_price, vibration_P}
    - lesson_note: plain-English rules applied
    """
    return JSONResponse(
        _get_asc_sq9_data(
            price=price,
            anchor_asc_deg=anchor_asc_deg,
            anchor_price=anchor_price,
            elapsed_mins=elapsed_mins,
            volume_ratio=volume_ratio,
            prev_high=prev_high,
            prev_low=prev_low,
        )
    )


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
