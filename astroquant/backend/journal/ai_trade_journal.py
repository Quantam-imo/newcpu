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


def generate_narrative(model, volatility, session, news_status, rr, htf_bias="NEUTRAL", ltf_structure="RANGE"):
    bias_map = {
        "BULLISH": "bullish institutional conviction — targeting liquidity above",
        "BEARISH": "bearish institutional conviction — targeting liquidity below",
        "NEUTRAL": "neutral bias — no directional edge confirmed",
        "UNKNOWN": "indeterminate bias — insufficient data",
    }
    structure_map = {
        "EXPANSION": "price in expansion / breakout phase",
        "TREND": "trending market structure",
        "RANGE": "ranging / consolidating structure",
    }
    bias_text = bias_map.get(str(htf_bias).upper(), f"{htf_bias} bias")
    structure_text = structure_map.get(str(ltf_structure).upper(), f"{ltf_structure} structure")
    return (
        f"HTF: {bias_text}. LTF: {structure_text}. "
        f"Active {model} setup during {session} session. "
        f"Volatility: {volatility} | News: {news_status} | R:R {rr}. "
        f"Monitor for institutional sweep confirmation before entry."
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
