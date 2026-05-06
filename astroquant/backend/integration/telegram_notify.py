import os
import sqlite3
from datetime import date, datetime, timezone, timedelta

import requests

_IST = timezone(timedelta(hours=5, minutes=30))


def _to_ist_label(ts_str: str) -> str:
    """Convert an ISO UTC timestamp string to a short IST display label."""
    try:
        dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        return dt.astimezone(_IST).strftime("%I:%M %p IST")
    except Exception:
        try:
            return str(ts_str).split("T", 1)[1][:8] if "T" in str(ts_str) else str(ts_str)
        except Exception:
            return str(ts_str)

DB_PATH = "ai_trade_journal.db"


def _telegram_credentials():
    token = (
        os.getenv("TELEGRAM_HEALTH_BOT_TOKEN", "").strip()
        or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    )
    chat_id = (
        os.getenv("TELEGRAM_HEALTH_CHAT_ID", "").strip()
        or os.getenv("TELEGRAM_CHAT_ID", "").strip()
    )
    return token, chat_id


def send_daily_summary(summary_text):
    bot_token, chat_id = _telegram_credentials()
    if not bot_token or not chat_id:
        return {"ok": False, "reason": "telegram credentials missing"}

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": summary_text,
    }

    try:
        response = requests.post(url, json=payload, timeout=8)
        response.raise_for_status()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _target_day_prefix(target_day: date | str | None = None):
    # Use IST date so midnight-crossing doesn't log to the wrong day
    if target_day is None:
        return datetime.now(_IST).date().isoformat()
    if isinstance(target_day, date):
        return target_day.isoformat()
    raw = str(target_day).strip()
    if not raw:
        return datetime.now(_IST).date().isoformat()
    return raw


def daily_journal_rows(target_day: date | str | None = None, limit: int = 5):
    day_prefix = _target_day_prefix(target_day)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT timestamp, symbol, model, result, pnl, r_multiple, confidence
        FROM trades
        WHERE timestamp LIKE ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (f"{day_prefix}%", max(1, int(limit or 5))),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def _format_journal_block(rows):
    if not rows:
        return "Journal: No trades logged for day."

    lines = ["Journal (latest):"]
    for idx, row in enumerate(rows, start=1):
        ts, symbol, model, result, pnl, r_multiple, confidence = row
        time_label = _to_ist_label(ts)
        pnl_val = float(pnl or 0.0)
        rr_val = float(r_multiple or 0.0)
        conf_val = float(confidence or 0.0)
        pnl_sign = "+" if pnl_val >= 0 else ""
        result_upper = str(result or "--").upper()
        lines.append(
            f"{idx}. {time_label} | {symbol} {model} {result_upper} | PnL {pnl_sign}{pnl_val:.2f} | R {rr_val:.2f}"
        )
    return "\n".join(lines)


def build_daily_summary(equity, pnl, trades, win_rate, phase, volatility_mode="NORMAL", report_day=None, journal_rows=None):
    day_label = _target_day_prefix(report_day)
    journal_block = _format_journal_block(list(journal_rows or []))
    return (
        "📊 AstroQuant Daily Report\n\n"
        f"Day: {day_label}\n"
        f"Phase: {phase}\n"
        f"Equity: {equity:.2f}\n"
        f"Daily PnL: {pnl:.2f}\n"
        f"Trades: {trades}\n"
        f"Win Rate: {win_rate:.1f}%\n"
        f"Volatility: {volatility_mode}\n"
        "System Status: Stable\n\n"
        f"{journal_block}"
    )


def daily_metrics_from_journal(now=None, target_day: date | str | None = None):
    now = now or datetime.now(_IST)
    day_prefix = _target_day_prefix(target_day if target_day is not None else now.date())

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
