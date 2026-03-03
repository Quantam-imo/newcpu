import sqlite3
from pathlib import Path


DB_PATH = Path("prop_state.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS prop_state (
            id INTEGER PRIMARY KEY,
            phase TEXT,
            profitable_days INTEGER,
            daily_high REAL,
            static_floor REAL,
            trading_enabled INTEGER,
            funded_lock_level REAL,
            funded_base_floor REAL,
            consecutive_losses INTEGER,
            cooldown_active INTEGER,
            cooldown_end TEXT
        )
        """
    )
    for column_sql in [
        "ALTER TABLE prop_state ADD COLUMN funded_lock_level REAL",
        "ALTER TABLE prop_state ADD COLUMN funded_base_floor REAL",
        "ALTER TABLE prop_state ADD COLUMN consecutive_losses INTEGER",
        "ALTER TABLE prop_state ADD COLUMN cooldown_active INTEGER",
        "ALTER TABLE prop_state ADD COLUMN cooldown_end TEXT",
    ]:
        try:
            c.execute(column_sql)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def save_state(
    phase,
    profitable_days,
    daily_high,
    static_floor,
    trading_enabled,
    funded_lock_level,
    funded_base_floor,
    consecutive_losses,
    cooldown_active,
    cooldown_end,
):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM prop_state")
    c.execute(
        """
        INSERT INTO prop_state (
            phase, profitable_days, daily_high, static_floor, trading_enabled,
            funded_lock_level, funded_base_floor, consecutive_losses, cooldown_active, cooldown_end
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            phase,
            profitable_days,
            daily_high,
            static_floor,
            int(trading_enabled),
            funded_lock_level,
            funded_base_floor,
            consecutive_losses,
            int(cooldown_active),
            cooldown_end,
        ),
    )
    conn.commit()
    conn.close()


def load_state():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            phase, profitable_days, daily_high, static_floor, trading_enabled,
            funded_lock_level, funded_base_floor, consecutive_losses, cooldown_active, cooldown_end
        FROM prop_state
        LIMIT 1
        """
    )
    row = c.fetchone()
    conn.close()

    if row:
        return {
            "phase": row[0],
            "profitable_days": row[1],
            "daily_high": row[2],
            "static_floor": row[3],
            "trading_enabled": bool(row[4]),
            "funded_lock_level": row[5],
            "funded_base_floor": row[6],
            "consecutive_losses": row[7],
            "cooldown_active": bool(row[8]) if row[8] is not None else False,
            "cooldown_end": row[9],
        }

    return None
