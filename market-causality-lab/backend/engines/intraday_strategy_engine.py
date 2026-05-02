"""
intraday_strategy_engine.py
============================
AstroQuant Intraday Strategy — "ICT Kill Zone Confluence" (IKZC)

Strategy Logic (7 mandatory gates, all must pass):
───────────────────────────────────────────────────
GATE 1 — HTF BIAS         : Daily OR Weekly ICT bias must align with direction.
GATE 2 — KILL ZONE TIMING : Bar must be inside London Open (03-05 EST) or
                            NY Open (08-10 EST) or Silver Bullet (10-11 / 14-15 EST).
GATE 3 — PD ARRAY         : BUY only from Discount (<45%), SELL only from Premium (>55%).
GATE 4 — STRUCTURE TRIGGER: MSS or CHoCH in trade direction (market broke structure).
GATE 5 — MODEL GATE       : v9 model probability >= 0.62 in trade direction.
GATE 6 — ICT SCORE        : ict_setup_score >= 0.30 AND >= 2 ICT concepts active.
GATE 7 — NOVEL CONFIRMATION: At least 1 novel signal active (ECS/NVA/CAR/ICT/FRV).

Entry:
  - Enter at open of next bar after all 7 gates pass.
  - Prefer FVG midpoint or Propulsion Block level when near (within 0.5×ATR).

Stop Loss:
  - BUY : last_swing_low - 0.25×ATR (just below the structure low)
  - SELL: last_swing_high + 0.25×ATR (just above the structure high)
  - Hard cap: stop cannot exceed 2×ATR from entry.

Take Profit:
  - TP1 (50% partial close) : entry + 1.5 × risk  (1:1.5 R)
  - TP2 (remaining 50%)     : entry + 3.0 × risk  (1:3 R)
  - Or opposing PD Array level, whichever is closer.

Position Sizing:
  - Risk 1% of account per trade.
  - Lots = (account × 0.01) / (stop_distance_points × point_value)

Maximum open trades: 2 simultaneously.
Maximum loss per session: 2% of account (circuit breaker).

The engine exposes:
  evaluate_bar(record, model_prob_buy, atr, prev_bars) -> SignalResult | None
  backtest_strategy(memory, price_df) -> BacktestResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

MODEL_PROB_THRESHOLD   = 0.62   # minimum model confidence to enter
ICT_SCORE_THRESHOLD    = 0.30   # minimum ict_setup_score
ICT_CONCEPTS_MIN       = 2      # minimum ICT sub-concepts active
PD_DISCOUNT_MAX        = 0.45   # buy only below this price-position %
PD_PREMIUM_MIN         = 0.55   # sell only above this price-position %
RISK_PER_TRADE_PCT     = 0.01   # 1% account risk per trade
SESSION_LOSS_LIMIT_PCT = 0.02   # 2% max session loss before shutdown
PARTIAL_CLOSE_RR       = 1.5    # close 50% at 1.5 R
FULL_CLOSE_RR          = 3.0    # close remaining at 3.0 R
STOP_ATR_BUFFER        = 0.25   # ATR buffer added below/above stop swing
STOP_MAX_ATR           = 2.0    # hard cap: stop <= 2×ATR from entry
ATR_PERIOD             = 14


# ──────────────────────────────────────────────────────────────────────────────
# Kill Zone definitions (UTC hour range — Gold trades 23:00 Sun - 22:00 Fri)
# ──────────────────────────────────────────────────────────────────────────────

KILL_ZONES_UTC = {
    "london_open":   (7,  10),   # 03:00-05:00 EST = 08:00-10:00 UTC  (DST-adjusted rough)
    "ny_open":       (13, 16),   # 08:00-10:00 EST = 13:00-16:00 UTC (includes NY open + first hour)
    "silver_bullet_am": (15, 16),# 10:00-11:00 EST = 15:00-16:00 UTC
    "silver_bullet_pm": (19, 20),# 14:00-15:00 EST = 19:00-20:00 UTC
    "london_close":  (10, 12),   # 05:00-07:00 EST = 10:00-12:00 UTC
}

KILL_ZONE_NAMES = list(KILL_ZONES_UTC.keys())


# ──────────────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class GateResult:
    passed: bool
    reason: str = ""


@dataclass
class SignalResult:
    direction:        str          # "BUY" or "SELL"
    entry_price:      float
    stop_price:       float
    tp1_price:        float        # 1.5 R — 50% partial
    tp2_price:        float        # 3.0 R — full close
    risk_points:      float        # entry - stop (absolute)
    reward_points:    float        # tp2 - entry (absolute)
    rr_ratio:         float        # reward / risk
    kill_zone:        str
    gates_passed:     list[str]
    model_prob:       float
    ict_score:        float
    ict_concepts:     int
    pd_position_pct:  float
    active_signals:   list[str]
    confidence_score: float        # composite 0-1 from all gates
    notes:            str = ""


@dataclass
class TradeResult:
    direction:     str
    entry:         float
    stop:          float
    tp1:           float
    tp2:           float
    exit_price:    float
    exit_reason:   str            # "tp1", "tp2", "stop", "session_end"
    pnl_r:         float          # P&L in R-multiples
    bars_held:     int
    entry_bar_idx: int


@dataclass
class BacktestResult:
    total_signals:       int
    total_trades:        int
    wins:                int
    losses:              int
    breakevens:          int
    win_rate:            float
    avg_win_r:           float
    avg_loss_r:          float
    expectancy_r:        float
    profit_factor:       float
    max_drawdown_r:      float
    sharpe_r:            float
    gate_pass_rate:      dict[str, float]
    trades:              list[TradeResult] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Kill Zone Check
# ──────────────────────────────────────────────────────────────────────────────

def _get_kill_zone(bar_time) -> str | None:
    """Return the kill zone name if the bar_time falls inside one, else None."""
    try:
        if hasattr(bar_time, "hour"):
            h = bar_time.hour
        else:
            h = pd.Timestamp(bar_time).hour
        for name, (start, end) in KILL_ZONES_UTC.items():
            if start <= h < end:
                return name
        return None
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Swing high / low for stop placement
# ──────────────────────────────────────────────────────────────────────────────

def _recent_swing_low(bars: pd.DataFrame, lookback: int = 20) -> float:
    """Last significant swing low in recent bars."""
    recent = bars.tail(lookback)
    return float(recent["low"].min())


def _recent_swing_high(bars: pd.DataFrame, lookback: int = 20) -> float:
    """Last significant swing high in recent bars."""
    recent = bars.tail(lookback)
    return float(recent["high"].max())


def _compute_atr(bars: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    if len(bars) < 3:
        return float(bars["high"].iloc[-1] - bars["low"].iloc[-1])
    h = bars["high"].astype(float)
    lo = bars["low"].astype(float)
    c = bars["close"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return float(atr.iloc[-1])


# ──────────────────────────────────────────────────────────────────────────────
# Individual Gate Evaluators
# ──────────────────────────────────────────────────────────────────────────────

def _gate1_htf_bias(record: dict, direction: str) -> GateResult:
    """HTF bias must align: daily OR weekly."""
    ict = record.get("ict") or {}
    if direction == "BUY":
        daily  = bool(ict.get("htf_daily_bias_bullish", False))
        weekly = bool(ict.get("htf_weekly_bias_bullish", False))
        # Also check structural weekly bias from gann_ict layer
        weekly_score = float((record.get("time_engine") or {}).get("ict_weekly_bias_score", 0) or 0)
        if daily or weekly or weekly_score > 0.5:
            return GateResult(True, f"htf_bias: daily={daily} weekly={weekly} score={weekly_score:.2f}")
        return GateResult(False, "htf_bias: no bullish HTF bias")
    else:  # SELL
        daily  = bool(ict.get("htf_daily_bias_bearish", False))
        weekly = bool(ict.get("htf_weekly_bias_bearish", False))
        weekly_score = float((record.get("time_engine") or {}).get("ict_weekly_bias_score", 0) or 0)
        if daily or weekly or weekly_score < 0.4:
            return GateResult(True, f"htf_bias: daily={daily} weekly={weekly} score={weekly_score:.2f}")
        return GateResult(False, "htf_bias: no bearish HTF bias")


def _gate2_kill_zone(record: dict) -> tuple[GateResult, str]:
    """Bar must be inside a valid kill zone."""
    bar = record.get("bar") or {}
    bar_time = bar.get("time") or bar.get("timestamp") or bar.get("bar_time")

    # Also check participation flags already computed in scanner
    participation = record.get("participation") or {}
    london = bool(participation.get("participation_london_open", False))
    ny     = bool(participation.get("participation_newyork_open", False))

    # Check ICT kill zone flags from gann_ict layer
    time_eng = record.get("time_engine") or {}
    ict_london = bool(time_eng.get("ict_killzone_london_open", False))
    ict_ny     = bool(time_eng.get("ict_killzone_ny_open", False))

    # Try bar timestamp
    kz = _get_kill_zone(bar_time) if bar_time else None

    if kz or london or ny or ict_london or ict_ny:
        active_kz = kz or ("london_open" if (london or ict_london) else "ny_open")
        return GateResult(True, f"kill_zone: {active_kz}"), active_kz

    # Silver bullet from ICT engine
    ict = record.get("ict") or {}
    if bool(ict.get("silver_bullet_active", False)):
        return GateResult(True, "kill_zone: silver_bullet"), "silver_bullet"

    return GateResult(False, "kill_zone: not in any kill zone"), ""


def _gate3_pd_array(record: dict, direction: str) -> GateResult:
    """Price must be in Discount zone for BUY, Premium for SELL."""
    ict = record.get("ict") or {}
    pos_pct = float(ict.get("pd_price_position_pct", 0.5) or 0.5)
    premium  = bool(ict.get("pd_premium", False))
    discount = bool(ict.get("pd_discount", False))

    if direction == "BUY":
        if discount or pos_pct <= PD_DISCOUNT_MAX:
            return GateResult(True, f"pd_array: discount zone pos={pos_pct:.2f}")
        # Equilibrium is allowed if other conditions are very strong
        if bool(ict.get("pd_equilibrium", False)) and pos_pct <= 0.50:
            return GateResult(True, f"pd_array: equilibrium (low side) pos={pos_pct:.2f}")
        return GateResult(False, f"pd_array: price in premium zone pos={pos_pct:.2f}")
    else:  # SELL
        if premium or pos_pct >= PD_PREMIUM_MIN:
            return GateResult(True, f"pd_array: premium zone pos={pos_pct:.2f}")
        if bool(ict.get("pd_equilibrium", False)) and pos_pct >= 0.50:
            return GateResult(True, f"pd_array: equilibrium (high side) pos={pos_pct:.2f}")
        return GateResult(False, f"pd_array: price in discount zone pos={pos_pct:.2f}")


def _gate4_structure_trigger(record: dict, direction: str) -> GateResult:
    """MSS or CHoCH must confirm the direction."""
    trigger = record.get("trigger") or {}
    structure = record.get("structure") or {}

    mss_bull  = bool(trigger.get("trigger_mss_bullish", False))
    mss_bear  = bool(trigger.get("trigger_mss_bearish", False))
    bos_bull  = bool(trigger.get("trigger_bos_bullish", False))
    bos_bear  = bool(trigger.get("trigger_bos_bearish", False))
    choch_up  = bool(structure.get("structure_choch_up", False))
    choch_dn  = bool(structure.get("structure_choch_down", False))
    disp_bull = bool(trigger.get("trigger_displacement_bullish", False))
    disp_bear = bool(trigger.get("trigger_displacement_bearish", False))

    # Sweep is also a valid structural confirmation
    sweep_buy  = bool(trigger.get("trigger_sweep_buy_side", False))
    sweep_sell = bool(trigger.get("trigger_sweep_sell_side", False))

    if direction == "BUY":
        if mss_bull or choch_up or (bos_bull and disp_bull) or sweep_buy:
            triggers = [k for k,v in {
                "mss_bull": mss_bull, "choch_up": choch_up,
                "bos_bull+disp": bos_bull and disp_bull, "sweep_buy": sweep_buy
            }.items() if v]
            return GateResult(True, f"structure: {','.join(triggers)}")
        return GateResult(False, "structure: no bullish MSS/CHoCH/sweep trigger")
    else:  # SELL
        if mss_bear or choch_dn or (bos_bear and disp_bear) or sweep_sell:
            triggers = [k for k,v in {
                "mss_bear": mss_bear, "choch_dn": choch_dn,
                "bos_bear+disp": bos_bear and disp_bear, "sweep_sell": sweep_sell
            }.items() if v]
            return GateResult(True, f"structure: {','.join(triggers)}")
        return GateResult(False, "structure: no bearish MSS/CHoCH/sweep trigger")


def _gate5_model(model_prob_buy: float, direction: str) -> GateResult:
    """Model probability must be >= threshold in the trade direction."""
    if direction == "BUY":
        if model_prob_buy >= MODEL_PROB_THRESHOLD:
            return GateResult(True, f"model: p_buy={model_prob_buy:.3f} >= {MODEL_PROB_THRESHOLD}")
        return GateResult(False, f"model: p_buy={model_prob_buy:.3f} < {MODEL_PROB_THRESHOLD}")
    else:  # SELL
        p_sell = 1.0 - model_prob_buy
        if p_sell >= MODEL_PROB_THRESHOLD:
            return GateResult(True, f"model: p_sell={p_sell:.3f} >= {MODEL_PROB_THRESHOLD}")
        return GateResult(False, f"model: p_sell={p_sell:.3f} < {MODEL_PROB_THRESHOLD}")


def _gate6_ict_score(record: dict, direction: str) -> GateResult:
    """ICT setup score + minimum active concepts."""
    ict = record.get("ict") or {}
    score    = float(ict.get("ict_setup_score", 0) or 0)
    concepts = int(ict.get("ict_concepts_active", 0) or 0)
    dir_ok   = str(ict.get("ict_setup_direction", "NEUTRAL")).upper() in {direction, "NEUTRAL"}

    if score >= ICT_SCORE_THRESHOLD and concepts >= ICT_CONCEPTS_MIN and dir_ok:
        return GateResult(True, f"ict_score={score:.2f} concepts={concepts} dir={ict.get('ict_setup_direction')}")
    return GateResult(False, f"ict_score={score:.2f} concepts={concepts} dir_ok={dir_ok} (need score>={ICT_SCORE_THRESHOLD}, concepts>={ICT_CONCEPTS_MIN})")


def _gate7_novel_confirmation(record: dict, direction: str) -> GateResult:
    """At least 1 novel signal must be active and aligned."""
    signals = record.get("novel_signals") or record.get("signals") or {}
    ict = record.get("ict") or {}

    active = []

    # ECS — energy compression breakout
    ecs = signals.get("ecs") or {}
    if bool(ecs.get("active", False)):
        active.append("ECS")

    # NVA — novel velocity anomaly
    nva = signals.get("nva") or {}
    if bool(nva.get("active", False)):
        active.append("NVA")

    # CAR — cycle alignment reversal
    car = signals.get("car") or {}
    if bool(car.get("active", False)):
        active.append("CAR")

    # ICT composite signal
    ict_sig = signals.get("ict") or {}
    if bool(ict_sig.get("active", False)):
        sig_dir = str(ict_sig.get("direction", "")).upper()
        if sig_dir == direction or not sig_dir:
            active.append("ICT_COMPOSITE")

    # FRV — fibonacci retracement velocity
    frv = signals.get("frv") or {}
    if bool(frv.get("active", False)):
        active.append("FRV")

    # VSTB — volatility state transition break
    vstb = signals.get("vstb") or {}
    if bool(vstb.get("active", False)):
        active.append("VSTB")

    # Judas swing adds confirmation
    if direction == "SELL" and bool(ict.get("judas_swing_buy", False)):
        active.append("JUDAS")
    if direction == "BUY" and bool(ict.get("judas_swing_sell", False)):
        active.append("JUDAS")

    # Silver bullet in direction
    if bool(ict.get("silver_bullet_active", False)):
        sb_dir = str(ict.get("silver_bullet_direction", "")).upper()
        if sb_dir == direction or not sb_dir:
            active.append("SILVER_BULLET")

    if active:
        return GateResult(True, f"novel: {','.join(active)}")
    return GateResult(False, "novel: no confirming signals active")


# ──────────────────────────────────────────────────────────────────────────────
# Entry / Stop / Target Price Calculator
# ──────────────────────────────────────────────────────────────────────────────

def _calculate_levels(
    direction: str,
    current_price: float,
    bars: pd.DataFrame,
    record: dict,
    atr: float,
) -> tuple[float, float, float, float]:
    """
    Returns (entry, stop, tp1, tp2).
    Entry is adjusted toward FVG/Propulsion Block if within range.
    """
    ict = record.get("ict") or {}

    # ── Entry refinement ──
    entry = current_price
    prop_level = float(ict.get("propulsion_block_level", 0) or 0)
    ce_level   = float(ict.get("ce_level", 0) or 0)

    if direction == "BUY":
        # Prefer entering at FVG/OB level if it's below current price but within 0.5 ATR
        if 0 < prop_level < current_price and (current_price - prop_level) <= 0.5 * atr:
            entry = prop_level
        elif 0 < ce_level < current_price and (current_price - ce_level) <= 0.5 * atr:
            entry = ce_level
    else:
        if prop_level > current_price and (prop_level - current_price) <= 0.5 * atr:
            entry = prop_level
        elif ce_level > current_price and (ce_level - current_price) <= 0.5 * atr:
            entry = ce_level

    # ── Stop Loss ──
    if direction == "BUY":
        swing_low = _recent_swing_low(bars, lookback=20)
        raw_stop  = swing_low - STOP_ATR_BUFFER * atr
        # Hard cap: stop cannot be more than 2×ATR below entry
        stop = max(raw_stop, entry - STOP_MAX_ATR * atr)
    else:
        swing_high = _recent_swing_high(bars, lookback=20)
        raw_stop   = swing_high + STOP_ATR_BUFFER * atr
        stop       = min(raw_stop, entry + STOP_MAX_ATR * atr)

    risk = abs(entry - stop)
    if risk < 1e-8:
        risk = atr * 0.5  # fallback minimum risk

    # ── Targets ──
    if direction == "BUY":
        tp1 = entry + PARTIAL_CLOSE_RR * risk
        tp2 = entry + FULL_CLOSE_RR   * risk
        # Cap TP2 at next premium PD array level if in range
        pos_pct = float(ict.get("pd_price_position_pct", 0.5) or 0.5)
        range_mid = float(ict.get("pd_range_midpoint", 0) or 0)
        if range_mid > 0:
            # Estimate premium zone top (range_mid / 0.5 * 1.0 gives full range top)
            full_range = range_mid / 0.5
            premium_level = full_range * 0.90  # 90th percentile of range
            if tp2 > premium_level > tp1:
                tp2 = premium_level
    else:
        tp1 = entry - PARTIAL_CLOSE_RR * risk
        tp2 = entry - FULL_CLOSE_RR   * risk
        pos_pct = float(ict.get("pd_price_position_pct", 0.5) or 0.5)
        range_mid = float(ict.get("pd_range_midpoint", 0) or 0)
        if range_mid > 0:
            full_range = range_mid / 0.5
            discount_level = full_range * 0.10
            if discount_level > 0 and tp2 < discount_level < tp1:
                tp2 = discount_level

    return entry, stop, tp1, tp2


# ──────────────────────────────────────────────────────────────────────────────
# Confidence Score
# ──────────────────────────────────────────────────────────────────────────────

def _confidence_score(
    model_prob: float,
    ict_score: float,
    ict_concepts: int,
    novel_count: int,
    in_silver_bullet: bool,
    judas_active: bool,
    mms_aligned: bool,
) -> float:
    """
    Composite 0–1 confidence score from multiple sources.
    Weights:
      Model prob      35%
      ICT score       25%
      Novel signals   20%
      Bonuses         20% (silver bullet, judas, mms, concept count)
    """
    model_score  = min(model_prob, 1.0) * 0.35
    ict_s        = min(ict_score, 1.0)  * 0.25
    novel_s      = min(novel_count / 4.0, 1.0) * 0.20

    bonus = 0.0
    if in_silver_bullet: bonus += 0.07
    if judas_active:     bonus += 0.05
    if mms_aligned:      bonus += 0.05
    bonus += min(ict_concepts / 8.0, 1.0) * 0.03

    return min(model_score + ict_s + novel_s + bonus, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# Main Bar Evaluator
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_bar(
    record: dict[str, Any],
    model_prob_buy: float,
    bars: pd.DataFrame,
    direction: str | None = None,
) -> SignalResult | None:
    """
    Evaluate a single scanner record against all 7 gates.

    Parameters
    ----------
    record        : Full scanner record dict (from scanner.py scan_market output).
    model_prob_buy: Model's predicted probability of a BUY outcome (0-1).
    bars          : OHLCV DataFrame up to and including the current bar.
    direction     : Force a specific direction ("BUY"/"SELL"), or None to auto-detect.

    Returns
    -------
    SignalResult if all 7 gates pass, None otherwise.
    """
    if not record or bars is None or len(bars) < 5:
        return None

    atr = _compute_atr(bars)
    bar = record.get("bar") or {}
    current_price = float(bar.get("close") or (bars["close"].iloc[-1] if len(bars) else 0))
    if current_price <= 0:
        return None

    # ── Auto-detect direction from model ──
    if direction is None:
        p_sell = 1.0 - model_prob_buy
        if model_prob_buy > p_sell:
            direction = "BUY"
        else:
            direction = "SELL"

    # ── Run all 7 gates ──
    g1 = _gate1_htf_bias(record, direction)
    g2, kill_zone = _gate2_kill_zone(record)
    g3 = _gate3_pd_array(record, direction)
    g4 = _gate4_structure_trigger(record, direction)
    g5 = _gate5_model(model_prob_buy, direction)
    g6 = _gate6_ict_score(record, direction)
    g7 = _gate7_novel_confirmation(record, direction)

    gates = [g1, g2, g3, g4, g5, g6, g7]
    gate_names = ["htf_bias", "kill_zone", "pd_array", "structure", "model", "ict_score", "novel"]

    if not all(g.passed for g in gates):
        return None  # At least one gate failed — no signal

    # ── All gates passed — compute levels ──
    entry, stop, tp1, tp2 = _calculate_levels(direction, current_price, bars, record, atr)
    risk_pts   = abs(entry - stop)
    reward_pts = abs(tp2 - entry)
    rr         = reward_pts / risk_pts if risk_pts > 1e-8 else 0.0

    # Reject if R:R is below minimum acceptable
    if rr < 1.5:
        return None

    # ── Collect active novel signals for display ──
    signals = record.get("novel_signals") or record.get("signals") or {}
    ict = record.get("ict") or {}
    active_signals = []
    for sig_name in ["ecs", "nva", "pacl", "ris", "car", "vstb", "frv", "ict"]:
        sig = signals.get(sig_name) or {}
        if bool(sig.get("active", False)):
            active_signals.append(sig_name.upper())
    if bool(ict.get("silver_bullet_active")):
        active_signals.append("SILVER_BULLET")
    if bool(ict.get("judas_swing_buy")) or bool(ict.get("judas_swing_sell")):
        active_signals.append("JUDAS_SWING")

    novel_count = len(active_signals)

    # ── Confidence score ──
    ict_score   = float(ict.get("ict_setup_score", 0) or 0)
    ict_concepts = int(ict.get("ict_concepts_active", 0) or 0)
    in_sb    = bool(ict.get("silver_bullet_active", False))
    judas    = bool(ict.get("judas_swing_buy") or ict.get("judas_swing_sell"))
    mms_buy  = bool(ict.get("mms_buy_program", False))
    mms_sell = bool(ict.get("mms_sell_program", False))
    mms_aligned = (direction == "BUY" and mms_buy) or (direction == "SELL" and mms_sell)

    confidence = _confidence_score(
        model_prob   = model_prob_buy if direction == "BUY" else (1.0 - model_prob_buy),
        ict_score    = ict_score,
        ict_concepts = ict_concepts,
        novel_count  = novel_count,
        in_silver_bullet = in_sb,
        judas_active     = judas,
        mms_aligned      = mms_aligned,
    )

    gates_passed = [f"{gate_names[i]}:{gates[i].reason}" for i in range(7)]

    return SignalResult(
        direction       = direction,
        entry_price     = round(entry, 5),
        stop_price      = round(stop, 5),
        tp1_price       = round(tp1, 5),
        tp2_price       = round(tp2, 5),
        risk_points     = round(risk_pts, 5),
        reward_points   = round(reward_pts, 5),
        rr_ratio        = round(rr, 2),
        kill_zone       = kill_zone,
        gates_passed    = gates_passed,
        model_prob      = round(model_prob_buy if direction == "BUY" else (1.0 - model_prob_buy), 4),
        ict_score       = round(ict_score, 3),
        ict_concepts    = ict_concepts,
        pd_position_pct = round(float(ict.get("pd_price_position_pct", 0.5) or 0.5), 3),
        active_signals  = active_signals,
        confidence_score = round(confidence, 3),
        notes           = f"ATR={round(atr,3)} RR={round(rr,2)} kz={kill_zone}",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Position Sizer
# ──────────────────────────────────────────────────────────────────────────────

def calculate_position_size(
    account_balance: float,
    stop_distance: float,
    point_value: float = 0.01,   # $0.01 per 0.01 per oz for gold spot
    risk_pct: float = RISK_PER_TRADE_PCT,
) -> dict[str, float]:
    """
    Calculate position size based on fixed fractional risk.

    For XAUUSD spot (1 lot = 100oz):
      point_value = 1.0 per pip (0.01 per 0.01 per lot)
      Use point_value = 1.0 and stop_distance in price points.

    Returns dict with lots, dollar_risk, stop_distance.
    """
    dollar_risk = account_balance * risk_pct
    if stop_distance <= 0 or point_value <= 0:
        return {"lots": 0.0, "dollar_risk": 0.0, "stop_distance": 0.0}

    # For XAUUSD: 1 lot = 100 oz, each $1 move = $100 profit/loss
    lots = dollar_risk / (stop_distance * 100.0)
    lots = max(0.01, round(lots, 2))  # minimum 0.01 lot

    return {
        "lots":           lots,
        "dollar_risk":    round(dollar_risk, 2),
        "stop_distance":  round(stop_distance, 3),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Backtester
# ──────────────────────────────────────────────────────────────────────────────

def _simulate_trade(
    signal: SignalResult,
    future_bars: pd.DataFrame,
    entry_bar_idx: int,
    max_bars_hold: int = 16,  # max 16 bars = 4h on 15m
) -> TradeResult:
    """
    Simulate a trade against future OHLCV bars.
    Uses close prices for TP1/TP2, high/low for stop checks.
    Partial close at TP1, full close at TP2 or stop.
    """
    direction  = signal.direction
    entry      = signal.entry_price
    stop       = signal.stop_price
    tp1        = signal.tp1_price
    tp2        = signal.tp2_price
    risk       = signal.risk_points

    tp1_hit    = False
    total_r    = 0.0
    exit_price = entry
    exit_reason = "session_end"
    bars_held  = 0

    for i, (_, row) in enumerate(future_bars.iterrows()):
        if i >= max_bars_hold:
            # Close at close price of last bar
            exit_price  = float(row["close"])
            exit_reason = "session_end"
            if direction == "BUY":
                total_r = ((exit_price - entry) / risk) * (0.5 if tp1_hit else 1.0)
            else:
                total_r = ((entry - exit_price) / risk) * (0.5 if tp1_hit else 1.0)
            if tp1_hit:
                total_r += PARTIAL_CLOSE_RR * 0.5  # already booked partial
            bars_held = i + 1
            break

        lo  = float(row["low"])
        hi  = float(row["high"])
        cls = float(row["close"])

        if direction == "BUY":
            # Check stop
            if lo <= stop:
                exit_price  = stop
                exit_reason = "stop"
                partial_r   = PARTIAL_CLOSE_RR * 0.5 if tp1_hit else 0.0
                total_r     = partial_r - (1.0 * (0.5 if tp1_hit else 1.0))
                bars_held   = i + 1
                break
            # Check TP1
            if not tp1_hit and hi >= tp1:
                tp1_hit = True  # book 50% at TP1
            # Check TP2
            if tp1_hit and hi >= tp2:
                exit_price  = tp2
                exit_reason = "tp2"
                total_r     = PARTIAL_CLOSE_RR * 0.5 + FULL_CLOSE_RR * 0.5
                bars_held   = i + 1
                break
        else:  # SELL
            # Check stop
            if hi >= stop:
                exit_price  = stop
                exit_reason = "stop"
                partial_r   = PARTIAL_CLOSE_RR * 0.5 if tp1_hit else 0.0
                total_r     = partial_r - (1.0 * (0.5 if tp1_hit else 1.0))
                bars_held   = i + 1
                break
            # Check TP1
            if not tp1_hit and lo <= tp1:
                tp1_hit = True
            # Check TP2
            if tp1_hit and lo <= tp2:
                exit_price  = tp2
                exit_reason = "tp2"
                total_r     = PARTIAL_CLOSE_RR * 0.5 + FULL_CLOSE_RR * 0.5
                bars_held   = i + 1
                break
    else:
        # Loop completed without break — session end
        if bars_held == 0:
            bars_held = len(future_bars)

    return TradeResult(
        direction     = direction,
        entry         = entry,
        stop          = stop,
        tp1           = tp1,
        tp2           = tp2,
        exit_price    = round(exit_price, 5),
        exit_reason   = exit_reason,
        pnl_r         = round(total_r, 3),
        bars_held     = bars_held,
        entry_bar_idx = entry_bar_idx,
    )


def backtest_strategy(
    memory: list[dict[str, Any]],
    price_df: pd.DataFrame,
    model_probs: list[float] | None = None,
) -> BacktestResult:
    """
    Run the IKZC strategy over a full memory list + price DataFrame.

    Parameters
    ----------
    memory      : List of scanner records (from scan_market).
    price_df    : Full OHLCV DataFrame aligned to memory.
    model_probs : Pre-computed model probability for each record.
                  If None, uses 0.65 as placeholder (demonstration mode).
    """
    if model_probs is None:
        model_probs = [0.65] * len(memory)

    total_signals = 0
    trades: list[TradeResult] = []
    gate_pass_counts: dict[str, int] = {
        "htf_bias": 0, "kill_zone": 0, "pd_array": 0,
        "structure": 0, "model": 0, "ict_score": 0, "novel": 0,
    }

    for idx in range(50, len(memory) - 20):
        record   = memory[idx]
        prob_buy = float(model_probs[idx])
        bars     = price_df.iloc[:idx + 1]

        # Quick pre-check: model must be at least somewhat directional
        p_sell = 1.0 - prob_buy
        if max(prob_buy, p_sell) < MODEL_PROB_THRESHOLD:
            continue

        direction = "BUY" if prob_buy > p_sell else "SELL"

        # Track which gates pass for analysis
        g1 = _gate1_htf_bias(record, direction)
        if g1.passed: gate_pass_counts["htf_bias"] += 1
        g2, kz = _gate2_kill_zone(record)
        if g2.passed: gate_pass_counts["kill_zone"] += 1
        g3 = _gate3_pd_array(record, direction)
        if g3.passed: gate_pass_counts["pd_array"] += 1
        g4 = _gate4_structure_trigger(record, direction)
        if g4.passed: gate_pass_counts["structure"] += 1
        g5 = _gate5_model(prob_buy, direction)
        if g5.passed: gate_pass_counts["model"] += 1
        g6 = _gate6_ict_score(record, direction)
        if g6.passed: gate_pass_counts["ict_score"] += 1
        g7 = _gate7_novel_confirmation(record, direction)
        if g7.passed: gate_pass_counts["novel"] += 1

        if not all(g.passed for g in [g1, g2, g3, g4, g5, g6, g7]):
            continue

        atr = _compute_atr(bars)
        bar = record.get("bar") or {}
        current_price = float(bar.get("close") or price_df["close"].iloc[idx])
        if current_price <= 0:
            continue

        entry, stop, tp1, tp2 = _calculate_levels(direction, current_price, bars, record, atr)
        risk_pts = abs(entry - stop)
        if risk_pts < 1e-8:
            continue
        rr = abs(tp2 - entry) / risk_pts
        if rr < 1.5:
            continue

        total_signals += 1
        signal = SignalResult(
            direction=direction, entry_price=entry, stop_price=stop,
            tp1_price=tp1, tp2_price=tp2, risk_points=risk_pts,
            reward_points=abs(tp2 - entry), rr_ratio=rr,
            kill_zone=kz, gates_passed=[], model_prob=prob_buy,
            ict_score=0, ict_concepts=0, pd_position_pct=0.5,
            active_signals=[], confidence_score=0,
        )

        future_bars = price_df.iloc[idx + 1: idx + 20]
        if len(future_bars) < 2:
            continue

        trade = _simulate_trade(signal, future_bars, idx)
        trades.append(trade)

    # ── Compute statistics ──
    if not trades:
        n = max(len(memory) - 70, 1)
        gate_pass_rate = {k: round(v / n, 3) for k, v in gate_pass_counts.items()}
        return BacktestResult(
            total_signals=total_signals, total_trades=0,
            wins=0, losses=0, breakevens=0,
            win_rate=0.0, avg_win_r=0.0, avg_loss_r=0.0,
            expectancy_r=0.0, profit_factor=0.0,
            max_drawdown_r=0.0, sharpe_r=0.0,
            gate_pass_rate=gate_pass_rate, trades=[],
        )

    wins       = [t for t in trades if t.pnl_r > 0.1]
    losses     = [t for t in trades if t.pnl_r < -0.1]
    breakevens = [t for t in trades if -0.1 <= t.pnl_r <= 0.1]

    avg_win    = float(np.mean([t.pnl_r for t in wins]))   if wins   else 0.0
    avg_loss   = float(np.mean([t.pnl_r for t in losses])) if losses else 0.0
    win_rate   = len(wins) / len(trades)
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    gross_profit = sum(t.pnl_r for t in wins)
    gross_loss   = abs(sum(t.pnl_r for t in losses))
    pf = gross_profit / gross_loss if gross_loss > 1e-8 else 999.0

    # Drawdown in R
    cumulative = np.cumsum([t.pnl_r for t in trades])
    peak = np.maximum.accumulate(cumulative)
    drawdown = peak - cumulative
    max_dd = float(drawdown.max()) if len(drawdown) > 0 else 0.0

    # Sharpe in R units (annualised rough)
    r_series = np.array([t.pnl_r for t in trades])
    sharpe = (r_series.mean() / r_series.std() * np.sqrt(252)) if r_series.std() > 0 else 0.0

    n = max(len(memory) - 70, 1)
    gate_pass_rate = {k: round(v / n, 3) for k, v in gate_pass_counts.items()}

    return BacktestResult(
        total_signals  = total_signals,
        total_trades   = len(trades),
        wins           = len(wins),
        losses         = len(losses),
        breakevens     = len(breakevens),
        win_rate       = round(win_rate, 4),
        avg_win_r      = round(avg_win, 3),
        avg_loss_r     = round(avg_loss, 3),
        expectancy_r   = round(expectancy, 3),
        profit_factor  = round(pf, 3),
        max_drawdown_r = round(max_dd, 3),
        sharpe_r       = round(sharpe, 3),
        gate_pass_rate = gate_pass_rate,
        trades         = trades,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Strategy Summary (human-readable)
# ──────────────────────────────────────────────────────────────────────────────

def strategy_summary() -> dict[str, Any]:
    """Return a human-readable summary of the IKZC strategy rules."""
    return {
        "name": "ICT Kill Zone Confluence (IKZC)",
        "version": "1.0",
        "timeframe": "15m",
        "asset": "XAU/USD (Gold)",
        "model_version": "v9_ict_extended (213 features, 74.0% accuracy)",
        "gates": {
            "1_htf_bias": {
                "rule": "Daily OR Weekly HTF ICT bias must align with trade direction",
                "source": "ict_engine: htf_daily_bias_bullish/bearish, htf_weekly_bias_bullish/bearish",
            },
            "2_kill_zone": {
                "rule": "Bar must be in London Open (08-10 UTC), NY Open (13-16 UTC), or Silver Bullet (15-16 / 19-20 UTC)",
                "source": "participation_engine + ict_engine silver_bullet_active",
            },
            "3_pd_array": {
                "rule": "BUY only below 45% of range (Discount). SELL only above 55% (Premium).",
                "source": "ict_engine: pd_price_position_pct, pd_premium, pd_discount",
            },
            "4_structure_trigger": {
                "rule": "MSS or CHoCH in trade direction, OR BOS+Displacement, OR liquidity sweep",
                "source": "trigger_context + structure_context",
            },
            "5_model_gate": {
                "rule": f"v9 model probability >= {MODEL_PROB_THRESHOLD} in trade direction",
                "source": "serving.py → decide_with_model()",
            },
            "6_ict_score": {
                "rule": f"ict_setup_score >= {ICT_SCORE_THRESHOLD} AND >= {ICT_CONCEPTS_MIN} ICT concepts active",
                "source": "ict_engine: ict_setup_score, ict_concepts_active",
            },
            "7_novel_confirmation": {
                "rule": "At least 1 novel signal active: ECS / NVA / CAR / ICT_COMPOSITE / FRV / VSTB / JUDAS / SILVER_BULLET",
                "source": "novel_signal_engine",
            },
        },
        "entry": "Open of bar AFTER all 7 gates pass. Prefer FVG midpoint or Propulsion Block if within 0.5×ATR.",
        "stop": {
            "buy":  "Last swing low (20-bar) − 0.25×ATR. Hard cap: max 2×ATR below entry.",
            "sell": "Last swing high (20-bar) + 0.25×ATR. Hard cap: max 2×ATR above entry.",
        },
        "targets": {
            "tp1": "1.5 R — close 50% of position",
            "tp2": "3.0 R — close remaining 50% (or next opposing PD array, whichever closer)",
        },
        "risk_management": {
            "risk_per_trade":     f"{RISK_PER_TRADE_PCT*100:.0f}% of account",
            "session_loss_limit": f"{SESSION_LOSS_LIMIT_PCT*100:.0f}% of account (stop trading for the day)",
            "max_concurrent":     "2 trades simultaneously",
            "minimum_rr":         "1:1.5 (rejected below this)",
            "target_rr":          "1:3",
        },
        "position_sizing": "dollar_risk = account × 1% | lots = dollar_risk / (stop_pts × 100)",
    }
