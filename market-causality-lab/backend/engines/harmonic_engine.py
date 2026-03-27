def harmonic_engine(df):
    move1 = abs(df["close"].iloc[-20] - df["close"].iloc[-10])
    move2 = abs(df["close"].iloc[-10] - df["close"].iloc[-1])

    ratio = float(move2 / move1) if move1 != 0 else 0.0

    if 1.5 < ratio < 1.7:
        pattern = "1.618 EXTENSION"
    elif 0.9 < ratio < 1.1:
        pattern = "AB=CD"
    else:
        pattern = "NONE"

    return {"ratio": ratio, "pattern": pattern}