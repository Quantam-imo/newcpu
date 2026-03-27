def sync_engine(state, physics, gann, liquidity, phase):
    score = 0

    # Physics
    if physics["force"] > 1:
        score += 1

    # Liquidity
    if liquidity["type"] == "SELL_SIDE_SWEEP":
        score += 1

    if liquidity["type"] == "BUY_SIDE_SWEEP":
        score -= 1

    # Gann
    if gann["zone"] == "REVERSAL":
        score -= 1

    # Phase bias
    if phase == "EXPANSION":
        score += 1

    if score > 1:
        # Accuracy Pass v2: EXPANSION + DOWN trend = 19% precision (anti-signal)
        # Only emit BUY if the 10-bar trend confirms the expansion direction.
        if phase == "EXPANSION" and state["trend"] == "DOWN":
            return "WAIT"
        return "BUY"

    if score < -1:
        return "SELL"

    return "WAIT"


def institutional_sync(signals, macro, capital_flow):
    score = {"BUY": 0, "SELL": 0}

    for s in signals.values():
        if s in score:
            score[s] += 1

    # Macro influence
    if macro == "GOLD BULLISH":
        score["BUY"] += 2

    if capital_flow == "SAFE HAVEN FLOW":
        score["BUY"] += 2

    return max(score, key=score.get), score