def optimize_entry(signal, current_price):
    spread_buffer = 2

    if signal["action"] == "BUY":
        entry = current_price - spread_buffer
    else:
        entry = current_price + spread_buffer

    return {
        "entry": entry,
        "sl": signal["sl"],
        "tp": signal["tp"]
    }
