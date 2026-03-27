def filter_signal(signal, confidence, phase=None):
    if confidence < 0.6:
        return "WAIT"

    # Accuracy Pass v1: MANIPULATION is an anti-signal (2.6% precision);
    # suppress directional calls in this phase entirely.
    if phase == "MANIPULATION" and signal in ("BUY", "SELL"):
        return "WAIT"

    # Stricter gate for EXPANSION — only pass directional signals with strong conviction
    if phase == "EXPANSION" and signal in ("BUY", "SELL") and confidence < 0.75:
        return "WAIT"

    if signal == "BUY" and confidence > 0.7:
        return "STRONG BUY"

    if signal == "SELL" and confidence > 0.7:
        return "STRONG SELL"

    return signal