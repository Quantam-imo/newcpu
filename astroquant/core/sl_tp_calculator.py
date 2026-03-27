def calculate_sl_tp(entry_price, direction):
    if direction == "BUY":
        sl = entry_price - 10   # example points
        tp = entry_price + 20
    else:
        sl = entry_price + 10
        tp = entry_price - 20
    return sl, tp
