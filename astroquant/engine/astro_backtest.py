import pandas as pd
from astroquant.engine.astro_signal_pro import get_astro_signal

def run_backtest(df):
    results = []
    for i in range(50, len(df)):
        sample = df.iloc[:i]
        signal = get_astro_signal()
        price = sample["close"].iloc[-1]
        next_price = df["close"].iloc[i]
        if signal == "BUY":
            result = "WIN" if next_price > price else "LOSS"
        elif signal == "SELL":
            result = "WIN" if next_price < price else "LOSS"
        else:
            result = "SKIP"
        results.append(result)
    win_rate = results.count("WIN") / len(results) if results else 0
    return {
        "total": len(results),
        "win_rate": round(win_rate * 100, 2)
    }
