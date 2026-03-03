import sqlite3
from datetime import datetime, timezone

DB_PATH = "ai_trade_journal.db"


def init_journal():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            phase TEXT,
            symbol TEXT,
            model TEXT,
            entry_reason TEXT,
            risk REAL,
            volatility TEXT,
            session TEXT,
            news_status TEXT,
            rr REAL,
            entry_price REAL,
            sl REAL,
            tp REAL,
            exit_price REAL,
            result TEXT,
            r_multiple REAL,
            pnl REAL,
            confidence REAL,
            governance_snapshot TEXT,
            narrative TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def generate_narrative(model, volatility, session, news_status, rr):
    return (
        f"Trade executed using {model} model during {session} session. "
        f"Volatility state: {volatility}. "
        f"News status: {news_status}. "
        f"Risk-reward ratio set at {rr}. "
        f"Entry aligned with institutional liquidity structure."
    )


def save_trade(trade_data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        INSERT INTO trades (
            timestamp, phase, symbol, model, entry_reason, risk,
            volatility, session, news_status, rr,
            entry_price, sl, tp, exit_price,
            result, r_multiple, pnl, confidence, governance_snapshot, narrative
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            trade_data.get("phase"),
            trade_data.get("symbol"),
            trade_data.get("model"),
            trade_data.get("entry_reason"),
            trade_data.get("risk"),
            trade_data.get("volatility"),
            trade_data.get("session"),
            trade_data.get("news_status"),
            trade_data.get("rr"),
            trade_data.get("entry_price"),
            trade_data.get("sl"),
            trade_data.get("tp"),
            trade_data.get("exit_price"),
            trade_data.get("result"),
            trade_data.get("r_multiple"),
            trade_data.get("pnl"),
            trade_data.get("confidence"),
            trade_data.get("governance_snapshot"),
            trade_data.get("narrative"),
        ),
    )

    conn.commit()
    conn.close()


def recent_trades(limit=50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT timestamp, model, result, r_multiple, pnl, phase
        FROM trades
        ORDER BY id DESC
        LIMIT ?
        """,
        (int(limit),),
    )
    rows = c.fetchall()
    conn.close()
    return rows
