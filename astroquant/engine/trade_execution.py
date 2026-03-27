from astroquant.engine.broker_api import place_order

def execute_trade(signal, price):
    trade = {}

    if signal["action"] == "BUY":
        trade = {
            "entry": price,
            "sl": price - 20,
            "tp": price + 60
        }

    elif signal["action"] == "SELL":
        trade = {
            "entry": price,
            "sl": price + 20,
            "tp": price - 60
        }

    place_order(trade)
    return trade
