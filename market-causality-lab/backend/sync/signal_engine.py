def generate_signals(state, liquidity, gann, ai_decision):
    signals = {}

    # Structure bias
    signals["structure"] = "BUY" if state["trend"] == "UP" else "SELL"

    # Liquidity — ICT/SMC sweep detection with price-zone proximity fallback
    if liquidity["type"] == "SELL_SIDE_SWEEP":
        signals["liquidity"] = "BUY"   # swept sell-side lows → reversal up expected
    elif liquidity["type"] == "BUY_SIDE_SWEEP":
        signals["liquidity"] = "SELL"  # swept buy-side highs → reversal down expected
    else:
        # No sweep: use price position relative to liquidity zones
        price = float(state.get("price", 0) or 0)
        above = float(liquidity.get("above", price + 1))
        below = float(liquidity.get("below", price - 1))
        if price > 0 and above > below:
            dist_above = above - price
            dist_below = price - below
            if dist_above < dist_below:
                # Price closer to upper pool — targeting upper liquidity
                signals["liquidity"] = "BUY"
            elif state.get("trend") == "DOWN":
                signals["liquidity"] = "SELL"
            else:
                signals["liquidity"] = "BUY"
        else:
            signals["liquidity"] = "NEUTRAL"

    # Gann
    signals["gann"] = "SELL" if gann["zone"] == "REVERSAL" else "BUY"

    # AI
    signals["ai"] = ai_decision

    return signals
