import pandas as pd

# -----------------------------
# 📊 MARKET STRUCTURE (BOS / CHoCH)
# -----------------------------
def detect_structure(df):
    highs = df["high"]
    lows = df["low"]

    if highs.iloc[-1] > highs.iloc[-2]:
        return "BOS_BULLISH"
    elif lows.iloc[-1] < lows.iloc[-2]:
        return "BOS_BEARISH"
    return "RANGE"

# -----------------------------
# 💧 LIQUIDITY SWEEP
# -----------------------------
def detect_liquidity_sweep(df):
    prev_high = df["high"].iloc[-2]
    prev_low = df["low"].iloc[-2]

    current_high = df["high"].iloc[-1]
    current_low = df["low"].iloc[-1]

    if current_high > prev_high:
        return "BUY_SIDE_LIQUIDITY_TAKEN"
    elif current_low < prev_low:
        return "SELL_SIDE_LIQUIDITY_TAKEN"
    return None

# -----------------------------
# ⚖️ FAIR VALUE GAP (FVG)
# -----------------------------
def detect_fvg(df):
    if len(df) < 3:
        return None

    c1 = df.iloc[-3]
    c2 = df.iloc[-2]
    c3 = df.iloc[-1]

    # Bullish FVG
    if c1["high"] < c3["low"]:
        return {
            "type": "BULLISH_FVG",
            "low": c1["high"],
            "high": c3["low"]
        }

    # Bearish FVG
    if c1["low"] > c3["high"]:
        return {
            "type": "BEARISH_FVG",
            "low": c3["high"],
            "high": c1["low"]
        }

    return None

# -----------------------------
# 🧱 ORDER BLOCK
# -----------------------------
def detect_order_block(df):
    last_candle = df.iloc[-2]

    if last_candle["close"] < last_candle["open"]:
        return {
            "type": "BEARISH_OB",
            "high": last_candle["high"],
            "low": last_candle["low"]
        }

    if last_candle["close"] > last_candle["open"]:
        return {
            "type": "BULLISH_OB",
            "high": last_candle["high"],
            "low": last_candle["low"]
        }

    return None

# -----------------------------
# 🐢 TURTLE SOUP (STOP HUNT REVERSAL)
# -----------------------------
def detect_turtle_soup(df):
    prev_high = df["high"].iloc[-3]
    prev_low = df["low"].iloc[-3]

    current_high = df["high"].iloc[-1]
    current_low = df["low"].iloc[-1]

    if current_high > prev_high and df["close"].iloc[-1] < prev_high:
        return "SELL_REVERSAL"

    if current_low < prev_low and df["close"].iloc[-1] > prev_low:
        return "BUY_REVERSAL"

    return None

# -----------------------------
# 🕐 SESSION BIAS (Simplified)
# -----------------------------
def session_bias(hour):
    if 7 <= hour <= 10:
        return "LONDON"
    elif 13 <= hour <= 16:
        return "NEW_YORK"
    return "ASIA"

# -----------------------------
# 🎯 FINAL ICT SIGNAL
# -----------------------------
def get_ict_signal(df):
    structure = detect_structure(df)
    liquidity = detect_liquidity_sweep(df)
    fvg = detect_fvg(df)
    ob = detect_order_block(df)
    turtle = detect_turtle_soup(df)

    score_buy = 0
    score_sell = 0

    # Liquidity logic
    if liquidity == "SELL_SIDE_LIQUIDITY_TAKEN":
        score_buy += 1
    elif liquidity == "BUY_SIDE_LIQUIDITY_TAKEN":
        score_sell += 1

    # Structure
    if structure == "BOS_BULLISH":
        score_buy += 1
    elif structure == "BOS_BEARISH":
        score_sell += 1

    # FVG
    if fvg:
        if fvg["type"] == "BULLISH_FVG":
            score_buy += 1
        else:
            score_sell += 1

    # Order Block
    if ob:
        if ob["type"] == "BULLISH_OB":
            score_buy += 1
        else:
            score_sell += 1

    # Turtle Soup
    if turtle == "BUY_REVERSAL":
        score_buy += 2
    elif turtle == "SELL_REVERSAL":
        score_sell += 2

    # Final decision
    if score_buy > score_sell:
        return {
            "signal": "BUY",
            "confidence": score_buy,
            "sl_points": 20,
            "tp_points": 60
        }

    elif score_sell > score_buy:
        return {
            "signal": "SELL",
            "confidence": score_sell,
            "sl_points": 20,
            "tp_points": 60
        }

    return {
        "signal": "NO_TRADE",
        "confidence": 0
    }
