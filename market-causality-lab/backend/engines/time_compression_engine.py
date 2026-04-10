"""
Time Compression Engine — Gann's law of released energy.

Core truths encoded:
  • Move begins BEFORE it is seen — compression is the signal
  • Market contracts in TIME before expanding in Price
  • Silence phase = signal (both time and range shrinking together)
  • Cycles tighten → breakout is near
  • No alignment → no move
  • Expansion = released compression (energy stored in silence, unleashed at node)

Three compression layers — all must converge for maximum signal:
  1. PRICE RANGE compression   — recent bar ranges vs historical (ATR ratio)
  2. TIME CYCLE compression    — gaps between pivot swings shortening
  3. VOLATILITY SILENCE        — standard deviation falling, histogram narrowing

Signal lifecycle:
  OPEN  → CONTRACTING  → SILENT  → RELEASED  → EXPANDING
  (normal)  (tightening)  (alarm)  (move begun)  (ride it)
"""
from __future__ import annotations

import math
import numpy as np

# Thresholds
_PRICE_COMPRESS_RATIO  = 0.60   # recent range < 60% of prior = price compression
_SILENCE_RATIO         = 0.40   # recent range < 40% of prior = silence
_CYCLE_COMPRESS_RATIO  = 0.65   # recent swing-gap < 65% of avg swing-gap = cycle tightening
_VOL_COMPRESS_RATIO    = 0.50   # recent stddev < 50% of baseline = volatility silence


def _swing_gaps(df, window: int = 60) -> list[int]:
    """
    Return list of bar-counts between recent pivot highs or lows.
    Each gap = number of bars from one swing to the next.
    Shorter gaps = time compression = cycles tightening.
    """
    if len(df) < 10:
        return []
    highs  = df["high"].values[-window:]
    lows   = df["low"].values[-window:]
    pivots = []
    for i in range(1, len(highs) - 1):
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            pivots.append(i)
        elif lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            pivots.append(i)
    if len(pivots) < 2:
        return []
    return [pivots[i + 1] - pivots[i] for i in range(len(pivots) - 1)]


def _price_range_layers(df) -> tuple[float, float, float, float]:
    """
    Return (recent_range, mid_range, prior_range, baseline_range) as average bar ranges
    over windows: 5, 10, 20, 50 bars.
    """
    def _avg_range(n: int) -> float:
        tail = df.tail(n)
        if tail.empty:
            return 0.0
        return float((tail["high"] - tail["low"]).mean())
    return _avg_range(5), _avg_range(10), _avg_range(20), _avg_range(50)


def _stddev_compression(df) -> tuple[float, float]:
    """Recent 10-bar return stddev vs 50-bar baseline stddev."""
    if len(df) < 50:
        return 0.0, 0.0
    returns = df["close"].pct_change().dropna().values
    recent  = float(np.std(returns[-10:])) if len(returns) >= 10 else 0.0
    baseline = float(np.std(returns[-50:])) if len(returns) >= 50 else recent
    return recent, baseline


