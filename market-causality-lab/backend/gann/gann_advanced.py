import math


def gann_advanced(state, df):
    price = state["price"]

    # Price -> degree
    degree = (math.sqrt(price) * 180) % 360

    # Time cycle (simple bar count)
    time_cycle = len(df) % 90  # 90-bar cycle

    # Price-Time equality
    price_move = float(abs(df["close"].iloc[-1] - df["close"].iloc[-10]))
    time_move = 10

    equality = bool(abs(price_move - time_move) < 1)

    return {
        "degree": float(degree),
        "time_cycle": time_cycle,
        "price_time_equal": equality,
        "zone": "REVERSAL" if 170 < degree < 190 else "NORMAL",
    }