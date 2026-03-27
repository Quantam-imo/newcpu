import sqlite3

def init_db():
    conn = sqlite3.connect("data/trades.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY,
        timestamp TEXT,
        signal TEXT,
        entry REAL,
        sl REAL,
        tp REAL,
        result TEXT,
        profit REAL
    )
    """)

    conn.commit()
    conn.close()
