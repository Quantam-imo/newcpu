def macro_engine(inflation, rates):
    """
    Gann macro context for gold.
    Real rate = rates - inflation. Negative real rate → gold bullish.
    """
    real_rate = rates - inflation

    if inflation > 5 and rates < inflation:
        return "GOLD BULLISH"       # stagflation / high inflation with soft real rate

    if real_rate < 0:
        return "GOLD MILD BULLISH"  # inflation premium, negative real rates

    if rates > inflation + 1.0:
        return "GOLD BEARISH"       # real rates significantly positive

    return "GOLD NEUTRAL"           # roughly balanced
