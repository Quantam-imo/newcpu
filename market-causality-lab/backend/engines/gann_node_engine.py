"""
Gann Node Engine — Pressure Points, NOT price levels.

Core Gann rules implemented:
  1. Time hits node  → REAL move (high probability signal)
  2. Price hits without time convergence → NOISE (filter out)
  3. Cycle completes at node, not by distance travelled
  4. The Spiral (SQ9 square-root spiral) governs expansion zones

A node is a time-price INTERSECTION on the SQ9 spiral.
Price alone reaching a SQ9 level is insufficient.
Time must also be at a Gann harmonic cycle count (90, 144, 180, 270, 360 bars).
"""
from __future__ import annotations
import math
from datetime import timedelta
from typing import Optional

# ── Gann harmonic bar counts ──────────────────────────────────────────────────
# These are the time counts where spiral cycles complete
GANN_TIME_HARMONICS = [
    (90,  "Quarter circle — 90°"),
    (144, "Natural order — 144°/Fibonacci"),
    (180, "Half circle — 180°"),
    (270, "Three-quarter circle — 270°"),
    (360, "Full circle — 360°"),
    (45,  "Eighth circle — 45°"),
    (72,  "Fifth of circle — 72°/Fibonacci"),
]

# ── SQ9 spiral step = 0.5 on sqrt scale (one 90-degree arc) ──────────────────
_SQ9_STEP = 0.5
# Cardinal angles on the spiral (0°/360°, 90°, 180°, 270°)
# Ordinal angles (45°, 135°, 225°, 315°) — secondary nodes
_CARDINAL_STEPS = {0, 1, 2, 3, 4}    # every full 90-degree step = cardinal
_ORDINAL_STEPS = {0.5, 1.5, 2.5, 3.5}  # half-steps = ordinal (45°)


def _sq9_levels(price: float, steps: int = 8) -> list[dict]:
    """Generate SQ9 spiral levels outward from price, both above and below.
    Each step = one 90-degree arc on the Gann square-root spiral.
    Returns list sorted by price with node_type (CARDINAL / ORDINAL / MINOR).
    """
    if price <= 0:
        return []
    root = math.sqrt(price)
    floor_n = int(root / _SQ9_STEP)
    levels = []
    for i in range(-steps, steps + 1):
        n = floor_n + i
        if n <= 0:
            continue
        lvl = round((n * _SQ9_STEP) ** 2, 2)
        step_n = abs(i)
        if step_n in _CARDINAL_STEPS:
            node_type = "CARDINAL"
        elif step_n in _ORDINAL_STEPS:
            node_type = "ORDINAL"
        else:
            node_type = "MINOR"
        direction = "above" if lvl > price else "below" if lvl < price else "exact"
        degree_step = i * 90          # each step = 90 degrees on spiral
        levels.append({
            "price": lvl,
            "step": i,
            "degree": degree_step,
            "node_type": node_type,
            "direction": direction,
        })
    return sorted(levels, key=lambda x: x["price"])


def _bars_since_swing(df) -> int:
    """Count bars since last significant swing high or low (>= 3-bar pivot)."""
    if len(df) < 6:
        return 0
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    # Walk backwards from bar[-2] looking for pivot
    for i in range(len(closes) - 2, 2, -1):
        is_pivot_high = highs[i] > highs[i - 1] and highs[i] > highs[i + 1]
        is_pivot_low  = lows[i]  < lows[i - 1]  and lows[i]  < lows[i + 1]
        if is_pivot_high or is_pivot_low:
            return len(closes) - 1 - i
    return 0


def _nearest_time_harmonic(bars_count: int) -> dict:
    """Find closest Gann time harmonic to current bar count from swing.
    Returns the harmonic, proximity (bars away), and whether we're AT the node.
    """
    if bars_count <= 0:
        return {"harmonic": 0, "label": "N/A", "bars_away": 999, "at_node": False}
    best = min(GANN_TIME_HARMONICS, key=lambda h: abs(h[0] - bars_count))
    bars_away = abs(best[0] - bars_count)
    tolerance = max(2, int(best[0] * 0.03))  # 3% tolerance, min 2 bars
    return {
        "harmonic": best[0],
        "label": best[1],
        "bars_away": bars_away,
        "at_node": bars_away <= tolerance,
    }


def _price_at_node(price: float, sq9_levels: list[dict], tolerance_pct: float = 0.003) -> Optional[dict]:
    """Check if current price is within tolerance% of any SQ9 node level.
    Returns the node dict if yes, None if price is NOT at a node.
    """
    for lvl in sq9_levels:
        if lvl["price"] <= 0:
            continue
        deviation = abs(price - lvl["price"]) / lvl["price"]
        if deviation <= tolerance_pct:
            return {**lvl, "deviation_pct": round(deviation * 100, 3)}
    return None