def time_compression_engine(df) -> dict:
    """
    Full time compression analysis.

    Returns:
        phase          str    — OPEN | CONTRACTING | SILENT | RELEASED | EXPANDING
        score          float  — 0.0 (expanding) → 1.0 (maximum silence)
        breakout_near  bool   — True when all 3 layers converge in compression
        layers         dict   — individual scores per compression layer
        cycle_tightening bool — swing gaps are shortening
        silence_active  bool — price AND volatility both in deep compression
        direction_bias  str   — UP | DOWN | NEUTRAL (pre-compression trend bias)
        energy_stored   float — 0–100 estimate of trapped energy (% vs max range)
        signal          str   — plain-English compression signal for display
        bars_in_compression int — how long current compression has been active
    """
    if len(df) < 20:
        return {
            "phase": "OPEN",
            "score": 0.0,
            "breakout_near": False,
            "layers": {},
            "cycle_tightening": False,
            "silence_active": False,
            "direction_bias": "NEUTRAL",
            "energy_stored": 0.0,
            "signal": "Insufficient data for compression analysis.",
            "bars_in_compression": 0,
        }

    # ── Layer 1: Price range compression ─────────────────────────────────────
    r5, r10, r20, r50 = _price_range_layers(df)
    price_ratio = r5 / r20 if r20 > 0 else 1.0
    price_compressed = price_ratio < _PRICE_COMPRESS_RATIO
    silence_price    = price_ratio < _SILENCE_RATIO
    price_score      = round(max(0.0, 1.0 - price_ratio), 4)

    # ── Layer 2: Time cycle compression (swing gaps shortening) ───────────────
    gaps = _swing_gaps(df, window=min(80, len(df)))
    cycle_tightening = False
    cycle_score      = 0.0
    if len(gaps) >= 3:
        recent_gaps  = gaps[-2:]
        earlier_gaps = gaps[:-2]
        avg_recent   = sum(recent_gaps)  / len(recent_gaps)
        avg_earlier  = sum(earlier_gaps) / len(earlier_gaps) if earlier_gaps else avg_recent
        if avg_earlier > 0:
            cycle_ratio      = avg_recent / avg_earlier
            cycle_tightening = cycle_ratio < _CYCLE_COMPRESS_RATIO
            cycle_score      = round(max(0.0, 1.0 - cycle_ratio), 4)

    # ── Layer 3: Volatility silence (stddev compression) ──────────────────────
    recent_std, baseline_std = _stddev_compression(df)
    vol_compressed = baseline_std > 0 and (recent_std / baseline_std) < _VOL_COMPRESS_RATIO
    vol_score      = round(max(0.0, 1.0 - (recent_std / baseline_std if baseline_std > 0 else 1.0)), 4)

    # ── Composite score (weighted: price 40%, cycle 35%, vol 25%) ─────────────
    score = round(price_score * 0.40 + cycle_score * 0.35 + vol_score * 0.25, 4)

    # ── Silence phase: all 3 layers compressing simultaneously ───────────────
    silence_active = price_compressed and vol_compressed
    # Full breakout alert: 2 of 3 plus price at recent low range
    breakout_near  = sum([price_compressed, cycle_tightening, vol_compressed]) >= 2

    # ── Phase classification ──────────────────────────────────────────────────
    if score > 0.65 and silence_active:
        phase = "SILENT"       # maximum compression — breakout imminent
    elif score > 0.45 or breakout_near:
        phase = "CONTRACTING"  # tightening — watch closely
    elif r5 > r50 * 1.5:
        phase = "EXPANDING"    # range exploding > 150% of 50-bar avg
    elif r5 > r20 * 1.2:
        phase = "RELEASED"     # compression just released, move begun
    else:
        phase = "OPEN"         # normal, no compression

    # ── Direction bias: pre-compression trend ─────────────────────────────────
    if len(df) >= 20:
        c20 = float(df["close"].iloc[-20])
        c5  = float(df["close"].iloc[-5])
        last = float(df["close"].iloc[-1])
        if last > c20 and last > c5:
            direction_bias = "UP"
        elif last < c20 and last < c5:
            direction_bias = "DOWN"
        else:
            direction_bias = "NEUTRAL"
    else:
        direction_bias = "NEUTRAL"

    # ── Energy stored estimate ────────────────────────────────────────────────
    # How much is the range compressed vs the 50-bar max range
    max_range_50 = float((df["high"].tail(50).max() - df["low"].tail(50).min())) if len(df) >= 50 else r50
    energy_stored = round(max(0.0, 1.0 - (r5 / max_range_50)) * 100, 1) if max_range_50 > 0 else 0.0

    # ── How long compression has been active ─────────────────────────────────
    bars_in_compression = 0
    ranges = (df["high"] - df["low"]).values
    threshold = r20 * _PRICE_COMPRESS_RATIO if r20 > 0 else float("inf")
    for i in range(len(ranges) - 1, -1, -1):
        if ranges[i] < threshold:
            bars_in_compression += 1
        else:
            break

    # ── Signal narration ───────────────────────────────────────────────────────
    layers_active = []
    if price_compressed: layers_active.append("PRICE")
    if cycle_tightening: layers_active.append("CYCLE")
    if vol_compressed:   layers_active.append("VOL")

    if phase == "SILENT":
        signal = (
            f"SILENCE PHASE — All compression layers firing ({', '.join(layers_active)}). "
            f"Energy stored {energy_stored:.0f}%. Breakout imminent. "
            f"Bias: {direction_bias}. Compression active {bars_in_compression} bars."
        )
    elif phase == "CONTRACTING":
        signal = (
            f"CONTRACTING — {' + '.join(layers_active) or 'Range'} compressing "
            f"(score {score:.2f}). {bars_in_compression} bars of tightening. "
            f"Cycles tightening: {'YES' if cycle_tightening else 'NO'}. "
            f"Watch for breakout toward {direction_bias}."
        )
    elif phase == "RELEASED":
        signal = (
            f"COMPRESSION RELEASED — Expansion beginning {direction_bias}. "
            f"Ride the move, prior energy {energy_stored:.0f}% was stored."
        )
    elif phase == "EXPANDING":
        signal = (
            f"EXPANDING — Compression fully released. Move is live ({direction_bias}). "
            f"Manage position, not entry."
        )
    else:
        signal = (
            f"Open market — no compression detected. "
            f"Score {score:.2f}. Price range at {r5:.1f} vs 20-bar avg {r20:.1f}."
        )

    return {
        "phase":               phase,
        "score":               score,
        "breakout_near":       breakout_near,
        "silence_active":      silence_active,
        "cycle_tightening":    cycle_tightening,
        "direction_bias":      direction_bias,
        "energy_stored":       energy_stored,
        "bars_in_compression": bars_in_compression,
        "signal":              signal,
        "layers": {
            "price_ratio":      round(price_ratio, 4),
            "price_score":      price_score,
            "price_compressed": price_compressed,
            "cycle_score":      cycle_score,
            "cycle_tightening": cycle_tightening,
            "vol_score":        vol_score,
            "vol_compressed":   vol_compressed,
            "recent_range":     round(r5, 2),
            "mid_range":        round(r20, 2),
            "baseline_range":   round(r50, 2),
            "swing_gaps":       gaps[-5:] if gaps else [],
        },
    }
