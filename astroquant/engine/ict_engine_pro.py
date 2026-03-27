import pandas as pd

# -----------------------------
# 📊 HTF BIAS (Higher Timeframe)
# -----------------------------
def get_htf_bias(htf_df):
    if htf_df["close"].iloc[-1] > htf_df["close"].iloc[-5]:
        return "BULLISH"
    elif htf_df["close"].iloc[-1] < htf_df["close"].iloc[-5]:
        return "BEARISH"
    return "RANGE"

# -----------------------------
# ⚖️ PREMIUM / DISCOUNT ZONE
# -----------------------------
def get_pd_zone(df):
    high = df["high"].max()
    low = df["low"].min()
    eq = (high + low) / 2

    price = df["close"].iloc[-1]

    if price < eq:
        return "DISCOUNT"
    else:
        return "PREMIUM"

# -----------------------------
# 💧 LIQUIDITY POOLS (Equal Highs/Lows)
# -----------------------------
def detect_liquidity_pool(df):
    highs = df["high"].rolling(5).max()
    lows = df["low"].rolling(5).min()

    if abs(highs.iloc[-1] - highs.iloc[-2]) < 0.5:
        return "EQUAL_HIGHS"

    if abs(lows.iloc[-1] - lows.iloc[-2]) < 0.5:
        return "EQUAL_LOWS"

    return None

# -----------------------------
# 🕐 KILLZONES (UTC adjust if needed)
# -----------------------------
def killzone_filter(hour):
    if 7 <= hour <= 10:
        return "LONDON_KILLZONE"
    elif 13 <= hour <= 16:
        return "NY_KILLZONE"
    return "OFF_SESSION"

# -----------------------------
# 🔀 SMT DIVERGENCE (XAU vs DXY or BTC)
# -----------------------------
def detect_smt(df1, df2):
    if df1["high"].iloc[-1] > df1["high"].iloc[-2] and df2["high"].iloc[-1] <= df2["high"].iloc[-2]:
        return "BEARISH_SMT"

    if df1["low"].iloc[-1] < df1["low"].iloc[-2] and df2["low"].iloc[-1] >= df2["low"].iloc[-2]:
        return "BULLISH_SMT"

    return None

# -----------------------------
# 🎯 ENTRY MODEL (INSTITUTIONAL LOGIC)
# -----------------------------
def entry_model(htf_bias, pd_zone, liquidity, smt, killzone):
    score_buy = 0
    score_sell = 0

    # HTF Bias
    if htf_bias == "BULLISH":
        score_buy += 2
    elif htf_bias == "BEARISH":
        score_sell += 2

    # PD Array
    if pd_zone == "DISCOUNT":
        score_buy += 1
    else:
        score_sell += 1

    # Liquidity
    if liquidity == "EQUAL_LOWS":
        score_buy += 1
    elif liquidity == "EQUAL_HIGHS":
        score_sell += 1

    # SMT
    if smt == "BULLISH_SMT":
        score_buy += 2
    elif smt == "BEARISH_SMT":
        score_sell += 2

    # Killzone boost
    if killzone != "OFF_SESSION":
        score_buy += 1
        score_sell += 1

    # FINAL DECISION
    if score_buy > score_sell:
        return {
            "signal": "BUY",
            "confidence": score_buy,
            "sl_points": 25,
            "tp_points": 80
        }

    elif score_sell > score_buy:
        return {
            "signal": "SELL",
            "confidence": score_sell,
            "sl_points": 25,
            "tp_points": 80
        }

    return {"signal": "NO_TRADE"}
