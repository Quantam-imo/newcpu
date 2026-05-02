def generate_signals(state, liquidity, gann, ai_decision):
    signals = {}

    # Structure bias
    signals["structure"] = "BUY" if state["trend"] == "UP" else "SELL"

    # Liquidity — sweep detection + directional bias when no sweep
    if liquidity["type"] == "SELL_SIDE_SWEEP":
        signals["liquidity"] = "BUY"   # sell-side swept → smart money buying
    elif liquidity["type"] == "BUY_SIDE_SWEEP":
        signals["liquidity"] = "SELL"  # buy-side swept → smart money distributing
    else:
        # No sweep: price between zones — use distance to nearest pool
        price = float(state.get("price", 0))
        above = float(liquidity.get("above") or 0)
        below = float(liquidity.get("below") or 0)
        if price > 0 and above > 0 and below > 0 and above != below:
            # Price closer to upper pool → targeting upper liquidity (BUY bias)
            # Price closer to lower pool → targeting lower liquidity (SELL bias)
            dist_above = abs(above - price)
            dist_below = abs(price - below)
            if dist_above < dist_below * 0.8:
                signals["liquidity"] = "SELL"  # near upper pool, risk of sell sweep
            elif dist_below < dist_above * 0.8:
                signals["liquidity"] = "BUY"   # near lower pool, risk of buy sweep
            else:
                signals["liquidity"] = "NEUTRAL"  # equidistant, no directional edge
        else:
            signals["liquidity"] = "NEUTRAL"

    # Gann
    signals["gann"] = "SELL" if gann["zone"] == "REVERSAL" else "BUY"

    # AI
    signals["ai"] = ai_decision

    return signals