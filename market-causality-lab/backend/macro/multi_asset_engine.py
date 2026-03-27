def multi_asset_engine(gold, usd, bonds):
    insight = {}

    # Gold vs USD
    if usd["trend"] == "DOWN" and gold["trend"] == "UP":
        insight["gold_usd"] = "STRONG BULLISH GOLD"

    # Gold vs Bonds
    if bonds["trend"] == "DOWN":
        insight["real_yield"] = "SUPPORT GOLD"

    return insight