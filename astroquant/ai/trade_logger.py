import sqlite3
from datetime import datetime

def log_trade(signal, entry, sl, tp):
    conn = sqlite3.connect("data/trades.db")
    c = conn.cursor()

    c.execute("""
    INSERT INTO trades (timestamp, signal, entry, sl, tp, result, profit)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (datetime.now(), signal, entry, sl, tp, "OPEN", 0))

    conn.commit()
    conn.close()
