def build_state(df):
    if len(df) < 10:
        raise ValueError("Need at least 10 rows to build state")

    last = df.iloc[-1]

    state = {}
    state["price"] = float(last["close"])

    # Simple structure
    state["trend"] = "UP" if df["close"].iloc[-1] > df["close"].iloc[-10] else "DOWN"

    # Momentum
    state["momentum"] = float(df["close"].iloc[-1] - df["close"].iloc[-5])

    # Volatility
    state["volatility"] = float((df["high"] - df["low"]).rolling(10).mean().iloc[-1])

    return state