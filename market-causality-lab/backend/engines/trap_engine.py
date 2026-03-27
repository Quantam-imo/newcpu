def trap_engine(state, liquidity, phase):
    trap = "NONE"

    # Classic trap logic
    if phase == "MANIPULATION":
        if liquidity["type"] == "BUY_SIDE_SWEEP" and state["trend"] == "UP":
            trap = "BUYER_TRAP"

        elif liquidity["type"] == "SELL_SIDE_SWEEP" and state["trend"] == "DOWN":
            trap = "SELLER_TRAP"

    return {"trap": trap, "probability": 0.7 if trap != "NONE" else 0.2}