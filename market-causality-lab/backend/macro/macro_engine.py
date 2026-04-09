def macro_engine(inflation, rates):
    real_rate = rates - inflation  # negative = gold bullish

    if inflation > 5 and rates < 5:
        return "GOLD BULLISH"  # stagflation / high inflation, low rates

    if real_rate < -1.0:
        return "GOLD BULLISH"  # negative real rates favour gold

    if real_rate > 1.5:
        return "GOLD BEARISH"  # strongly positive real rates hurt gold

    if rates > inflation:
        return "GOLD BEARISH"  # real rate positive, mild headwind

    if inflation > rates:
        return "GOLD BULLISH"  # inflation premium, gold-supportive

    return "GOLD NEUTRAL"  # rates ~= inflation, no clear macro edge

    return "NEUTRAL"