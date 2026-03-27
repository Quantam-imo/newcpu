def scenario_engine(dominant, confidence):
    scenarios = {}

    if dominant == "BUY":
        scenarios["best"] = "STRONG BULLISH MOVE"
        scenarios["worst"] = "FAKE BREAKOUT DOWN"
    elif dominant == "SELL":
        scenarios["best"] = "STRONG BEARISH MOVE"
        scenarios["worst"] = "SHORT SQUEEZE UP"
    else:
        scenarios["best"] = "SIDEWAYS"
        scenarios["worst"] = "VOLATILE WHIPSAW"

    scenarios["confidence"] = confidence

    return scenarios