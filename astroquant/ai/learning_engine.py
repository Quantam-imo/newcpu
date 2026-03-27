import sqlite3

def analyze_performance():
    conn = sqlite3.connect("data/trades.db")
    c = conn.cursor()

    c.execute("SELECT signal, result FROM trades")
    data = c.fetchall()

    stats = {
        "BUY_win": 0,
        "BUY_loss": 0,
        "SELL_win": 0,
        "SELL_loss": 0
    }

    for signal, result in data:
        if signal == "BUY" and result == "WIN":
            stats["BUY_win"] += 1
        elif signal == "BUY":
            stats["BUY_loss"] += 1
        elif signal == "SELL" and result == "WIN":
            stats["SELL_win"] += 1
        elif signal == "SELL":
            stats["SELL_loss"] += 1

    conn.close()
    return stats
