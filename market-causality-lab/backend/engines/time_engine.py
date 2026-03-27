def time_engine(gann, astro):
    signals = []

    if gann["price_time_equal"]:
        signals.append("GANN TURN")

    if astro["strength"] == "HIGH":
        signals.append("ASTRO WINDOW")

    if len(signals) >= 2:
        timing = "STRONG TURN WINDOW"
    elif len(signals) == 1:
        timing = "POSSIBLE TURN"
    else:
        timing = "NO SIGNAL"

    return {"signals": signals, "timing": timing}