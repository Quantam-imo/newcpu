# Database layer for AstroQuant
import sqlite3
import os

DB_PATH = os.getenv("ASTROQUANT_DB_PATH", "astroquant.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    with open(os.path.join(os.path.dirname(__file__), "../../data/schema.sql")) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
