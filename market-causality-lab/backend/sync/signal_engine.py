def generate_signals(state, liquidity, gann, ai_decision):
    signals = {}

    # Structure bias
    signals["structure"] = "BUY" if state["trend"] == "UP" else "SELL"

    # Liquidity
    if liquidity["type"] == "SELL_SIDE_SWEEP":
        signals["liquidity"] = "BUY"
    elif liquidity["type"] == "BUY_SIDE_SWEEP":
        signals["liquidity"] = "SELL"
    else:
        signals["liquidity"] = "NEUTRAL"

    # Gann
    signals["gann"] = "SELL" if gann["zone"] == "REVERSAL" else "BUY"

    # AI
    signals["ai"] = ai_decision

    return signals