def gann_node_engine(df, state: dict) -> dict:
    """
    Core Gann Node pressure-point engine.

    Returns:
        node_active       bool   — True only when time AND price converge at node
        node_type         str    — CARDINAL | ORDINAL | MINOR | NONE
        node_price        float  — SQ9 level price is near (or 0)
        node_degree       int    — SQ9 degree step at this node
        time_harmonic     int    — Gann bar count firing (90/144/180/270/360)
        time_label        str    — human label for harmonic
        bars_from_swing   int    — bars elapsed since last swing pivot
        bars_to_next_node int    — bars until nearest forward harmonic
        price_at_node     bool   — price within 0.3% of SQ9 level
        time_at_node      bool   — bar count at Gann harmonic
        signal_quality    str    — REAL | NOISE | BUILDING | WATCH
        spiral_expansion  str    — UP_SPIRAL | DOWN_SPIRAL | COILING (spiral direction)
        next_nodes        list   — next 3 SQ9 levels above and below with expected bar counts
        narration         str    — plain-English description for display
    """
    price = float(state["price"])
    sq9_levels = _sq9_levels(price, steps=6)

    bars_from_swing = _bars_since_swing(df)
    time_info = _nearest_time_harmonic(bars_from_swing)

    price_node = _price_at_node(price, sq9_levels)
    price_at_node = price_node is not None
    time_at_node = time_info["at_node"]

    # ── Core Rule ────────────────────────────────────────────────────────────
    # REAL signal = time AT node AND price AT node (both must converge)
    # NOISE = only price at node, no time
    # BUILDING = only time at node, price not yet at node
    # WATCH = neither at node, but approaching
    if time_at_node and price_at_node:
        signal_quality = "REAL"
        node_active = True
        matched_node = price_node
    elif price_at_node and not time_at_node:
        signal_quality = "NOISE"
        node_active = False
        matched_node = price_node
    elif time_at_node and not price_at_node:
        signal_quality = "BUILDING"
        node_active = False
        matched_node = None
    else:
        signal_quality = "WATCH"
        node_active = False
        matched_node = None

    node_type  = matched_node["node_type"] if matched_node else "NONE"
    node_price = matched_node["price"]     if matched_node else 0.0
    node_deg   = matched_node["degree"]    if matched_node else 0

    # ── Spiral direction ─────────────────────────────────────────────────────
    # Determine if price is expanding outward (up or down the spiral)
    # or coiling (price compressing near a node between harmonics)
    if len(df) >= 20:
        range_now  = float(df["high"].tail(5).max()  - df["low"].tail(5).min())
        range_prev = float(df["high"].tail(20).max() - df["low"].tail(20).min())
        expansion_ratio = range_now / range_prev if range_prev > 0 else 1.0
    else:
        expansion_ratio = 1.0

    trend = state.get("trend", "UP")
    if expansion_ratio > 0.35:
        spiral_expansion = "UP_SPIRAL" if trend == "UP" else "DOWN_SPIRAL"
    else:
        spiral_expansion = "COILING"

    # ── Next forward nodes (price levels + estimated bar counts) ─────────────
    # Find next 3 levels above and below, with nearest harmonic bar count
    above_nodes = sorted([x for x in sq9_levels if x["direction"] == "above"][:3], key=lambda x: x["price"])
    below_nodes = sorted([x for x in sq9_levels if x["direction"] == "below"][-3:], key=lambda x: x["price"], reverse=True)

    def _enrich_node(n: dict) -> dict:
        dist_pct = round(abs(n["price"] - price) / price * 100, 2)
        # Estimate bars needed from current bar count to next harmonic large enough to cover this distance
        bars_needed = next(
            (h for h, _ in GANN_TIME_HARMONICS if h > bars_from_swing),
            360
        ) - bars_from_swing
        return {
            "price": n["price"],
            "degree": n["degree"],
            "node_type": n["node_type"],
            "direction": n["direction"],
            "dist_pct": dist_pct,
            "est_bars_to_reach": max(0, bars_needed),
        }

    next_nodes = [_enrich_node(n) for n in (above_nodes + below_nodes)]
    next_nodes.sort(key=lambda x: x["dist_pct"])

    # ── Bars to next node ────────────────────────────────────────────────────
    next_harmonic = next((h for h, _ in GANN_TIME_HARMONICS if h > bars_from_swing), 360)
    bars_to_next = next_harmonic - bars_from_swing

    # ── Narration ────────────────────────────────────────────────────────────
    if signal_quality == "REAL":
        narration = (
            f"NODE CONFIRMED — Price ${node_price} + Time {time_info['harmonic']}bars "
            f"({time_info['label']}) converge. {node_type} node. MOVE EXPECTED."
        )
    elif signal_quality == "NOISE":
        narration = (
            f"PRICE AT NODE ${node_price} but time ({bars_from_swing} bars) "
            f"is {time_info['bars_away']} bars from harmonic {time_info['harmonic']}. "
            f"Treat as NOISE — no action."
        )
    elif signal_quality == "BUILDING":
        narration = (
            f"TIME NODE FIRING at {time_info['harmonic']} bars ({time_info['label']}), "
            f"but price ${price:.2f} is not yet at a SQ9 level. "
            f"Watch for price to reach nearest node: next above ${above_nodes[0]['price'] if above_nodes else 0}."
        )
    else:
        narration = (
            f"Spiral tracking: {bars_from_swing} bars from swing, "
            f"{bars_to_next} bars to next harmonic ({next_harmonic}). "
            f"Nearest node above ${above_nodes[0]['price'] if above_nodes else 0}, "
            f"below ${below_nodes[0]['price'] if below_nodes else 0}."
        )

    return {
        "node_active":       node_active,
        "node_type":         node_type,
        "node_price":        node_price,
        "node_degree":       node_deg,
        "time_harmonic":     time_info["harmonic"],
        "time_label":        time_info["label"],
        "bars_from_swing":   bars_from_swing,
        "bars_to_next_node": bars_to_next,
        "price_at_node":     price_at_node,
        "time_at_node":      time_at_node,
        "signal_quality":    signal_quality,
        "spiral_expansion":  spiral_expansion,
        "next_nodes":        next_nodes,
        "narration":         narration,
        "sq9_levels":        sq9_levels,
    }
