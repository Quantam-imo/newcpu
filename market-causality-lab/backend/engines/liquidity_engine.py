def liquidity_engine(df):
    highs = df["high"].rolling(10).max()
    lows = df["low"].rolling(10).min()

    last = df.iloc[-1]

    liquidity = {}

    # Buy-side liquidity (above highs)
    if last["close"] > highs.iloc[-2]:
        liquidity["type"] = "BUY_SIDE_SWEEP"
    # Sell-side liquidity
    elif last["close"] < lows.iloc[-2]:
        liquidity["type"] = "SELL_SIDE_SWEEP"
    else:
        liquidity["type"] = "NO_SWEEP"

    # Liquidity zones
    liquidity["above"] = highs.iloc[-2]
    liquidity["below"] = lows.iloc[-2]

    return liquidity