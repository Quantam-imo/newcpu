def weight_engine(state, phase):
    weights = {
        "liquidity": 3,
        "psychology": 2,
        "physics": 2,
        "gann": 2,
        "astro": 2,
        "ai": 3,
        "harmonic": 1,
        "numerology": 1,
    }

    # Dynamic adjustments
    if phase == "EXPANSION":
        weights["physics"] += 1

    if phase == "MANIPULATION":
        weights["liquidity"] += 1
        weights["psychology"] += 1

    return weights