def ai_decision(prob):
    if prob["BUY"] > 0.6:
        return "BUY"

    if prob["SELL"] > 0.6:
        return "SELL"

    return "WAIT"