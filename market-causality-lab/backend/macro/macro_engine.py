def macro_engine(inflation, rates):
    if inflation > 5 and rates < 5:
        return "GOLD BULLISH"

    if rates > inflation:
        return "GOLD BEARISH"

    return "NEUTRAL"