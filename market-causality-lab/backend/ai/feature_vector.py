def create_feature_vector(record):
    state = record["state"]
    physics = record["physics"]
    gann = record["gann"]
    liquidity = record["liquidity"]
    phase = record["phase"]

    phase_map = {
        "ACCUMULATION": 0,
        "MANIPULATION": 1,
        "EXPANSION": 2,
        "DISTRIBUTION": 3,
        "NEUTRAL": 4,
    }

    vector = [
        1 if state["trend"] == "UP" else -1,
        state["momentum"],
        state["volatility"],
        physics["force"],
        physics["velocity"],
        1 if gann["zone"] == "REVERSAL" else 0,
        1 if liquidity["type"] == "BUY_SIDE_SWEEP" else 0,
        1 if liquidity["type"] == "SELL_SIDE_SWEEP" else 0,
        phase_map.get(phase, 9),
    ]

    return vector