import os
import sqlite3
from datetime import datetime, timezone

import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
DB_PATH = "ai_trade_journal.db"


def send_daily_summary(summary_text):
    if not BOT_TOKEN or not CHAT_ID:
        return {"ok": False, "reason": "telegram credentials missing"}

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": summary_text,
    }

    try:
        response = requests.post(url, json=payload, timeout=8)
        response.raise_for_status()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def build_daily_summary(equity, pnl, trades, win_rate, phase, volatility_mode="NORMAL"):
    return (
        "📊 AstroQuant Daily Report\n\n"
        f"Phase: {phase}\n"
        f"Equity: {equity:.2f}\n"
        f"Daily PnL: {pnl:.2f}\n"
        f"Trades: {trades}\n"
        f"Win Rate: {win_rate:.1f}%\n"
        f"Volatility: {volatility_mode}\n"
        "System Status: Stable"
    )


def daily_metrics_from_journal(now=None):
    now = now or datetime.now(timezone.utc)
    day_prefix = now.date().isoformat()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT result, pnl
        FROM trades
        WHERE timestamp LIKE ?
        """,
        (f"{day_prefix}%",),
    )
    rows = c.fetchall()
    conn.close()

    trades = len(rows)
    wins = sum(1 for result, _ in rows if str(result).upper() == "WIN")
    pnl = sum(float(pnl_value or 0.0) for _, pnl_value in rows)
    win_rate = (wins / trades) * 100 if trades > 0 else 0.0

    return {
        "trades": trades,
        "wins": wins,
        "pnl": pnl,
        "win_rate": win_rate,
    }
