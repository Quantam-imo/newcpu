def phase_engine(state, liquidity):
    # Accumulation
    if abs(state["momentum"]) < 0.5 and state["volatility"] < 2:
        return "ACCUMULATION"

    # Manipulation (with sweep)
    if liquidity["type"] != "NO_SWEEP":
        return "MANIPULATION"

    # Expansion (strong move)
    if abs(state["momentum"]) > 1.5:
        return "EXPANSION"

    # Distribution (exhaustion)
    if abs(state["momentum"]) < 0.3 and state["volatility"] > 2:
        return "DISTRIBUTION"

    # Default: no clear phase signal → consolidation
    return "CONSOLIDATION"

    return "NEUTRAL"