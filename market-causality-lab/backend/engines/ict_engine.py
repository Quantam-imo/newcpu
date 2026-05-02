"""
ict_engine.py
=============
Complete ICT (Inner Circle Trader) & MMS (Money Market Structure) concept engine.

Implements ALL concepts not covered elsewhere in the scanner:

ICT Concepts:
  1.  PD Array stack (Premium/Discount/Equilibrium classification)
  2.  HTF Daily Bias  (is today above/below weekly midpoint?)
  3.  HTF Weekly Bias (price position in weekly range)
  4.  Judas Swing     (false session open spike before real reversal)
  5.  Silver Bullet   (3-window ICT high-probability FVG entry setup)
  6.  NWOG / NDOG     (New Week / New Day Opening Gap)
  7.  Propulsion Block (last OB that caused the current impulse)
  8.  SMT-proxy       (inter-session divergence proxy for XAU)

MMS Concepts (ICT Money Market Structure):
  9.  Buy Program / Sell Program detection (institutional order flow phase)
  10. Consequent Encroachment (CE) — midpoint of FVG being tested
  11. Liquidity Void detection (fast impulse leaving no pullback = void)
  12. Consolidation vs Expansion classification

All functions accept a pandas DataFrame with OHLCV columns (lowercase).
The main entry point is:
    ict_context = compute_ict_context(sub_df)

Returns a single flat dict suitable for injection into the scanner record.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _atr_series(df: pd.DataFrame, length: int = 14) -> pd.Series:
    h = df["high"].astype(float)
    lo = df["low"].astype(float)
    c = df["close"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False).mean()


def _empty_context() -> dict[str, Any]:
    return {
        # PD Array / HTF Bias
        "pd_premium":               False,
        "pd_discount":              False,
        "pd_equilibrium":           False,
        "pd_equilibrium_zone":      False,   # within ±5% of 50% midpoint
        "pd_range_midpoint":        0.0,
        "pd_price_position_pct":    0.5,     # 0=bottom of range, 1=top
        "htf_daily_bias_bullish":   False,
        "htf_daily_bias_bearish":   False,
        "htf_weekly_bias_bullish":  False,
        "htf_weekly_bias_bearish":  False,
        # Judas Swing
        "judas_swing_buy":          False,   # false bullish spike → expect bearish
        "judas_swing_sell":         False,   # false bearish spike → expect bullish
        "judas_strength":           0.0,
        # Silver Bullet
        "silver_bullet_active":     False,
        "silver_bullet_direction":  "NEUTRAL",
        "silver_bullet_window":     "",      # "10-11am", "2-3pm", "NY-mid"
        # NWOG / NDOG
        "ndog_bullish":             False,   # New Day Opening Gap up (gap above prev close)
        "ndog_bearish":             False,   # New Day Opening Gap down
        "nwog_bullish":             False,   # New Week Opening Gap up
        "nwog_bearish":             False,   # New Week Opening Gap down
        "ndog_gap_pct":             0.0,
        # Propulsion Block
        "propulsion_block_near":    False,
        "propulsion_block_level":   0.0,
        "propulsion_block_bullish": False,
        "propulsion_block_bearish": False,
        # SMT proxy
        "smt_session_divergence":   False,   # session momentum diverging from structure
        # MMS — Money Market Structure
        "mms_buy_program":          False,   # institutional buy program likely active
        "mms_sell_program":         False,   # institutional sell program likely active
        "mms_program_strength":     0.0,
        # Consequent Encroachment (CE)
        "ce_fvg_bullish_tested":    False,   # price testing midpoint of bullish FVG
        "ce_fvg_bearish_tested":    False,
        "ce_level":                 0.0,
        # Liquidity Void
        "liquidity_void_up":        False,   # fast up impulse left a void (no fill)
        "liquidity_void_down":      False,
        "liquidity_void_strength":  0.0,
        # Consolidation / Expansion
        "market_is_expanding":      False,
        "market_is_consolidating":  False,
        "expansion_direction":      "NEUTRAL",
        # Composite ICT score
        "ict_setup_score":          0.0,     # 0-1, how many ICT conditions are aligned
        "ict_setup_direction":      "NEUTRAL",
        "ict_concepts_active":      [],      # list of active concept names
    }


# ──────────────────────────────────────────────────────────────────────────────
# 1. PD Array — Premium / Discount / Equilibrium
# ──────────────────────────────────────────────────────────────────────────────

def _compute_pd_array(df: pd.DataFrame) -> dict[str, Any]:
    """
    Classify current price as Premium, Discount, or Equilibrium
    within the recent HTF range (last 50 bars = ~12.5 hours on 15m).
    
    ICT definition:
      - Range high to range low = full range
      - 50% midpoint = Equilibrium
      - Above 50% = Premium (consider selling)
      - Below 50% = Discount (consider buying)
      - Within ±5% of midpoint = equilibrium zone (neutral)
    """
    if len(df) < 20:
        return {}

    lookback = min(50, len(df))
    recent = df.tail(lookback)
    range_high = float(recent["high"].max())
    range_low  = float(recent["low"].min())
    close      = float(df["close"].iloc[-1])

    if range_high <= range_low:
        return {}

    midpoint = (range_high + range_low) / 2.0
    position_pct = (close - range_low) / (range_high - range_low)  # 0=bottom, 1=top

    premium      = position_pct > 0.55
    discount     = position_pct < 0.45
    equilibrium  = not premium and not discount
    equil_zone   = 0.45 <= position_pct <= 0.55

    return {
        "pd_premium":               premium,
        "pd_discount":              discount,
        "pd_equilibrium":           equilibrium,
        "pd_equilibrium_zone":      equil_zone,
        "pd_range_midpoint":        round(midpoint, 4),
        "pd_price_position_pct":    round(position_pct, 4),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 2. HTF Daily / Weekly Bias
# ──────────────────────────────────────────────────────────────────────────────

def _compute_htf_bias(df: pd.DataFrame) -> dict[str, Any]:
    """
    HTF Daily Bias: Is today's price above or below yesterday's midpoint?
    HTF Weekly Bias: Is this week's price above or below last week's midpoint?
    
    ICT uses HTF bias to filter intraday entries:
      - If daily bullish bias → only take BUY setups intraday
      - If daily bearish bias → only take SELL setups intraday
    """
    if len(df) < 100:
        return {}

    close = float(df["close"].iloc[-1])

    # Daily bias: last 96 bars ≈ 1 full day (96×15m)
    daily_lookback = min(96, len(df))
    daily_slice = df.tail(daily_lookback)
    daily_high = float(daily_slice["high"].max())
    daily_low  = float(daily_slice["low"].min())
    daily_mid  = (daily_high + daily_low) / 2.0

    htf_daily_bullish = close > daily_mid
    htf_daily_bearish = close < daily_mid

    # Weekly bias: last 480 bars ≈ 1 week (480×15m = 5 trading days)
    weekly_lookback = min(480, len(df))
    weekly_slice = df.tail(weekly_lookback)
    weekly_high = float(weekly_slice["high"].max())
    weekly_low  = float(weekly_slice["low"].min())
    weekly_mid  = (weekly_high + weekly_low) / 2.0

    htf_weekly_bullish = close > weekly_mid
    htf_weekly_bearish = close < weekly_mid

    return {
        "htf_daily_bias_bullish":  htf_daily_bullish,
        "htf_daily_bias_bearish":  htf_daily_bearish,
        "htf_weekly_bias_bullish": htf_weekly_bullish,
        "htf_weekly_bias_bearish": htf_weekly_bearish,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 3. Judas Swing Detection
# ──────────────────────────────────────────────────────────────────────────────

def _compute_judas_swing(df: pd.DataFrame) -> dict[str, Any]:
    """
    Judas Swing: A false spike at the session open that liquidates early
    retail positions before the real institutional move begins.
    
    Detection logic:
      - First 4 bars of session (London Open or NY Open approximation):
        * If first spike is UP but then reverses DOWN = Judas BUY setup (bearish reversal)
        * If first spike is DOWN but then reverses UP = Judas SELL setup (bullish reversal)
      - Requires: spike > 0.5 ATR AND reversal bar closes opposite direction
      - Uses last 8 bars to detect a recent Judas pattern
    """
    if len(df) < 12:
        return {}

    atr = _atr_series(df).iloc[-1]
    if atr <= 0:
        return {}

    # Look at last 8 bars for a Judas pattern
    recent = df.tail(8)
    highs  = recent["high"].astype(float).values
    lows   = recent["low"].astype(float).values
    closes = recent["close"].astype(float).values
    opens  = recent["open"].astype(float).values

    judas_buy  = False   # false down spike → real move UP
    judas_sell = False   # false up spike → real move DOWN
    judas_strength = 0.0

    for i in range(1, len(closes) - 2):
        bar_range = highs[i] - lows[i]
        if bar_range < 0.3 * atr:
            continue

        # Judas SELL: price spikes UP with large wick, then closes DOWN hard
        upper_wick = highs[i] - max(opens[i], closes[i])
        lower_wick = min(opens[i], closes[i]) - lows[i]
        is_rejection_bar = upper_wick > bar_range * 0.50  # top wick > 50% of bar

        if is_rejection_bar and closes[i] < opens[i]:  # bearish rejection bar
            # Next bar confirms reversal
            if i + 1 < len(closes) and closes[i + 1] < closes[i]:
                judas_sell = True
                judas_strength = min(upper_wick / atr, 1.0)
                break

        # Judas BUY: price spikes DOWN with large lower wick, then closes UP
        is_demand_bar = lower_wick > bar_range * 0.50  # bottom wick > 50% of bar

        if is_demand_bar and closes[i] > opens[i]:  # bullish rejection bar
            if i + 1 < len(closes) and closes[i + 1] > closes[i]:
                judas_buy = True
                judas_strength = min(lower_wick / atr, 1.0)
                break

    return {
        "judas_swing_buy":   judas_buy,
        "judas_swing_sell":  judas_sell,
        "judas_strength":    round(judas_strength, 4),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 4. Silver Bullet Setup
# ──────────────────────────────────────────────────────────────────────────────

def _compute_silver_bullet(df: pd.DataFrame) -> dict[str, Any]:
    """
    Silver Bullet: ICT's highest-probability intraday setup.
    
    Three valid windows (EST):
      1. 10:00–11:00 AM EST (after London-NY overlap FVG)
      2.  2:00– 3:00 PM EST (NY afternoon)
      3. Sometimes referenced at 2:00–2:30 PM
    
    Conditions:
      - Price is inside or near a Fair Value Gap (FVG)
      - A displacement (MSS-level impulse) occurred this session
      - Kill zone timing is active
      - Price is in discount (for BUY) or premium (for SELL)
    
    Proxy detection (time-aware, 15m bars):
      - We estimate hour from the date column if available
      - Otherwise use last few bar conditions
    """
    if len(df) < 10:
        return {}

    # Try to get hour from date/time column
    current_hour_est = -1
    for col in ["date", "time", "datetime"]:
        if col in df.columns:
            try:
                last_ts = pd.to_datetime(df[col].iloc[-1])
                # Approximate UTC to EST (-5h standard, -4h DST; use -5 as proxy)
                current_hour_est = (last_ts.hour - 5) % 24
                break
            except Exception:
                pass

    # FVG detection (same as location context but simplified)
    if len(df) < 5:
        return {}
    lows   = df["low"].astype(float)
    highs  = df["high"].astype(float)
    closes = df["close"].astype(float)
    close  = float(closes.iloc[-1])

    bullish_fvg = float(lows.iloc[-1]) > float(highs.iloc[-3])
    bearish_fvg = float(highs.iloc[-1]) < float(lows.iloc[-3])
    fvg_present = bullish_fvg or bearish_fvg

    # Displacement: large range bar (> 1.5 ATR) in last 5 bars
    atr = _atr_series(df).iloc[-1]
    recent_ranges = (df["high"].astype(float) - df["low"].astype(float)).tail(5)
    displacement_present = bool((recent_ranges > 1.5 * atr).any()) if atr > 0 else False

    # PD position
    lookback = min(50, len(df))
    recent = df.tail(lookback)
    rng_high = float(recent["high"].max())
    rng_low  = float(recent["low"].min())
    pos_pct  = (close - rng_low) / max(rng_high - rng_low, 1e-9)

    in_discount = pos_pct < 0.45
    in_premium  = pos_pct > 0.55

    # Silver Bullet timing windows (EST hours)
    window_10_11 = 10 <= current_hour_est <= 11
    window_14_15 = 14 <= current_hour_est <= 15
    in_silver_window = window_10_11 or window_14_15

    if not (fvg_present and displacement_present):
        return {
            "silver_bullet_active":    False,
            "silver_bullet_direction": "NEUTRAL",
            "silver_bullet_window":    "",
        }

    direction = "NEUTRAL"
    if bullish_fvg and in_discount:
        direction = "BUY"
    elif bearish_fvg and in_premium:
        direction = "SELL"

    active = direction != "NEUTRAL" and in_silver_window

    window_name = ""
    if active:
        window_name = "10-11am EST" if window_10_11 else "2-3pm EST"

    return {
        "silver_bullet_active":    active,
        "silver_bullet_direction": direction,
        "silver_bullet_window":    window_name,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 5. NWOG / NDOG — New Week / New Day Opening Gap
# ──────────────────────────────────────────────────────────────────────────────

def _compute_opening_gaps(df: pd.DataFrame) -> dict[str, Any]:
    """
    NDOG (New Day Opening Gap): The gap between yesterday's close and today's open.
    NWOG (New Week Opening Gap): The gap between last week's close and this week's open.
    
    ICT uses these gaps as magnet targets — price tends to fill them.
    A bullish gap = buy programs running above it.
    A bearish gap = sell programs running below it.
    """
    if len(df) < 5:
        return {}

    opens  = df["open"].astype(float)
    closes = df["close"].astype(float)
    atr    = _atr_series(df).iloc[-1]

    current_open = float(opens.iloc[-1])
    prev_close   = float(closes.iloc[-2]) if len(df) >= 2 else current_open

    gap = current_open - prev_close
    gap_pct = abs(gap) / max(prev_close, 1e-9) * 100

    # Meaningful gap = > 0.3 ATR
    min_gap = 0.3 * atr if atr > 0 else 0.01 * prev_close
    ndog_bullish = gap > min_gap
    ndog_bearish = gap < -min_gap

    # Weekly gap approximation: compare current open vs close from 480 bars ago
    nwog_bullish = False
    nwog_bearish = False
    if len(df) >= 480:
        weekly_prev_close = float(closes.iloc[-480])
        weekly_gap = current_open - weekly_prev_close
        weekly_min_gap = max(min_gap * 3, 0.0)
        nwog_bullish = weekly_gap > weekly_min_gap
        nwog_bearish = weekly_gap < -weekly_min_gap

    return {
        "ndog_bullish": ndog_bullish,
        "ndog_bearish": ndog_bearish,
        "nwog_bullish": nwog_bullish,
        "nwog_bearish": nwog_bearish,
        "ndog_gap_pct": round(gap_pct, 4),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 6. Propulsion Block
# ──────────────────────────────────────────────────────────────────────────────

def _compute_propulsion_block(df: pd.DataFrame) -> dict[str, Any]:
    """
    Propulsion Block: The last Order Block (OB) that directly CAUSED the
    most recent impulse move. This is a higher-confidence OB than a generic OB
    because it has already proven it holds institutional orders.
    
    Detection:
      - Find the last large impulse (> 2 ATR in N bars)
      - The bar immediately before that impulse is the propulsion block candle
      - If price retraces back to that level → high-probability entry zone
    """
    if len(df) < 20:
        return {}

    atr    = _atr_series(df).iloc[-1]
    closes = df["close"].astype(float).values
    opens  = df["open"].astype(float).values
    highs  = df["high"].astype(float).values
    lows   = df["low"].astype(float).values
    close  = closes[-1]

    if atr <= 0:
        return {}

    prop_level    = 0.0
    prop_bullish  = False
    prop_bearish  = False
    prop_near     = False

    # Search for propulsion in last 30 bars
    lookback = min(30, len(closes) - 3)
    for i in range(len(closes) - lookback, len(closes) - 2):
        move = closes[i + 2] - closes[i]
        if abs(move) > 2.0 * atr:
            # The bar at i is the propulsion block
            prop_level = opens[i]
            prop_bullish = move > 0
            prop_bearish = move < 0
            break

    if prop_level > 0:
        tolerance = atr * 0.5
        prop_near = abs(close - prop_level) <= tolerance

    return {
        "propulsion_block_near":    prop_near,
        "propulsion_block_level":   round(prop_level, 4),
        "propulsion_block_bullish": prop_bullish and prop_near,
        "propulsion_block_bearish": prop_bearish and prop_near,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 7. Consequent Encroachment (CE)
# ──────────────────────────────────────────────────────────────────────────────

def _compute_consequent_encroachment(df: pd.DataFrame) -> dict[str, Any]:
    """
    CE (Consequent Encroachment): The midpoint of a Fair Value Gap.
    
    ICT: Price often retraces to exactly 50% of an FVG before continuing.
    The CE is the most precise entry within an FVG.
    """
    if len(df) < 5:
        return {}

    highs  = df["high"].astype(float)
    lows   = df["low"].astype(float)
    close  = float(df["close"].iloc[-1])
    atr    = _atr_series(df).iloc[-1]

    # Detect most recent FVG in last 20 bars
    ce_bull_tested = False
    ce_bear_tested = False
    ce_level       = 0.0

    lookback = min(20, len(df) - 2)
    for i in range(len(df) - lookback, len(df) - 2):
        lo_i   = float(lows.iloc[i])
        hi_i   = float(highs.iloc[i])
        lo_i2  = float(lows.iloc[i + 2])
        hi_i2  = float(highs.iloc[i + 2])

        # Bullish FVG: low of bar+2 > high of bar → gap between them
        if lo_i2 > hi_i:
            fvg_mid  = (lo_i2 + hi_i) / 2.0
            ce_level = fvg_mid
            tol      = max(atr * 0.3, (lo_i2 - hi_i) * 0.25)
            ce_bull_tested = abs(close - fvg_mid) <= tol
            break

        # Bearish FVG: high of bar+2 < low of bar
        if hi_i2 < lo_i:
            fvg_mid  = (hi_i2 + lo_i) / 2.0
            ce_level = fvg_mid
            tol      = max(atr * 0.3, (lo_i - hi_i2) * 0.25)
            ce_bear_tested = abs(close - fvg_mid) <= tol
            break

    return {
        "ce_fvg_bullish_tested": ce_bull_tested,
        "ce_fvg_bearish_tested": ce_bear_tested,
        "ce_level":              round(ce_level, 4),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 8. Liquidity Void
# ──────────────────────────────────────────────────────────────────────────────

def _compute_liquidity_void(df: pd.DataFrame) -> dict[str, Any]:
    """
    Liquidity Void: A fast impulse move that left almost no wicks/pullback.
    Price will eventually be drawn back to fill this void.
    
    Detection: 3+ consecutive directional bars with tiny wicks
    (each bar's body > 70% of the bar's total range).
    """
    if len(df) < 8:
        return {}

    opens  = df["open"].astype(float).values
    closes = df["close"].astype(float).values
    highs  = df["high"].astype(float).values
    lows   = df["low"].astype(float).values
    atr    = _atr_series(df).iloc[-1]

    void_up     = False
    void_down   = False
    void_strength = 0.0

    # Check last 6 bars for 3 consecutive directional bars
    for start in range(len(closes) - 6, len(closes) - 2):
        if start < 0:
            continue
        bars_range = range(start, min(start + 3, len(closes)))
        if len(list(bars_range)) < 3:
            continue

        bull_bodies = 0
        bear_bodies = 0
        for i in bars_range:
            rng = highs[i] - lows[i]
            if rng < 1e-9:
                continue
            body = abs(closes[i] - opens[i])
            body_ratio = body / rng
            if closes[i] > opens[i] and body_ratio > 0.65:
                bull_bodies += 1
            elif closes[i] < opens[i] and body_ratio > 0.65:
                bear_bodies += 1

        if bull_bodies >= 3:
            total_move = closes[start + 2] - closes[start]
            if total_move > 1.5 * atr:
                void_up = True
                void_strength = min(total_move / (3 * atr), 1.0) if atr > 0 else 0.5
                break
        if bear_bodies >= 3:
            total_move = closes[start] - closes[start + 2]
            if total_move > 1.5 * atr:
                void_down = True
                void_strength = min(total_move / (3 * atr), 1.0) if atr > 0 else 0.5
                break

    return {
        "liquidity_void_up":       void_up,
        "liquidity_void_down":     void_down,
        "liquidity_void_strength": round(void_strength, 4),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 9. MMS — Money Market Structure
# ──────────────────────────────────────────────────────────────────────────────

def _compute_mms(df: pd.DataFrame) -> dict[str, Any]:
    """
    MMS (Money Market Structure): Detects whether institutional BUY or
    SELL programs are currently running.
    
    Buy Program indicators (ICT/MMS):
      - Price making HH + HL (upward swing structure)
      - Retracing into a discount PD array
      - EMA stack bullish (8>20>50)
      - Displacement was bullish
    
    Sell Program indicators:
      - Price making LL + LH (downward swing structure)
      - Bouncing into a premium PD array
      - EMA stack bearish
      - Displacement was bearish
    
    Also classifies market as Consolidating vs Expanding.
    """
    if len(df) < 55:
        return {}

    closes = df["close"].astype(float)
    highs  = df["high"].astype(float)
    lows   = df["low"].astype(float)
    close  = float(closes.iloc[-1])

    def _ema(s, n):
        return s.ewm(span=n, adjust=False).mean()

    ema8  = float(_ema(closes, 8).iloc[-1])
    ema20 = float(_ema(closes, 20).iloc[-1])
    ema50 = float(_ema(closes, 50).iloc[-1])

    ema_bullish = ema8 > ema20 > ema50
    ema_bearish = ema8 < ema20 < ema50

    # Swing structure in last 20 bars
    lookback = min(20, len(df))
    recent_highs = highs.tail(lookback).values
    recent_lows  = lows.tail(lookback).values

    hh = float(recent_highs[-1]) > float(recent_highs[:-1].max()) if len(recent_highs) > 1 else False
    ll = float(recent_lows[-1]) < float(recent_lows[:-1].min()) if len(recent_lows) > 1 else False

    # PD position
    r_high = float(highs.tail(50).max())
    r_low  = float(lows.tail(50).min())
    pos    = (close - r_low) / max(r_high - r_low, 1e-9)
    in_discount = pos < 0.45
    in_premium  = pos > 0.55

    buy_program  = ema_bullish and in_discount
    sell_program = ema_bearish and in_premium

    # Stronger version: also require HH for buy / LL for sell
    buy_strength  = sum([ema_bullish, in_discount, hh]) / 3.0
    sell_strength = sum([ema_bearish, in_premium, ll]) / 3.0
    program_strength = max(buy_strength, sell_strength)

    # Consolidation vs Expansion
    atr = _atr_series(df).iloc[-1]
    recent_ranges = (highs - lows).tail(10)
    avg_range     = float(recent_ranges.mean()) if len(recent_ranges) else 0.0
    is_expanding      = avg_range > 1.2 * atr if atr > 0 else False
    is_consolidating  = avg_range < 0.7 * atr if atr > 0 else False
    expansion_dir     = "BUY" if (is_expanding and ema_bullish) else ("SELL" if (is_expanding and ema_bearish) else "NEUTRAL")

    return {
        "mms_buy_program":        buy_program,
        "mms_sell_program":       sell_program,
        "mms_program_strength":   round(program_strength, 4),
        "market_is_expanding":    is_expanding,
        "market_is_consolidating": is_consolidating,
        "expansion_direction":    expansion_dir,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 10. SMT Proxy (Session Momentum Divergence)
# ──────────────────────────────────────────────────────────────────────────────

def _compute_smt_proxy(df: pd.DataFrame) -> dict[str, Any]:
    """
    SMT (Smart Money Technique) Divergence:
    In true ICT, this uses correlated assets (e.g., XAU vs DXY or GC vs SI).
    
    Since we only have XAU data, we compute an intra-asset SMT proxy:
    Compare current-session momentum vs prior-session structure.
    If price makes a new session high but the impulse velocity is LOWER
    than the prior session → bearish divergence (SMT-proxy).
    Vice versa for bullish divergence.
    """
    if len(df) < 100:
        return {}

    closes = df["close"].astype(float).values
    atr    = _atr_series(df).iloc[-1]

    # Compare last 32 bars (1 session) vs prior 32 bars
    if len(closes) < 65:
        return {"smt_session_divergence": False}

    cur_session  = closes[-32:]
    prev_session = closes[-64:-32]

    cur_high_idx  = int(np.argmax(cur_session))
    cur_low_idx   = int(np.argmin(cur_session))
    prev_high     = float(np.max(prev_session))
    prev_low      = float(np.min(prev_session))
    cur_high      = float(np.max(cur_session))
    cur_low       = float(np.min(cur_session))

    # Momentum: average bar-to-bar change magnitude
    cur_momentum  = float(np.mean(np.abs(np.diff(cur_session))))
    prev_momentum = float(np.mean(np.abs(np.diff(prev_session))))

    # Bearish SMT proxy: new high but falling momentum
    bearish_smt = cur_high > prev_high and cur_momentum < prev_momentum * 0.75

    # Bullish SMT proxy: new low but rising momentum (spring)
    bullish_smt = cur_low < prev_low and cur_momentum > prev_momentum * 1.25

    divergence = bearish_smt or bullish_smt

    return {
        "smt_session_divergence": divergence,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Composite ICT Score
# ──────────────────────────────────────────────────────────────────────────────

def _compute_ict_score(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Aggregate ICT concept alignment into a single score and direction.
    More aligned concepts = higher conviction trade.
    """
    buy_signals  = []
    sell_signals = []

    # PD Array alignment
    if ctx.get("pd_discount"):          buy_signals.append("pd_discount")
    if ctx.get("pd_premium"):           sell_signals.append("pd_premium")

    # HTF bias
    if ctx.get("htf_daily_bias_bullish"):  buy_signals.append("htf_daily_bull")
    if ctx.get("htf_daily_bias_bearish"):  sell_signals.append("htf_daily_bear")
    if ctx.get("htf_weekly_bias_bullish"): buy_signals.append("htf_weekly_bull")
    if ctx.get("htf_weekly_bias_bearish"): sell_signals.append("htf_weekly_bear")

    # Session setups
    sb_dir = ctx.get("silver_bullet_direction", "NEUTRAL")
    if ctx.get("silver_bullet_active"):
        if sb_dir == "BUY":   buy_signals.append("silver_bullet")
        elif sb_dir == "SELL": sell_signals.append("silver_bullet")

    if ctx.get("judas_swing_buy"):   buy_signals.append("judas_swing")
    if ctx.get("judas_swing_sell"):  sell_signals.append("judas_swing")

    # Gaps (magnets)
    if ctx.get("ndog_bullish") or ctx.get("nwog_bullish"):
        buy_signals.append("opening_gap")
    if ctx.get("ndog_bearish") or ctx.get("nwog_bearish"):
        sell_signals.append("opening_gap")

    # Structure tools
    if ctx.get("propulsion_block_bullish"):  buy_signals.append("propulsion_ob")
    if ctx.get("propulsion_block_bearish"):  sell_signals.append("propulsion_ob")

    if ctx.get("ce_fvg_bullish_tested"):  buy_signals.append("ce_test")
    if ctx.get("ce_fvg_bearish_tested"):  sell_signals.append("ce_test")

    # MMS program
    if ctx.get("mms_buy_program"):   buy_signals.append("mms_buy_program")
    if ctx.get("mms_sell_program"):  sell_signals.append("mms_sell_program")

    # Liquidity void (reversal magnet)
    if ctx.get("liquidity_void_down"):  buy_signals.append("void_fill")
    if ctx.get("liquidity_void_up"):    sell_signals.append("void_fill")

    total = len(buy_signals) + len(sell_signals)
    if total == 0:
        return {"ict_setup_score": 0.0, "ict_setup_direction": "NEUTRAL", "ict_concepts_active": []}

    buy_score  = len(buy_signals)
    sell_score = len(sell_signals)

    if buy_score > sell_score:
        direction = "BUY"
        score = buy_score / max(total, 8)  # normalise against max ~8 possible signals
    elif sell_score > buy_score:
        direction = "SELL"
        score = sell_score / max(total, 8)
    else:
        direction = "NEUTRAL"
        score = 0.0

    all_active = buy_signals + sell_signals

    return {
        "ict_setup_score":     round(min(score, 1.0), 4),
        "ict_setup_direction": direction,
        "ict_concepts_active": all_active,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────

def compute_ict_context(sub_df: pd.DataFrame) -> dict[str, Any]:
    """
    Compute the complete ICT + MMS context for a single scanner bar.

    Parameters
    ----------
    sub_df : pd.DataFrame
        OHLCV DataFrame up to and including the current bar.
        Must have lowercase columns: open, high, low, close, volume.

    Returns
    -------
    dict
        Flat dictionary with all ICT/MMS fields.
        Safe to inject directly into the scanner record as `record["ict"]`.
    """
    ctx = _empty_context()

    if sub_df is None or len(sub_df) < 5:
        return ctx

    # Cap to most recent 500 bars to keep per-bar cost O(1) during training
    if len(sub_df) > 500:
        sub_df = sub_df.iloc[-500:]

    try:
        ctx.update(_compute_pd_array(sub_df))
    except Exception:
        pass

    try:
        ctx.update(_compute_htf_bias(sub_df))
    except Exception:
        pass

    try:
        ctx.update(_compute_judas_swing(sub_df))
    except Exception:
        pass

    try:
        ctx.update(_compute_silver_bullet(sub_df))
    except Exception:
        pass

    try:
        ctx.update(_compute_opening_gaps(sub_df))
    except Exception:
        pass

    try:
        ctx.update(_compute_propulsion_block(sub_df))
    except Exception:
        pass

    try:
        ctx.update(_compute_consequent_encroachment(sub_df))
    except Exception:
        pass

    try:
        ctx.update(_compute_liquidity_void(sub_df))
    except Exception:
        pass

    try:
        ctx.update(_compute_mms(sub_df))
    except Exception:
        pass

    try:
        ctx.update(_compute_smt_proxy(sub_df))
    except Exception:
        pass

    try:
        ctx.update(_compute_ict_score(ctx))
    except Exception:
        pass

    return ctx
