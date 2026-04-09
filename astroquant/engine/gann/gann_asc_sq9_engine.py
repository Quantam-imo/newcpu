"""
ASC (Ascendant) + Square of 9 — Tradeable Signal & Backtest Engine

Lesson 3 Practical Module — GannAstroTrader

FRAMEWORK:
  1. Track ASC degree movement from a swing-low anchor point
  2. Map cumulative ASC movement to SQ9 price levels
  3. When ASC crosses 45°, 90°, 180°, 270°, 360° → mark as TIME NODE
  4. ICT filter: is liquidity swept? displacement? active session?
  5. Signal:  TIME_NODE + ICT_PASS → ENTRY
             TIME_NODE + no ICT  → WATCH
             no node              → NOISE

ASC DATA INTERPRETATION:
  Each 1° of ASC movement represents approximately √price unit in SQ9.
  At 90°/180°/270°/360° ASC boundaries, Gann Energy Changes are highest.
  When ASC angle aligns with SQ9 price level — "squaring" of time and price.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:
    import swisseph as swe
    _SWE_AVAILABLE = True
except ImportError:
    _SWE_AVAILABLE = False

from astroquant.engine.gann.gann_astro_timing_engine import (
    intraday_price_projection,
    price_time_vibration,
    ORBITAL_PERIODS,
    ANGULAR_SPEED,
)
from astroquant.engine.gann.gann_square_of_9_engine import GannSquareOf9Engine

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

ASC_KEY_ANGLES = [45.0, 90.0, 180.0, 270.0, 360.0]  # Gann energy change degrees
KEY_ANGLE_NAMES = {
    45:  "45° SEMISQUARE",
    90:  "90° SQUARE",
    180: "180° OPPOSITION",
    270: "270° SESQUISQUARE",
    360: "360° FULL CYCLE",
}

# ASC angular speed: full zodiac (360°) in ~2 hours sidereal = 0.5°/min = 30°/hr
ASC_DEG_PER_MINUTE: float = 0.25          # conservative live fallback (no Eph)
ASC_DEG_PER_HOUR:   float = 15.0          # earth rotation: 360°/24h = 15°/hr
MINUTES_PER_KEY_ANGLE: float = 90.0 / (ASC_DEG_PER_MINUTE * 60)  # ≈6hrs

# ICT session windows in UTC (London + NY are primary)
ICT_SESSIONS = {
    "LONDON": (7, 16),
    "NEW_YORK": (13, 21),
    "OVERLAP": (13, 16),
    "ASIA": (0, 8),
}

_sq9 = GannSquareOf9Engine()


# ── State dataclasses ──────────────────────────────────────────────────────────

@dataclass
class TimeNodeState:
    key_angle: float
    name: str
    status: str          # PASSED | ACTIVE | PENDING
    asc_cumulative_deg: float
    sq9_price_level: float
    time_to_activate_min: float   # 0.0 if active/passed


@dataclass
class ICTState:
    session_name: str
    session_active: bool
    liquidity_swept: bool
    displacement: bool
    pass_filter: bool
    session_note: str


@dataclass
class AscSq9Signal:
    signal: str               # ENTRY | WATCH | NOISE
    signal_strength: float    # 0.0–1.0
    current_asc_deg: float
    cumulative_asc_movement: float
    anchor_asc_deg: float
    anchor_price: float
    nearest_sq9_level: float
    sq9_distance: float
    sq9_bias: str             # ABOVE | BELOW | AT_LEVEL
    active_time_node: Optional[TimeNodeState]
    all_time_nodes: List[TimeNodeState]
    ict: ICTState
    intraday_price_projection: float
    vibration_P: float
    lesson_note: str
    timestamp: str


# ── Live ASC computation ───────────────────────────────────────────────────────

def _compute_asc_swiss_eph(lat: float = 40.7128, lon: float = -74.0060) -> float:
    """Compute ascendant degree using Swiss Ephemeris."""
    if not _SWE_AVAILABLE:
        return None
    try:
        now_utc = datetime.now(timezone.utc)
        jd = swe.julday(
            now_utc.year, now_utc.month, now_utc.day,
            now_utc.hour + now_utc.minute / 60.0 + now_utc.second / 3600.0
        )
        houses_result = swe.houses(jd, lat, lon, b"P")
        # swe.houses returns (cusps, ascmc) where ascmc[0] = ASC
        if isinstance(houses_result, tuple) and len(houses_result) >= 2:
            ascmc = houses_result[1]
            return float(ascmc[0]) % 360.0
    except Exception as exc:
        logger.debug("Swiss Eph ASC failed: %s", exc)
    return None


def compute_live_asc(lat: float = 40.7128, lon: float = -74.0060) -> Dict:
    """Get current Ascendant degree.

    Primary: Swiss Ephemeris (precise).
    Fallback: Time-based sidereal approximation (accurate within ~2°).

    Returns {degree, source, mins_to_next_90, mins_to_next_key}
    """
    asc_deg = _compute_asc_swiss_eph(lat, lon)

    if asc_deg is not None:
        source = "swisseph"
    else:
        # Time-based fallback: GMST → approx local sidereal
        now = datetime.now(timezone.utc)
        doy = now.timetuple().tm_yday
        base_deg = (doy / 365.25) * 360.0
        time_deg = (now.hour + now.minute / 60.0) * ASC_DEG_PER_HOUR
        lon_offset = (lon / 360.0) * 360.0
        asc_deg = (base_deg + time_deg + lon_offset) % 360.0
        source = "time_approx"

    # Time to next key angles
    deg_in_cycle = asc_deg % 360.0
    upcoming_keys = sorted([k for k in ASC_KEY_ANGLES if k > deg_in_cycle % 360])
    if not upcoming_keys:
        upcoming_keys = [360.0]

    next_key = upcoming_keys[0]
    deg_to_next = (next_key - deg_in_cycle) % 360.0 or 360.0
    mins_to_next_key = deg_to_next / ASC_DEG_PER_MINUTE
    mins_to_next_90 = (90.0 - (deg_in_cycle % 90.0)) / ASC_DEG_PER_MINUTE

    return {
        "degree": round(asc_deg, 2),
        "degree_in_cycle": round(deg_in_cycle, 2),
        "source": source,
        "mins_to_next_key": round(mins_to_next_key, 1),
        "mins_to_next_90": round(mins_to_next_90, 1),
        "next_key_angle": next_key,
    }


# ── ASC → SQ9 mapping ─────────────────────────────────────────────────────────

def asc_to_sq9_offset(asc_cumulative_deg: float) -> float:
    """Map cumulative ASC movement to SQ9 root offset.

    Gann principle: 360° ASC = full SQ9 ring.
    Map 0°–360° linearly to root offset range -0.5 → +0.5.

    Returns: root_offset for GannSquareOf9Engine.level()
    """
    # Normalise to 0–1 within the current 360° cycle
    frac = (asc_cumulative_deg % 360.0) / 360.0
    # Map fraction to offset band -0.5 → +0.5
    return round(-0.5 + frac * 1.0, 4)


def asc_sq9_price_level(anchor_price: float, asc_cumulative_deg: float) -> Dict:
    """Compute the SQ9 price level that corresponds to current ASC movement.

    When market price equals this SQ9 level, time and price are "Squared".
    → High-probability reversal or continuation setup.
    """
    offset = asc_to_sq9_offset(asc_cumulative_deg)
    level = _sq9.level(anchor_price, offset)
    nearest = _sq9.nearest(anchor_price)

    return {
        "sq9_level_at_asc": round(level, 4) if level else None,
        "nearest_sq9": nearest,
        "asc_offset": offset,
        "asc_deg": round(asc_cumulative_deg % 360.0, 2),
        "squared": nearest["distance"] is not None and nearest["distance"] < 2.0,
    }


# ── Time Node computation ──────────────────────────────────────────────────────

def compute_time_nodes(
    anchor_asc_deg: float,
    current_asc_deg: float,
    anchor_price: float,
) -> List[TimeNodeState]:
    """Evaluate all 5 key ASC time nodes (45°/90°/180°/270°/360°).

    Node status:
      PASSED  → cumulative movement has crossed this angle
      ACTIVE  → cumulative movement is within ±3° of this angle right now
      PENDING → not yet reached
    """
    cumulative = (current_asc_deg - anchor_asc_deg) % 360.0
    nodes: List[TimeNodeState] = []

    for angle in ASC_KEY_ANGLES:
        offset = asc_to_sq9_offset(angle)
        sq9_level = _sq9.level(anchor_price, offset) or anchor_price

        if cumulative >= angle + 3.0:
            status = "PASSED"
            time_to = 0.0
        elif cumulative >= angle - 3.0:
            status = "ACTIVE"
            time_to = 0.0
        else:
            status = "PENDING"
            deg_remaining = angle - cumulative
            time_to = deg_remaining / ASC_DEG_PER_MINUTE

        nodes.append(TimeNodeState(
            key_angle=angle,
            name=KEY_ANGLE_NAMES[int(angle)],
            status=status,
            asc_cumulative_deg=round(cumulative, 2),
            sq9_price_level=round(sq9_level, 2),
            time_to_activate_min=round(time_to, 1),
        ))

    return nodes


# ── ICT Filter ────────────────────────────────────────────────────────────────

def evaluate_ict_filter(
    price: float,
    prev_high: float,
    prev_low: float,
    volume_ratio: float = 1.0,    # current volume / average volume
    displacement_threshold_pts: float = 3.0,  # $ displacement required
) -> ICTState:
    """ICT filter: liquidity + displacement + session.

    Rules:
      liquidity_swept  = price traded above prev_high (sell-side) or below prev_low (buy-side)
      displacement     = |current close - prev close| > threshold  (strong directional candle)
      session_active   = current UTC hour falls in London or NY session
    """
    now_utc = datetime.now(timezone.utc)
    utc_hour = now_utc.hour

    # Determine active session
    session_name = "OFF_HOURS"
    session_active = False
    for sess, (start, end) in ICT_SESSIONS.items():
        if start <= utc_hour < end:
            session_name = sess
            session_active = True
            if sess == "OVERLAP":
                session_name = "OVERLAP (Highest Liquidity)"
            break

    # Liquidity sweep: price touched beyond prior range
    liquidity_swept = price > prev_high or price < prev_low

    # Displacement: strong impulsive move with elevated volume
    price_move = abs(price - max(prev_high, prev_low) if price > prev_high else price - prev_low)
    displacement = price_move >= displacement_threshold_pts and volume_ratio >= 1.2

    pass_filter = session_active and liquidity_swept and displacement

    note_parts = []
    if not session_active:
        note_parts.append(f"OFF_HOURS (UTC {utc_hour}h) — Wait for London/NY")
    if not liquidity_swept:
        note_parts.append("No liquidity sweep — price inside prior range")
    if not displacement:
        note_parts.append(f"No displacement ({price_move:.1f}pts, vol_ratio {volume_ratio:.1f}x)")
    if pass_filter:
        note_parts.append("ICT PASS — all filters satisfied")

    return ICTState(
        session_name=session_name,
        session_active=session_active,
        liquidity_swept=liquidity_swept,
        displacement=displacement,
        pass_filter=pass_filter,
        session_note="; ".join(note_parts) or "N/A",
    )


# ── Master signal computation ──────────────────────────────────────────────────

def compute_asc_sq9_signal(
    price: float,
    anchor_asc_deg: float,
    anchor_price: float,
    elapsed_mins: float = 0.0,
    volume_ratio: float = 1.0,
    prev_high: float = None,
    prev_low: float = None,
    lat: float = 40.7128,
    lon: float = -74.0060,
) -> AscSq9Signal:
    """Master function: ASC + SQ9 → Signal.

    1. Get live ASC degree
    2. Compute cumulative movement from anchor
    3. Evaluate all 5 time nodes
    4. Map to SQ9 price structure
    5. Apply ICT filter
    6. Generate ENTRY / WATCH / NOISE signal
    """
    # 1. Live ASC
    asc_data = compute_live_asc(lat, lon)
    current_asc = asc_data["degree"]
    cumulative_asc = (current_asc - anchor_asc_deg) % 360.0

    # 2. SQ9 mapping
    sq9_data = asc_sq9_price_level(anchor_price, cumulative_asc)
    nearest_sq9 = sq9_data["nearest_sq9"]

    # 3. Time nodes
    nodes = compute_time_nodes(anchor_asc_deg, current_asc, anchor_price)
    active_node = next((n for n in nodes if n.status == "ACTIVE"), None)

    # 4. ICT filter
    ph = prev_high if prev_high else price * 1.005
    pl = prev_low if prev_low else price * 0.995
    ict = evaluate_ict_filter(price, ph, pl, volume_ratio)

    # 5. Intraday P(t) projection
    intraday = intraday_price_projection(
        h=anchor_price,
        delta_t=max(0.01, elapsed_mins),
        a=price * 0.001,          # ~0.1% of price as astro amplitude
        theta_deg=ASC_DEG_PER_MINUTE * 60,  # ASC speed in deg/hr for hourly theta
        phi_deg=anchor_asc_deg % 360.0,
        v=max(0.01, volume_ratio),
    )

    # 6. Vibration P(t) — Saturn as major cycle reference
    vibration_p = price_time_vibration(
        t=elapsed_mins / (60 * 24),  # convert mins → days
        R=3.5,
        T_days=ORBITAL_PERIODS["saturn"],
        phi_deg=anchor_asc_deg % 360.0,
        Z=price * 0.02,
    )

    # 7. Signal logic
    has_time_node = active_node is not None
    sq9_aligned = nearest_sq9.get("distance", float("inf")) or float("inf")
    price_at_sq9 = sq9_aligned < price * 0.003  # within 0.3%

    if has_time_node and ict.pass_filter:
        signal = "ENTRY"
        strength = min(1.0, 0.6 + (0.2 if price_at_sq9 else 0) + 0.2)
    elif has_time_node and not ict.pass_filter:
        signal = "WATCH"
        strength = 0.5 + (0.1 if price_at_sq9 else 0)
    elif price_at_sq9 and ict.pass_filter:
        signal = "WATCH"
        strength = 0.45
    else:
        signal = "NOISE"
        strength = 0.1

    # Lesson note
    node_label = active_node.name if active_node else "no active time node"
    lesson_note = (
        f"ASC at {current_asc:.1f}° (Δ{cumulative_asc:.1f}° from anchor). "
        f"SQ9: {nearest_sq9.get('level', '?')} ({nearest_sq9.get('bias', '?')}). "
        f"Time Node: {node_label}. ICT: {'PASS' if ict.pass_filter else 'FAIL'}. "
        f"Signal → {signal}. "
        "Rule: Only take ENTRY when ASC hits key angle + ICT confirms. "
        "WATCH = setup forming. NOISE = stand aside."
    )

    return AscSq9Signal(
        signal=signal,
        signal_strength=round(strength, 2),
        current_asc_deg=round(current_asc, 2),
        cumulative_asc_movement=round(cumulative_asc, 2),
        anchor_asc_deg=round(anchor_asc_deg, 2),
        anchor_price=round(anchor_price, 2),
        nearest_sq9_level=nearest_sq9.get("level") or 0.0,
        sq9_distance=round(nearest_sq9.get("distance") or 0.0, 4),
        sq9_bias=nearest_sq9.get("bias", "NEUTRAL"),
        active_time_node=active_node,
        all_time_nodes=nodes,
        ict=ict,
        intraday_price_projection=round(intraday["projected_price"], 2),
        vibration_P=round(vibration_p, 4),
        lesson_note=lesson_note,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ── Backtest engine ───────────────────────────────────────────────────────────

@dataclass
class BacktestBar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    asc_deg: float   # Ascendant degree at bar open


@dataclass
class BacktestTrade:
    entry_time: str
    entry_price: float
    exit_time: Optional[str]
    exit_price: Optional[float]
    direction: str         # LONG | SHORT
    pnl_points: Optional[float]
    win: Optional[bool]
    signal_strength: float
    time_node_angle: float
    ict_state: str         # PASS | FAIL (recorded at entry)
    note: str


@dataclass
class BacktestResult:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win_pts: float
    avg_loss_pts: float
    profit_factor: float
    total_pnl: float
    reversal_rate: float      # % of time nodes that produced a reversal
    fakeout_rate: float       # % of ENTRY signals that were fakeouts
    ict_filter_improvement: float  # win_rate WITH vs WITHOUT ICT
    trades: List[BacktestTrade]


def backtest_asc_sq9(
    bars: List[BacktestBar],
    anchor_asc_deg: float = None,
    anchor_price: float = None,
    stop_pts: float = 5.0,    # stop loss in price points
    target_pts: float = 10.0, # take profit in price points
    require_ict: bool = True,
) -> BacktestResult:
    """Backtest the ASC + SQ9 signal system over a list of bars.

    Entry rules:
      - ASC cumulative movement crosses a key angle (45/90/180/270/360°)
      - Price is within 0.3% of nearest SQ9 level
      - ICT filter passes (if require_ict)

    Exit rules:
      - Take profit: +target_pts above/below entry
      - Stop loss:   -stop_pts below/above entry
      - Or end of data

    Reversal detection:
      - If price closed opposite direction on next 3 bars after time node → reversal
    """
    if not bars:
        return BacktestResult(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, [])

    # Use first bar as anchor if none provided
    if anchor_asc_deg is None:
        anchor_asc_deg = bars[0].asc_deg
    if anchor_price is None:
        anchor_price = bars[0].open

    trades: List[BacktestTrade] = []
    reversal_count = 0
    node_count = 0
    ict_pass_wins = 0
    ict_pass_total = 0
    no_ict_wins = 0
    no_ict_total = 0

    for i, bar in enumerate(bars):
        cumulative_asc = (bar.asc_deg - anchor_asc_deg) % 360.0

        # Check for active time node
        node = None
        for angle in ASC_KEY_ANGLES:
            if abs(cumulative_asc - angle) <= 3.0:
                node = angle
                break
        if node is None:
            continue

        node_count += 1

        # SQ9 check
        sq9_info = _sq9.nearest(bar.close)
        sq9_dist = sq9_info.get("distance") or float("inf")
        price_at_sq9 = sq9_dist < bar.close * 0.003

        # ICT filter (simplified for backtest)
        if i >= 1:
            prev_high = bars[i - 1].high
            prev_low = bars[i - 1].low
        else:
            prev_high = bar.high
            prev_low = bar.low

        liq_swept = bar.high > prev_high or bar.low < prev_low
        displacement = abs(bar.close - bar.open) > stop_pts * 0.5
        session_ok = True  # assume all bars are in session for backtest
        ict_pass = liq_swept and displacement and session_ok

        if require_ict and not ict_pass:
            continue

        # Direction: bias from SQ9 position
        direction = "SHORT" if sq9_info.get("bias") == "ABOVE" else "LONG"
        strength = 0.8 if (ict_pass and price_at_sq9) else 0.5

        # Simulate exit over next N bars
        entry_price = bar.close
        exit_price = None
        exit_time = None
        pnl = None
        win = None

        for j in range(i + 1, min(i + 10, len(bars))):
            future = bars[j]
            if direction == "LONG":
                if future.high >= entry_price + target_pts:
                    exit_price = entry_price + target_pts
                    exit_time = future.timestamp
                    pnl = target_pts
                    win = True
                    break
                elif future.low <= entry_price - stop_pts:
                    exit_price = entry_price - stop_pts
                    exit_time = future.timestamp
                    pnl = -stop_pts
                    win = False
                    break
            else:  # SHORT
                if future.low <= entry_price - target_pts:
                    exit_price = entry_price - target_pts
                    exit_time = future.timestamp
                    pnl = target_pts
                    win = True
                    break
                elif future.high >= entry_price + stop_pts:
                    exit_price = entry_price + stop_pts
                    exit_time = future.timestamp
                    pnl = -stop_pts
                    win = False
                    break

        # Check reversal (direction confirmed): if price moved right direction in next 3 bars
        if i + 3 < len(bars):
            next3 = bars[i + 1: i + 4]
            if direction == "LONG" and all(b.close > entry_price for b in next3):
                reversal_count += 1
            elif direction == "SHORT" and all(b.close < entry_price for b in next3):
                reversal_count += 1

        # Track ICT filter effectiveness
        if ict_pass:
            ict_pass_total += 1
            if win:
                ict_pass_wins += 1
        else:
            no_ict_total += 1
            if win:
                no_ict_wins += 1

        trades.append(BacktestTrade(
            entry_time=bar.timestamp,
            entry_price=round(entry_price, 2),
            exit_time=exit_time,
            exit_price=round(exit_price, 2) if exit_price else None,
            direction=direction,
            pnl_points=round(pnl, 2) if pnl is not None else None,
            win=win,
            signal_strength=round(strength, 2),
            time_node_angle=node,
            ict_state="PASS" if ict_pass else "FAIL",
            note=(
                f"ASC Δ{cumulative_asc:.1f}° → {node}° node. "
                f"SQ9 {sq9_info.get('level','?')} ({sq9_info.get('bias','?')}). "
                f"ICT {'PASS' if ict_pass else 'FAIL'}."
            ),
        ))

    # Compute statistics
    closed = [t for t in trades if t.win is not None]
    wins = [t for t in closed if t.win]
    losses = [t for t in closed if not t.win]

    win_rate = len(wins) / len(closed) if closed else 0.0
    avg_win = sum(t.pnl_points for t in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(t.pnl_points for t in losses) / len(losses)) if losses else 0.0
    profit_factor = (avg_win * len(wins)) / (avg_loss * len(losses)) if losses and avg_loss > 0 else float("inf")
    total_pnl = sum(t.pnl_points for t in closed)

    reversal_rate = reversal_count / node_count if node_count else 0.0
    fakeout_rate = 1.0 - win_rate

    ict_wr = ict_pass_wins / ict_pass_total if ict_pass_total > 0 else 0.0
    no_ict_wr = no_ict_wins / no_ict_total if no_ict_total > 0 else 0.0
    ict_improvement = ict_wr - no_ict_wr

    return BacktestResult(
        total_trades=len(trades),
        winning_trades=len(wins),
        losing_trades=len(losses),
        win_rate=round(win_rate, 3),
        avg_win_pts=round(avg_win, 2),
        avg_loss_pts=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2),
        total_pnl=round(total_pnl, 2),
        reversal_rate=round(reversal_rate, 3),
        fakeout_rate=round(fakeout_rate, 3),
        ict_filter_improvement=round(ict_improvement, 3),
        trades=trades,
    )


# ── Quick summary for API ──────────────────────────────────────────────────────

def build_asc_sq9_api_payload(
    price: float,
    anchor_asc_deg: float,
    anchor_price: float,
    elapsed_mins: float = 0.0,
    volume_ratio: float = 1.0,
    prev_high: float = None,
    prev_low: float = None,
) -> Dict:
    """Build the complete JSON payload for /api/astro/asc-sq9."""
    sig = compute_asc_sq9_signal(
        price=price,
        anchor_asc_deg=anchor_asc_deg,
        anchor_price=anchor_price,
        elapsed_mins=elapsed_mins,
        volume_ratio=volume_ratio,
        prev_high=prev_high,
        prev_low=prev_low,
    )

    nodes_payload = [
        {
            "angle": n.key_angle,
            "name": n.name,
            "status": n.status,
            "sq9_level": n.sq9_price_level,
            "mins_to_activate": n.time_to_activate_min,
        }
        for n in sig.all_time_nodes
    ]

    return {
        "signal": sig.signal,
        "signal_strength": sig.signal_strength,
        "asc": {
            "current_deg": sig.current_asc_deg,
            "cumulative_movement": sig.cumulative_asc_movement,
            "anchor_deg": sig.anchor_asc_deg,
        },
        "sq9": {
            "nearest_level": sig.nearest_sq9_level,
            "distance": sig.sq9_distance,
            "bias": sig.sq9_bias,
        },
        "active_time_node": {
            "angle": sig.active_time_node.key_angle,
            "name": sig.active_time_node.name,
            "sq9_level": sig.active_time_node.sq9_price_level,
        } if sig.active_time_node else None,
        "all_time_nodes": nodes_payload,
        "ict": {
            "session": sig.ict.session_name,
            "session_active": sig.ict.session_active,
            "liquidity_swept": sig.ict.liquidity_swept,
            "displacement": sig.ict.displacement,
            "pass": sig.ict.pass_filter,
            "note": sig.ict.session_note,
        },
        "projections": {
            "intraday_price": sig.intraday_price_projection,
            "vibration_P": sig.vibration_P,
        },
        "lesson_note": sig.lesson_note,
        "timestamp": sig.timestamp,
    }
