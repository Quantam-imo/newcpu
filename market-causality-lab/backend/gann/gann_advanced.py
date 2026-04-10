import math


def gann_advanced(state, df):
    price = state["price"]

    # Price -> degree (Square-of-Nine: sqrt × 180, mod 360)
    degree = (math.sqrt(price) * 180) % 360

    # Time cycle (simple bar count within 90-bar Gann cycle)
    time_cycle = len(df) % 90

    # Price-Time equality — Gann's core balance law
    # Measured in SQ9 degree-units: |Δsqrt(price) × 360| should ≈ 10 bars
    # This normalises for any price level (gold, ES, crypto, etc.)
    close_now  = float(df["close"].iloc[-1])
    close_prev = float(df["close"].iloc[-10]) if len(df) >= 10 else close_now
    price_move_degrees = abs(math.sqrt(max(close_now, 1e-9)) - math.sqrt(max(close_prev, 1e-9))) * 360
    time_bars = 10
    pt_ratio  = price_move_degrees / time_bars if time_bars > 0 else 1.0
    equality  = bool(0.90 <= pt_ratio <= 1.10)  # balanced within 10% of 1:1 angle

    return {
        "degree": float(degree),
        "time_cycle": time_cycle,
        "price_time_equal": equality,
        "price_time_ratio": round(pt_ratio, 4),
        "zone": "REVERSAL" if 170 < degree < 190 else "NORMAL",
    }