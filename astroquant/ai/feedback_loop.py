from astroquant.ai.learning_engine import analyze_performance

def adjust_strategy():
    stats = analyze_performance()

    if stats["BUY_loss"] > stats["BUY_win"]:
        return {"bias": "REDUCE_BUY"}

    if stats["SELL_loss"] > stats["SELL_win"]:
        return {"bias": "REDUCE_SELL"}

    return {"bias": "NORMAL"}
