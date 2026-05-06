#!/usr/bin/env python3
"""AstroQuant Telegram daemon.

Features:
- Chat commands: /status, /signals, /news, /report, /links, /help
- Periodic reports with system health, signals, and news context
- Event-driven alerts when key signal bias changes or news halt changes
- Daily scheduled summary and trade-journal digest

Env (.env):
- TELEGRAM_ALERT_ENABLED=true
- TELEGRAM_BOT_TOKEN=<token>          # legacy/default token fallback
- TELEGRAM_UPDATES_BOT_TOKEN=<token>  # optional: MCL/news/signal channel bot token
- TELEGRAM_HEALTH_BOT_TOKEN=<token>   # optional: health/system channel bot token
- TELEGRAM_COMMAND_BOT_TOKEN=<token>  # optional: command polling bot token
- TELEGRAM_CHAT_ID=<chat_id>          # legacy/default chat fallback
- TELEGRAM_COMMAND_CHAT_ID=<chat_id>  # optional: command chat
- TELEGRAM_SIGNALS_CHAT_ID=<chat_id>  # optional: signals+trades only (falls back to CHAT_ID)
- TELEGRAM_HEALTH_CHAT_ID=<chat_id>   # optional: reports+health only  (falls back to CHAT_ID)
- TELEGRAM_REPORT_INTERVAL_SEC=1800
- TELEGRAM_SIGNAL_SYMBOL=XAUUSD
- TELEGRAM_REPORT_MODE=short|full
- TELEGRAM_DAILY_SUMMARY_ENABLED=true|false
- TELEGRAM_DAILY_SUMMARY_UTC=09:00
- TELEGRAM_DAEMON_HEALTH_INTERVAL_SEC=1800
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import atexit
import signal
import subprocess
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import requests

# Indian Standard Time = UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))


def _now_ist() -> datetime:
    return datetime.now(_IST)


def _fmt_ist(dt: datetime = None) -> str:
    """Return a formatted IST timestamp string like '14:32 IST'."""
    d = (dt or _now_ist()).astimezone(_IST)
    return d.strftime("%d %b %Y %I:%M %p IST")


def _fmt_ist_short(dt: datetime = None) -> str:
    """Return short IST time like '14:32 IST'."""
    d = (dt or _now_ist()).astimezone(_IST)
    return d.strftime("%I:%M %p IST")

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR = WORKSPACE / "data"
LOG_DIR = DATA_DIR / "logs"
ENV_FILE = WORKSPACE / ".env"
STATE_FILE = DATA_DIR / "telegram_daemon_state.json"
LOG_FILE = LOG_DIR / "telegram_daemon.log"
PID_FILE = DATA_DIR / "telegram_daemon.pid"
_TOKEN_LOCK_FILE: Optional[Path] = None

LOG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
_ERROR_THROTTLE: Dict[str, float] = {}


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _log(msg: str) -> None:
    stamp = _now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {msg}\n")


def _api_base() -> str:
    return "http://127.0.0.1:8000"


def _default_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _updates_token() -> str:
    return os.getenv("TELEGRAM_UPDATES_BOT_TOKEN", "").strip() or _default_token()


def _health_token() -> str:
    return os.getenv("TELEGRAM_HEALTH_BOT_TOKEN", "").strip() or _default_token() or _updates_token()


def _command_token() -> str:
    return os.getenv("TELEGRAM_COMMAND_BOT_TOKEN", "").strip() or _updates_token() or _default_token()


def _chat_id() -> str:
    """Primary chat ID — used for command polling and as fallback for all channels."""
    return os.getenv("TELEGRAM_CHAT_ID", "").strip()


def _command_chat_id() -> str:
    return os.getenv("TELEGRAM_COMMAND_CHAT_ID", "").strip() or _chat_id()


def _signals_chat_id() -> str:
    """Chat ID for signal/trade alerts. Falls back to primary if not set."""
    return os.getenv("TELEGRAM_SIGNALS_CHAT_ID", "").strip() or _chat_id()


def _health_chat_id() -> str:
    """Chat ID for periodic reports and daemon health. Falls back to primary if not set."""
    return os.getenv("TELEGRAM_HEALTH_CHAT_ID", "").strip() or _chat_id()


# Signal directions that warrant a Telegram alert.
_ACTIONABLE_SIGNALS = frozenset({
    "BUY", "SELL", "STRONG BUY", "STRONG SELL", "BUY_LIMIT", "SELL_LIMIT",
})


def _enabled() -> bool:
    return os.getenv("TELEGRAM_ALERT_ENABLED", "false").strip().lower() == "true"


def _report_interval() -> int:
    try:
        return max(60, int(os.getenv("TELEGRAM_REPORT_INTERVAL_SEC", "1800")))
    except Exception:
        return 1800


# Futures alias → display symbol map.  Keeps messages using friendly names.
_SYMBOL_DISPLAY_MAP: dict[str, str] = {
    "GC.FUT": "XAUUSD",
    "GC.C.1": "XAUUSD",
    "GC.c.1": "XAUUSD",
    "NQ.FUT": "NQ",
    "NQ.C.1": "NQ",
    "NQ.c.1": "NQ",
    "6E.FUT": "EURUSD",
    "6E.C.1": "EURUSD",
    "6E.c.1": "EURUSD",
    "YM.FUT": "US30",
    "YM.C.1": "US30",
    "BTC.C.1": "BTC",
}


def _display_symbol(symbol: str) -> str:
    """Return the user-friendly display name for a symbol (e.g. GC.FUT → XAUUSD)."""
    return _SYMBOL_DISPLAY_MAP.get(symbol, _SYMBOL_DISPLAY_MAP.get(symbol.upper(), symbol))


def _signal_symbol() -> str:
    raw = os.getenv("TELEGRAM_SIGNAL_SYMBOL", "XAUUSD").strip() or "XAUUSD"
    return _display_symbol(raw)


def _signal_symbols() -> list[str]:
    raw = os.getenv("TELEGRAM_SIGNAL_SYMBOLS", "").strip()
    if not raw:
        return [_signal_symbol()]
    symbols = [_display_symbol(str(x).strip()) for x in raw.split(",") if str(x).strip()]
    if not symbols:
        return [_signal_symbol()]
    # Deduplicate while preserving order — GC.FUT and XAUUSD both map to XAUUSD
    out: list[str] = []
    for symbol in symbols:
        if symbol not in out:
            out.append(symbol)
    return out


def _report_mode() -> str:
    mode = os.getenv("TELEGRAM_REPORT_MODE", "full").strip().lower()
    return mode if mode in {"short", "full"} else "full"


def _daily_summary_enabled() -> bool:
    return os.getenv("TELEGRAM_DAILY_SUMMARY_ENABLED", "false").strip().lower() == "true"


def _daily_summary_utc() -> tuple[int, int]:
    raw = os.getenv("TELEGRAM_DAILY_SUMMARY_UTC", "09:00").strip()
    try:
        hour_s, minute_s = raw.split(":", 1)
        hour = max(0, min(23, int(hour_s)))
        minute = max(0, min(59, int(minute_s)))
        return hour, minute
    except Exception:
        return 9, 0


def _day_start_utc() -> tuple[int, int]:
    # Default = 03:45 UTC = 09:15 AM IST (NSE/BSE open, gold market active)
    raw = os.getenv("TELEGRAM_DAY_START_UTC", "03:45").strip()
    try:
        hour_s, minute_s = raw.split(":", 1)
        hour = max(0, min(23, int(hour_s)))
        minute = max(0, min(59, int(minute_s)))
        return hour, minute
    except Exception:
        return 3, 45


def _day_end_utc() -> tuple[int, int]:
    # Default = 18:00 UTC = 11:30 PM IST (after US session close)
    raw = os.getenv("TELEGRAM_DAY_END_UTC", "18:00").strip()
    try:
        hour_s, minute_s = raw.split(":", 1)
        hour = max(0, min(23, int(hour_s)))
        minute = max(0, min(59, int(minute_s)))
        return hour, minute
    except Exception:
        return 18, 0


def _day_boundary_reports_enabled() -> bool:
    return os.getenv("TELEGRAM_DAY_BOUNDARY_REPORTS_ENABLED", "true").strip().lower() == "true"


def _daemon_health_interval() -> int:
    try:
        return max(60, int(os.getenv("TELEGRAM_DAEMON_HEALTH_INTERVAL_SEC", "1800")))
    except Exception:
        return 1800


def _startup_online_cooldown_sec() -> int:
    try:
        return max(60, int(os.getenv("TELEGRAM_STARTUP_ALERT_COOLDOWN_SEC", "900")))
    except Exception:
        return 900


# Telegram hard limit for a single message.
_TG_MAX_CHARS = 4000


def _send_to(chat_id: str, text: str, *, token: str | None = None) -> bool:
    """Core sender — routes to a specific chat_id."""
    _token_value = str(token or "").strip()
    if not _token_value or not chat_id:
        _log("send skipped: missing Telegram token or chat_id")
        return False
    body = str(text or "")
    if len(body) > _TG_MAX_CHARS:
        body = body[:_TG_MAX_CHARS - 14] + "\n[...truncated]"
    try:
        url = f"https://api.telegram.org/bot{_token_value}/sendMessage"
        r = requests.post(url, json={"chat_id": chat_id, "text": body}, timeout=12)
        ok = r.status_code == 200
        if not ok:
            _log(f"send failed [{chat_id}]: HTTP {r.status_code} {r.text[:200]}")
        return ok
    except Exception as exc:
        _log(f"send exception [{chat_id}]: {exc}")
        return False


def _send_message(text: str) -> bool:
    """Send a signal/trade/news alert to the signals channel."""
    return _send_to(_signals_chat_id(), text, token=_updates_token())


def _send_health(text: str) -> bool:
    """Send a periodic report or daemon health message to the health channel."""
    return _send_to(_health_chat_id(), text, token=_health_token())


def _send_command(text: str) -> bool:
    """Send bot command replies to the command channel."""
    return _send_to(_command_chat_id(), text, token=_command_token())


def _market_reaction_snapshot(symbols: Optional[list] = None) -> str:
    """Return a compact market-reaction block for news event messages.

    Fetches live price from the 5m MCL chart and MCL bias/signal from the
    summary endpoint. Returns a multi-line string ready to append to any
    news alert message.
    """
    result_lines: list = []
    watch = symbols or [_signal_symbol()]
    for sym in watch[:3]:
        pct_move: Optional[float] = None
        try:
            # 1. Latest price + direction from 5m chart (last 6 candles)
            chart = _get_json("/market_causality/chart", params={"symbol": sym, "timeframe": "5m", "limit": 6})
            candles = chart.get("candles") or []
            price_line = ""
            if len(candles) >= 2:
                cur = candles[-1]
                ref = candles[-3] if len(candles) >= 3 else candles[0]
                close = float(cur["close"])
                ref_open = float(ref["open"])
                pct = (close - ref_open) / ref_open * 100 if ref_open else 0.0
                pct_move = pct
                rng = float(cur["high"]) - float(cur["low"])
                arrow = "▲" if close >= float(cur["open"]) else "▼"
                price_line = f"{arrow} {close:.2f} ({pct:+.2f}%) | Range: {rng:.2f}"
        except Exception:
            price_line = ""

        try:
            # 2. MCL bias / signal from summary endpoint
            summ = _get_json("/market_causality/summary", params={"symbol": sym, "timeframe": "15m"})
            signal_val = str(summ.get("signal") or "N/A")
            trend_val = str(summ.get("trend") or "N/A")
            conf_raw = summ.get("confidence")
            conf_str = f"{float(conf_raw) * 100:.0f}%" if conf_raw is not None else "N/A"
            reaction_sentiment = (
                "BULLISH reaction" if trend_val.lower() in ("bullish", "bull") else
                "BEARISH reaction" if trend_val.lower() in ("bearish", "bear") else
                "NEUTRAL/mixed"
            )
            # Explicit trend state for fast readability in Telegram.
            trend_state = "SIDEWAYS"
            if trend_val.lower() in ("bullish", "bull", "uptrend", "up"):
                trend_state = "UPTREND"
            elif trend_val.lower() in ("bearish", "bear", "downtrend", "down"):
                trend_state = "DOWNTREND"
            elif pct_move is not None:
                if pct_move >= 0.10:
                    trend_state = "UPTREND"
                elif pct_move <= -0.10:
                    trend_state = "DOWNTREND"

            bias_line = (
                f"{reaction_sentiment} | Trend: {trend_state} | "
                f"Bias: {trend_val.upper()} | Signal: {signal_val} ({conf_str})"
            )
        except Exception:
            bias_line = ""

        lines: list = [f"  [{sym}]"]
        if price_line:
            lines.append(f"    Price : {price_line}")
        if bias_line:
            lines.append(f"    MCL   : {bias_line}")
        if len(lines) > 1:
            result_lines.extend(lines)

    return "\n".join(result_lines) if result_lines else "  Market data unavailable"


def _market_hours_block(symbol: str = "XAUUSD") -> str:
    """Return a compact market-hours line for status reports.
    Example:  'Market: CLOSED (Weekend) — opens Today 22:00 UTC'
              'Market: OPEN | Early close today 18:30 UTC (Memorial Day)'
              'Market: OPEN'
    """
    try:
        from astroquant.engine.market_calendar import MarketCalendar
        info = MarketCalendar.get_session_info(symbol)
        if info["is_open"]:
            if info["is_early_close"]:
                ec = info.get("early_close_utc", "")[:16].replace("T", " ")
                name = info.get("holiday_name", "Early Close")
                return f"OPEN | Early close {ec} UTC ({name})"
            return "OPEN"
        else:
            reason = info.get("reason", "Closed")
            return f"CLOSED — {reason}"
    except Exception:
        return "OPEN"  # fallback


def _prepare_polling() -> None:
    token = _command_token()
    if not token:
        return
    try:
        # Ensure getUpdates long polling is allowed; webhook and polling cannot coexist.
        url = f"https://api.telegram.org/bot{token}/deleteWebhook"
        requests.post(url, data={"drop_pending_updates": "false"}, timeout=12)
    except Exception as exc:
        _throttled_error("telegram:deleteWebhook", f"deleteWebhook failed: {exc}", every_sec=600)


def _token_lock_path() -> Optional[Path]:
    token = _command_token()
    if not token:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return Path(f"/tmp/astroquant_telegram_{digest}.lock")


def _acquire_lock_file(lock_file: Path, pid: int) -> bool:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_file), flags)
        os.write(fd, str(pid).encode("utf-8"))
        os.close(fd)
        return True
    except FileExistsError:
        pass
    except Exception:
        return False

    try:
        old_pid = int(lock_file.read_text(encoding="utf-8").strip())
        os.kill(old_pid, 0)
        return False
    except Exception:
        try:
            lock_file.unlink(missing_ok=True)
        except Exception:
            return False

    try:
        fd = os.open(str(lock_file), flags)
        os.write(fd, str(pid).encode("utf-8"))
        os.close(fd)
        return True
    except Exception:
        return False


def _api_timeout(path: str) -> int:
    if path == "/ai/mentor":
        try:
            return max(5, int(os.getenv("TELEGRAM_MENTOR_TIMEOUT_SEC", "15")))
        except Exception:
            return 15
    try:
        return max(5, int(os.getenv("TELEGRAM_API_TIMEOUT_SEC", "10")))
    except Exception:
        return 10


def _throttled_error(key: str, message: str, every_sec: int = 120) -> None:
    now = time.time()
    last = _ERROR_THROTTLE.get(key, 0)
    if now - last >= every_sec:
        _ERROR_THROTTLE[key] = now
        _log(message)


def _get_json(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        r = requests.get(f"{_api_base()}{path}", params=params, timeout=_api_timeout(path))
        r.raise_for_status()
        return r.json() if r.text else {}
    except Exception as exc:
        _throttled_error(f"api:{path}", f"api error {path}: {exc}")
        return {}


def _load_state() -> Dict[str, Any]:
    default_state = {
        "last_update_id": 0,
        "last_report_ts": 0,
        "last_daemon_health_ts": 0,
        "last_online_alert_ts": 0,
        "last_bias": None,
        "last_bias_map": {},
        "last_signal_map": {},
        "last_astro_sig_map": {},
        "last_news_halt": None,
        "last_news_sig": "",
        "last_trade_key_map": {},
        "last_trade_alert_check_ts": 0,
        "last_mentor_poll_ts": 0,
        "last_day_start_report_date": "",
        "last_day_end_report_date": "",
        "last_daily_summary_date": "",
        "last_holiday_eve_alert_date": "",
        "last_mcl_daily_date": "",
    }
    if not STATE_FILE.exists():
        return default_state
    try:
        loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return default_state
        merged = dict(default_state)
        merged.update(loaded)
        return merged
    except Exception:
        return default_state


def _save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")


def _extract_signal_context(mentor_payload: Dict[str, Any]) -> Dict[str, Any]:
    # API response is double-nested: {"context": {"context": {market, model, astro, ...}}}
    outer = mentor_payload.get("context", {}) if isinstance(mentor_payload, dict) else {}
    inner = outer.get("context", {}) if isinstance(outer, dict) else {}
    # Fall back to outer if inner context is absent (older API format)
    ctx = inner if (isinstance(inner, dict) and inner) else (outer if isinstance(outer, dict) else {})

    market = ctx.get("market", {}) if isinstance(ctx, dict) else {}
    model_ctx = ctx.get("model", {}) if isinstance(ctx, dict) else {}

    # Resolve HTF/LTF/Vol/News from market sub-dict first, then ctx top-level as fallback
    htf_bias = (market.get("htf_bias") or ctx.get("htf_bias") or "N/A")
    ltf_structure = (market.get("ltf_structure") or ctx.get("ltf_structure") or "N/A")
    volatility = (market.get("volatility") or ctx.get("volatility_state") or ctx.get("volatility") or "N/A")
    news_state = (market.get("news_state") or ctx.get("news_state") or "N/A")

    # Normalize astro — API uses different key names and may have _engine: NOT_ACTIVE
    raw_astro = ctx.get("astro", {}) if isinstance(ctx, dict) else {}
    astro: Dict[str, Any] = {}
    if isinstance(raw_astro, dict) and raw_astro:
        engine_state = str(raw_astro.get("_engine", "")).upper()
        if engine_state == "NOT_ACTIVE":
            astro = {
                "harmonic_window": False,
                "astro_marker": "DISABLED",
                "astro_bias": "--",
                "signal": "N/A",
                "reason": "Astro engine not active",
            }
        else:
            astro = {
                "harmonic_window": raw_astro.get("harmonic_window", False),
                "astro_marker": raw_astro.get("astro_marker") or raw_astro.get("planet_event") or "N/A",
                "astro_bias": raw_astro.get("astro_bias") or raw_astro.get("bias") or "N/A",
                "signal": raw_astro.get("signal", "N/A"),
                "reason": raw_astro.get("reason", "N/A"),
            }

    # Signal: check model first, then walk the full context tree
    signal = model_ctx.get("signal") or model_ctx.get("action") or model_ctx.get("recommendation")
    if not signal:
        def walk(obj: Any) -> Optional[str]:
            if isinstance(obj, dict):
                for key in ("signal", "action", "recommendation"):
                    if key in obj and obj[key] not in (None, "", "N/A", "--"):
                        return str(obj[key])
                for v in obj.values():
                    out = walk(v)
                    if out:
                        return out
            elif isinstance(obj, list):
                for item in obj:
                    out = walk(item)
                    if out:
                        return out
            return None
        signal = walk(ctx)

    return {
        "signal": signal or "--",
        "htf_bias": htf_bias,
        "ltf_structure": ltf_structure,
        "volatility": volatility,
        "news_state": news_state,
        "astro": astro,
    }


def _links_block() -> str:
    app_url = (DATA_DIR / "tunnel_url.txt").read_text(encoding="utf-8", errors="ignore").strip() if (DATA_DIR / "tunnel_url.txt").exists() else "PENDING"
    desktop_url = (DATA_DIR / "novnc_tunnel_url.txt").read_text(encoding="utf-8", errors="ignore").strip() if (DATA_DIR / "novnc_tunnel_url.txt").exists() else "PENDING"
    return f"App: {app_url}\nDesktop: {desktop_url}"


def _journal_db_candidates() -> list[Path]:
    return [
        WORKSPACE / "ai_trade_journal.db",
        DATA_DIR / "ai_trade_journal.db",
        WORKSPACE / "data" / "ai_trade_journal.db",
    ]


def _trade_digest(limit: int = 50) -> Dict[str, Any]:
    db_path = next((p for p in _journal_db_candidates() if p.exists()), None)
    if not db_path:
        return {"ok": False, "reason": "journal_db_missing"}
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM trades")
        total = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT result, pnl
            FROM trades
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        conn.close()

        wins = 0
        losses = 0
        pnl_sum = 0.0
        for result, pnl in rows:
            try:
                pnl_val = float(pnl or 0.0)
            except Exception:
                pnl_val = 0.0
            pnl_sum += pnl_val
            if str(result).upper() in {"WIN", "TP", "PROFIT"} or pnl_val > 0:
                wins += 1
            elif str(result).upper() in {"LOSS", "SL"} or pnl_val < 0:
                losses += 1

        n = len(rows)
        win_rate = round((wins / n) * 100.0, 1) if n else 0.0
        return {
            "ok": True,
            "db": str(db_path),
            "total": total,
            "sampled": n,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "pnl_sum": round(pnl_sum, 2),
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _trade_digest_text() -> str:
    d = _trade_digest(limit=100)
    if not d.get("ok"):
        return f"Journal: unavailable ({d.get('reason', 'unknown')})"
    pnl_sign = "+" if float(d['pnl_sum']) >= 0 else ""
    wr = d['win_rate']
    wr_label = "STRONG" if wr >= 60 else ("OK" if wr >= 45 else "WEAK")
    return (
        f"Trade Journal\n"
        f"All-time trades : {d['total']}\n"
        f"Recent (last 100): {d['sampled']} | W {d['wins']} / L {d['losses']}\n"
        f"Win rate        : {wr}% [{wr_label}]\n"
        f"Recent PnL      : {pnl_sign}{d['pnl_sum']:.2f}"
    )


def _multi_symbol_signal_snapshot() -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for symbol in _signal_symbols():
        mentor = _get_json("/ai/mentor", params={"symbol": symbol})
        sig = _extract_signal_context(mentor)
        rows.append(
            {
                "symbol": symbol,
                "signal": str(sig.get("signal", "N/A")),
                "htf_bias": str(sig.get("htf_bias", "N/A")),
                "ltf_structure": str(sig.get("ltf_structure", "N/A")),
                "volatility": str(sig.get("volatility", "N/A")),
                "news_state": str(sig.get("news_state", "N/A")),
                "astro": dict(sig.get("astro", {}) if isinstance(sig.get("astro", {}), dict) else {}),
            }
        )
    return rows


def _multi_symbol_signals_text() -> str:
    rows = _multi_symbol_signal_snapshot()
    if not rows:
        return "Signals: no symbols configured"
    lines = [f"Signals ({len(rows)} symbol{'s' if len(rows) != 1 else ''}):"]
    for row in rows:
        news_flag = " [NEWS HALT]" if str(row.get('news_state', '')).upper() == 'HALT' else ""
        lines.append(
            f"  {row['symbol']}: {row['signal']} | HTF {row['htf_bias']} | "
            f"LTF {row['ltf_structure']} | Vol {row['volatility']}{news_flag}"
        )
    return "\n".join(lines)


def _build_status_report(mode: str = "full") -> str:
    status = _get_json("/status")
    health = status.get("system_health", {}) if isinstance(status, dict) else {}
    symbols = _signal_symbols()
    symbol = symbols[0]
    mentor = _get_json("/ai/mentor", params={"symbol": symbol})
    sig = _extract_signal_context(mentor)
    multi_symbol_block = _multi_symbol_signals_text()

    news_halt = status.get("news_halt", "N/A")
    next_news = status.get("next_news", [])
    # Format next_news properly — it's a list of dicts, not raw strings.
    if isinstance(next_news, list) and next_news:
        _news_parts = []
        for _item in next_news[:3]:
            if isinstance(_item, dict):
                _mins = _item.get("minutes_to_event")
                _timing = f"T-{int(_mins)}m" if _mins is not None else _item.get("time_utc", "")
                _news_parts.append(
                    f"{_item.get('currency','?')} {_item.get('title','?')} ({_timing}) [{_item.get('impact','?')}]"
                )
            else:
                _news_parts.append(str(_item))
        next_news_text = " | ".join(_news_parts)
    else:
        next_news_text = "None"

    news_halt_flag = " HALTED" if news_halt else ""
    market_hours = _market_hours_block(symbol)
    if mode == "short":
        return (
            f"AstroQuant [{_fmt_ist_short()}]\n"
            f"CPU {health.get('cpu_percent', '?')}% | MEM {health.get('memory_percent', '?')}%\n"
            f"{symbol}: {sig['signal']} | HTF {sig['htf_bias']} | Vol {sig['volatility']}\n"
            f"Market: {market_hours}\n"
            f"News:{news_halt_flag or ' clear'} | Broker: {health.get('broker', 'N/A')}\n"
            f"{_links_block()}"
        )

    digest = _trade_digest_text()
    return (
        f"AstroQuant Report\n"
        f"[{_fmt_ist()}]\n"
        f"\n"
        f"System\n"
        f"  CPU {health.get('cpu_percent', '?')}% | MEM {health.get('memory_percent', '?')}%\n"
        f"  DB {health.get('database', 'N/A')} | Celery {health.get('celery', 'N/A')}\n"
        f"  Orchestrator {health.get('orchestrator', 'N/A')} | Broker {health.get('broker', 'N/A')}\n"
        f"\n"
        f"Market\n"
        f"  Status: {market_hours}\n"
        f"  {multi_symbol_block}\n"
        f"  News:{news_halt_flag or ' clear'} | Next: {next_news_text}\n"
        f"\n"
        f"{digest}\n"
        f"\n"
        f"{_links_block()}"
    )


def _pending_approvals_text() -> str:
    """Fetch /pending_trades from the local API and format for Telegram."""
    try:
        r = requests.get(f"{_api_base()}/pending_trades", timeout=5)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        return f"Error fetching pending trades: {exc}"
    pending = data.get("pending", [])
    if not pending:
        return "No pending trade approvals."
    now = time.time()
    lines = [f"Pending Approvals ({len(pending)})"]
    for rec in pending:
        tid = rec.get("trade_id", "?")
        try:
            raw_ts = rec.get("requested_at", now)
            if isinstance(raw_ts, str):
                from datetime import datetime as _dt
                req_ts = _dt.fromisoformat(raw_ts.replace("Z", "+00:00")).timestamp()
            else:
                req_ts = float(raw_ts or now)
        except Exception:
            req_ts = float(now)
        age = int(now - req_ts)
        ttl = max(0, 300 - age)
        entry = rec.get('entry')
        sl = rec.get('sl')
        tp = rec.get('tp')
        price_info = f"E {entry} SL {sl} TP {tp}" if entry else "price N/A"
        raw_conf = rec.get('confidence', 0)
        try:
            conf_f = float(raw_conf or 0)
            conf_str = f"{conf_f * 100:.0f}%" if conf_f <= 1 else f"{conf_f:.0f}%"
        except Exception:
            conf_str = str(raw_conf)
        lines.append(
            f"\n{rec.get('symbol')} {rec.get('direction')} | {rec.get('model')}\n"
            f"  Conf {conf_str} | RR {rec.get('rr')} | {price_info}\n"
            f"  Expires in {ttl}s\n"
            f"  /approve {tid}   /reject {tid}"
        )
    return "\n".join(lines)


def _submit_approval(trade_id: str, approved: bool) -> str:
    """Call the backend to approve or reject a pending trade."""
    trade_id = trade_id.strip()
    if not trade_id:
        return "Usage: /approve <trade_id> or /reject <trade_id>"
    action = "approve" if approved else "reject"
    try:
        r = requests.post(
            f"{_api_base()}/trade/{action}/{trade_id}",
            timeout=8,
        )
        if r.status_code == 404:
            return f"Trade {trade_id} not found or already expired."
        r.raise_for_status()
        result = r.json()
        if result.get("ok"):
            verb = "APPROVED - engine will execute on next cycle" if approved else "REJECTED - signal discarded"
            # Include trade details from result so user can verify they acted on the right trade.
            sym = result.get("symbol") or result.get("trade", {}).get("symbol", "")
            direction = result.get("direction") or result.get("trade", {}).get("direction", "")
            detail = f" ({sym} {direction})" if sym else ""
            return f"Trade {trade_id}{detail}: {verb}."
        return f"Trade {trade_id} already decided: {result.get('status')}"
    except Exception as exc:
        return f"Error: {exc}"


def _command_help() -> str:
    return (
        "AstroQuant bot commands:\n"
        "/status - system health summary\n"
        "/daemon - daemon singleton health\n"
        "/signals - current signal snapshot\n"
        "/signals_all - multi-symbol signal analysis\n"
        "/astro - astro update snapshot\n"
        "/news - news halt and upcoming events\n"
        "/matrix [symbol] - MCL multi-timeframe confluence grid\n"
        "/orderflow [symbol] [timeframe] - delta, imbalance, iceberg count\n"
        "/iceberg [symbol] [timeframe] - current iceberg/absorption levels\n"
        "/absorption - AI model absorption and learning state\n"
        "/phase [symbol] [timeframe] - intraday AI phase forecast (default 15m)\n"
        "/report - report (mode from TELEGRAM_REPORT_MODE)\n"
        "/report_short - compact report\n"
        "/report_full - full report\n"
        "/pnl - trade journal digest\n"
        "/daily - run daily summary now\n"
        "/links - app + desktop links\n"
        "/pending - list pending trade approvals\n"
        "/approve <id> - approve a pending trade\n"
        "/reject <id> - reject a pending trade\n"
        "/brain - AI learning engine health\n"
        "/mcl - MCL prediction briefing (present + AI phase + future + Gann Q&A)\n"
        "/help - this help"
    )


def _daemon_health_text() -> str:
    pid = os.getpid()
    pidfile = PID_FILE.read_text(encoding="utf-8").strip() if PID_FILE.exists() else "missing"
    proc_count = 1
    backend_ok = "NO"
    broker_ok = "NO"
    cdp_ok = "NO"
    phase = "N/A"
    balance = "N/A"
    daily_pnl = "N/A"
    app_url = (DATA_DIR / "tunnel_url.txt").read_text(encoding="utf-8", errors="ignore").strip() if (DATA_DIR / "tunnel_url.txt").exists() else "PENDING"
    novnc_url = (DATA_DIR / "novnc_tunnel_url.txt").read_text(encoding="utf-8", errors="ignore").strip() if (DATA_DIR / "novnc_tunnel_url.txt").exists() else "PENDING"

    try:
        status = _get_json("/status")
        if status:
            backend_ok = "YES"
            broker_ok = "YES" if bool(status.get("connected_broker", False)) else "NO"
            phase = str(status.get("phase", "N/A"))
            bal = status.get("balance")
            balance = f"${float(bal):.2f}" if bal is not None else "N/A"
            dpnl = status.get("daily_loss")
            daily_pnl = f"{'-' if (dpnl or 0) > 0 else '+'}{abs(float(dpnl or 0)):.2f}" if dpnl is not None else "N/A"
    except Exception:
        backend_ok = "NO"

    try:
        r = requests.get("http://127.0.0.1:9222/json/version", timeout=5)
        cdp_ok = "YES" if r.status_code == 200 else "NO"
    except Exception:
        cdp_ok = "NO"

    try:
        r = subprocess.run(
            ["pgrep", "-af", f"{WORKSPACE}/telegram_bot_daemon.py"],
            capture_output=True,
            text=True,
            check=False,
        )
        lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
        proc_count = len(lines)
    except Exception:
        proc_count = 1
    singleton = "OK" if proc_count == 1 and pidfile == str(pid) else "DUPLICATE"
    return (
        f"Daemon [{_fmt_ist()}]\n"
        f"Singleton : {singleton} (PID {pid}, {proc_count} proc)\n"
        f"Backend   : {backend_ok} | Broker: {broker_ok} | Chrome: {cdp_ok}\n"
        f"Phase     : {phase} | Balance: {balance} | Daily PnL: {daily_pnl}\n"
        f"App       : {app_url}\n"
        f"Desktop   : {novnc_url}"
    )


# ── MCL DAILY PREDICTION BRIEFING ─────────────────────────────────────────

def _mcl_daily_enabled() -> bool:
    return os.getenv("TELEGRAM_MCL_DAILY_ENABLED", "true").strip().lower() == "true"


def _mcl_daily_utc() -> tuple[int, int]:
    raw = os.getenv("TELEGRAM_MCL_DAILY_UTC", "03:45").strip()
    try:
        h, m = raw.split(":", 1)
        return max(0, min(23, int(h))), max(0, min(59, int(m)))
    except Exception:
        return 3, 45


def _fetch_mcl_summary(symbol: str, timeframe: str = "1d", timeout: int = 100) -> dict:
    try:
        r = requests.get(
            f"{_api_base()}/market_causality/summary",
            params={"symbol": symbol, "timeframe": timeframe},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json() if r.text else {}
    except Exception as exc:
        _log(f"mcl_summary error ({symbol}/{timeframe}): {exc}")
        return {}


def _fetch_mcl_matrix(symbol: str, timeout: int = 120) -> dict:
    try:
        r = requests.get(
            f"{_api_base()}/market_causality/timeframe_matrix",
            params={"symbol": symbol},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json() if r.text else {}
    except Exception as exc:
        _log(f"mcl_matrix error ({symbol}): {exc}")
        return {}


def _fetch_mcl_gann_qa(symbol: str, date_str: str, limit: int = 20) -> dict:
    try:
        r = requests.get(
            f"{_api_base()}/market_causality/gann_qa",
            params={"symbol": symbol, "date": date_str, "limit": limit},
            timeout=12,
        )
        r.raise_for_status()
        return r.json() if r.text else {}
    except Exception as exc:
        _log(f"mcl_gann_qa error ({symbol}): {exc}")
        return {}


def _fetch_orderflow_summary(symbol: str, timeframe: str = "1m") -> dict:
    try:
        r = requests.get(
            f"{_api_base()}/market/orderflow_summary",
            params={"symbol": symbol, "timeframe": timeframe},
            timeout=12,
        )
        r.raise_for_status()
        return r.json() if r.text else {}
    except Exception as exc:
        _log(f"orderflow_summary error ({symbol}/{timeframe}): {exc}")
        return {}


def _fetch_chart_data(symbol: str, timeframe: str = "1m", limit: int = 80) -> dict:
    chart_timeframe = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "4h": "240",
        "1d": "1d",
    }.get(timeframe, timeframe)
    try:
        r = requests.get(
            f"{_api_base()}/chart/data",
            params={"symbol": symbol, "timeframe": chart_timeframe, "limit": limit},
            timeout=20,
        )
        r.raise_for_status()
        return r.json() if r.text else {}
    except Exception as exc:
        _log(f"chart_data error ({symbol}/{timeframe}): {exc}")
        return {}


def _fetch_ai_absorption() -> dict:
    try:
        r = requests.get(
            f"{_api_base()}/market_causality/chart/ai-absorption",
            timeout=12,
        )
        r.raise_for_status()
        return r.json() if r.text else {}
    except Exception as exc:
        _log(f"ai_absorption error: {exc}")
        return {}


def _parse_symbol_timeframe_args(raw: str, default_timeframe: str = "1m") -> tuple[str, str]:
    parts = [part for part in raw.split() if part]
    symbol = _signal_symbol()
    timeframe = default_timeframe
    valid_timeframes = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}

    if len(parts) >= 2:
        candidate = _display_symbol(parts[1].strip())
        if candidate.lower() in valid_timeframes:
            timeframe = candidate.lower()
        else:
            symbol = candidate

    if len(parts) >= 3:
        candidate_tf = parts[2].strip().lower()
        if candidate_tf in valid_timeframes:
            timeframe = candidate_tf

    return symbol, timeframe


def _handle_orderflow_command(raw: str) -> str:
    symbol, timeframe = _parse_symbol_timeframe_args(raw, default_timeframe="1m")
    payload = _fetch_orderflow_summary(symbol, timeframe=timeframe)
    summary = payload.get("summary") or {}
    if not summary:
        return f"Orderflow unavailable for {symbol} {timeframe}."

    return (
        f"Orderflow: {symbol} [{_fmt_ist()}]\n"
        f"Timeframe  : {timeframe}\n"
        f"Mode       : {summary.get('market_data_mode', 'N/A')}\n"
        f"Regime     : {summary.get('regime_mode', 'N/A')} | Alert: {summary.get('alert_level', 'N/A')}\n"
        f"Delta      : {float(summary.get('delta') or 0.0):.2f} | Imbalance: {summary.get('imbalance', 'N/A')}\n"
        f"Aggression : buy {float(summary.get('buy_aggression') or 0.0):.0f} | sell {float(summary.get('sell_aggression') or 0.0):.0f}\n"
        f"Icebergs   : {int(summary.get('iceberg_count') or 0)} | Absorption: {summary.get('absorption', 'N/A')}\n"
        f"Confidence : {float(summary.get('confidence') or 0.0):.1f}%\n"
        f"Narrative  : {summary.get('narrative', 'N/A')}"
    )


def _handle_iceberg_command(raw: str) -> str:
    symbol, timeframe = _parse_symbol_timeframe_args(raw, default_timeframe="1m")
    payload = _fetch_chart_data(symbol, timeframe=timeframe, limit=80)
    overlays = payload.get("overlays") or {}
    meta = payload.get("meta") or {}
    iceberg_rows = list(overlays.get("iceberg") or [])
    absorption_levels = list(overlays.get("absorption_levels") or [])

    lines = [
        f"Iceberg: {symbol} [{_fmt_ist()}]",
        f"Timeframe : {timeframe}",
        f"Source    : {meta.get('source', 'N/A')}",
        f"Levels    : {len(iceberg_rows)} iceberg rows | {len(absorption_levels)} absorption levels",
    ]

    if iceberg_rows:
        lines += ["", "TOP LEVELS"]
        for row in iceberg_rows[:5]:
            try:
                price = float(row.get("price") or 0.0)
                strength = float(row.get("absorption_strength") or 0.0)
                lines.append(f"  {price:.3f}  strength={strength:.2f}")
            except Exception:
                continue
    elif absorption_levels:
        lines += ["", "ABSORPTION LEVELS"]
        for price in absorption_levels[:5]:
            try:
                lines.append(f"  {float(price):.3f}")
            except Exception:
                continue
    else:
        lines += ["", "No active iceberg/absorption levels reported."]

    return "\n".join(lines)


def _handle_absorption_command() -> str:
    payload = _fetch_ai_absorption()
    if not payload:
        return "AI absorption unavailable - backend not responding."
    if str(payload.get("status") or "").lower() != "ok":
        return f"AI absorption error: {payload.get('error', 'unknown error')}"

    total_predictions = int(payload.get("total_predictions") or 0)
    total_outcomes = int(payload.get("total_outcomes") or 0)
    calibration = payload.get("calibration_score")
    model_weights = dict(payload.get("model_weights") or {})
    model_win_rates = dict(payload.get("model_win_rates") or {})
    top_model = str(payload.get("top_model") or "N/A")
    learning_state = str(payload.get("learning_state") or "N/A")
    cycle_alignment = str(payload.get("cycle_alignment") or "N/A")

    scored_models = []
    for model, win_rate in model_win_rates.items():
        if win_rate is None:
            continue
        try:
            scored_models.append((model, float(win_rate), float(model_weights.get(model, 0.0) or 0.0)))
        except Exception:
            continue
    scored_models.sort(key=lambda item: (-item[1], -item[2], item[0]))

    lines = [
        f"AI Absorption [{_fmt_ist()}]",
        f"State       : {learning_state}",
        f"Top model   : {top_model}",
        f"Cycle align : {cycle_alignment}",
        f"Predictions : {total_predictions} | Outcomes: {total_outcomes}",
        f"Calibration : {round(float(calibration) * 100, 1)}%" if calibration is not None else "Calibration : N/A",
    ]

    if scored_models:
        lines += ["", "MODEL SCOREBOARD"]
        for model, win_rate, weight in scored_models[:5]:
            lines.append(f"  {model:<10} win={win_rate * 100:.1f}%  weight={weight:.3f}")

    return "\n".join(lines)


def _handle_matrix_command(raw: str) -> str:
    parts = [part for part in raw.split() if part]
    symbol = _signal_symbol()
    if len(parts) >= 2:
        symbol = _display_symbol(parts[1].strip())

    payload = _fetch_mcl_matrix(symbol, timeout=90)
    rows = list(payload.get("rows") or [])
    if not rows:
        return f"Matrix unavailable for {symbol}."

    tf_order = ("1month", "1w", "1d", "4h", "1h", "30m", "15m", "5m", "1m")
    row_map = {str(row.get("timeframe") or ""): row for row in rows if isinstance(row, dict)}
    ordered_rows = [row_map[tf] for tf in tf_order if tf in row_map]
    if not ordered_rows:
        ordered_rows = rows

    lines = [f"MCL Matrix — {symbol}", f"{_fmt_ist()}"]
    coverage = payload.get("coverage") or {}
    ok_count = coverage.get("ok_count")
    total = coverage.get("total")
    if ok_count is not None and total is not None:
        lines.append(f"Coverage : {ok_count}/{total}")

    lines += ["", "TIMEFRAME CONFLUENCE"]
    for row in ordered_rows[:9]:
        timeframe = str(row.get("timeframe") or "?")
        signal = str(row.get("signal") or "N/A")
        bias = str(row.get("bias_label") or "")
        status = str(row.get("status") or "?")
        quality = str(row.get("quality") or "")
        conf = row.get("confidence")
        conf_str = f"{int(float(conf) * 100)}%" if conf is not None else "--"
        model_used = row.get("ai_model_used")
        model_tag = "MODEL" if model_used else "FALLBACK"
        lines.append(f"  {timeframe:<7} {signal:<5} {conf_str:<4} {bias} [{status}|{quality}|{model_tag}]")

    return "\n".join(lines)


def _handle_phase_command(raw: str) -> str:
    symbol, timeframe = _parse_symbol_timeframe_args(raw, default_timeframe="15m")

    summary = _fetch_mcl_summary(symbol, timeframe=timeframe, timeout=30)
    if not summary:
        return f"Phase forecast unavailable for {symbol} {timeframe} - backend not responding."

    message = _build_mcl_ai_phase_message(symbol, summary)
    return f"{message}\n\nTimeframe : {timeframe}"


def _build_mcl_present_message(symbol: str, summary: dict) -> str:
    """Message 1 — present signal: action, confidence, gann score, trade levels."""
    signal = str(summary.get("signal") or "N/A")
    sig_upper = signal.upper()
    conf = float(summary.get("confidence") or 0.0)
    quality = str(summary.get("quality") or "N/A")
    bias_label = str(summary.get("bias_label") or "N/A")
    bias_score = float(summary.get("bias_score") or 0.0)
    gann_pct = float(summary.get("gann_questions_pct") or 0.0)
    gann_verdict = str(summary.get("gann_questions_verdict") or "N/A")
    gann_buy = float(summary.get("gann_buy_prob") or 0.0)
    gann_sell = float(summary.get("gann_sell_prob") or 0.0)
    gann_wait = float(summary.get("gann_wait_prob") or 100.0)
    rows_analyzed = summary.get("rows_analyzed") or "N/A"
    status = str(summary.get("status") or "?")
    stale_tag = " [CACHED]" if status in ("stale_timeout", "timeout") else ""
    conf_pct = int(conf * 100) if conf <= 1.0 else int(conf)
    sig_dir = "BUY" if "BUY" in sig_upper else ("SELL" if "SELL" in sig_upper else "WAIT")

    tl = summary.get("trade_levels") or {}
    entry = tl.get("entry") or tl.get("entry_price")
    target = tl.get("take_profit") or tl.get("target")
    stop = tl.get("stop_loss") or tl.get("stop")
    rr = tl.get("r_ratio") or tl.get("rr")

    lines = [
        f"MCL PRESENT ANALYSIS — {symbol}{stale_tag}",
        f"{_fmt_ist()}",
        "",
        "SIGNAL",
        f"  Action     : {sig_dir} ({signal})",
        f"  Confidence : {conf_pct}%",
        f"  Quality    : {quality}",
        f"  Bias       : {bias_label}  ({bias_score:.2f})",
        f"  Data rows  : {rows_analyzed}",
        "",
        f"GANN SCORE : {gann_pct:.0f}%  [{gann_verdict}]",
        f"  Buy {gann_buy:.0f}% | Sell {gann_sell:.0f}% | Wait {gann_wait:.0f}%",
    ]

    if entry or target or stop:
        lines += ["", "TRADE LEVELS"]
        if entry:
            lines.append(f"  Entry  : {entry}")
        if target:
            lines.append(f"  Target : {target}")
        if stop:
            lines.append(f"  Stop   : {stop}")
        if rr:
            try:
                lines.append(f"  R:R    : {float(rr):.1f}:1")
            except Exception:
                lines.append(f"  R:R    : {rr}")

    # Add live reaction context so Gann/signal alerts show how market is moving now.
    reaction_text = _market_reaction_snapshot([symbol])
    lines += ["", "MARKET REACTION", reaction_text]

    return "\n".join(lines)


def _build_mcl_future_message(symbol: str, summary: dict, matrix: dict) -> str:
    """Message 2 — future outlook: projection, Gann degree, mindset, multi-TF signals."""
    obs = summary.get("observation") or {}
    # observation fields stored both nested (obs dict) and flat (summary top-level)
    projected_move = obs.get("signal_projected_move") or summary.get("observation_signal_projected_move")
    projected_pct = obs.get("signal_projected_move_pct") or summary.get("observation_signal_projected_move_pct")
    window_hours = obs.get("signal_window_hours") or summary.get("observation_signal_window_hours")
    gann_degree = obs.get("gann_degree") or summary.get("observation_gann_degree")
    proximity = obs.get("gann_angle_proximity") or summary.get("observation_gann_angle_proximity")
    mindset_bias = str(obs.get("gann_mindset_bias") or summary.get("observation_gann_mindset_bias") or "")
    mindset_narr = str(obs.get("gann_mindset_narration") or summary.get("observation_gann_mindset_narration") or "")
    sig_start_t = obs.get("signal_start_time") or summary.get("observation_signal_start_time")
    sig_end_t = obs.get("signal_end_time") or summary.get("observation_signal_end_time")

    lines = [
        f"MCL FUTURE OUTLOOK — {symbol}",
        f"{_fmt_ist()}",
    ]

    if projected_move is not None:
        try:
            pm = float(projected_move)
            sign = "+" if pm >= 0 else ""
            pct_str = f" ({sign}{float(projected_pct):.2f}%)" if projected_pct is not None else ""
            wh_str = f" | window {float(window_hours):.0f}h" if window_hours else ""
            lines += ["", "PROJECTION", f"  Move : {sign}{pm:.1f} pts{pct_str}{wh_str}"]
        except Exception:
            pass

    if sig_start_t or sig_end_t:
        lines += ["", "SIGNAL WINDOW",
                  f"  Start : {str(sig_start_t or 'N/A')[:19].replace('T', ' ')}",
                  f"  End   : {str(sig_end_t or 'N/A')[:19].replace('T', ' ')}"]

    if gann_degree is not None:
        try:
            lines += ["", "GANN ANGLE",
                      f"  Degree    : {float(gann_degree):.1f}°",
                      f"  Proximity : {proximity or 'N/A'}"]
        except Exception:
            pass

    if mindset_bias:
        lines += ["", "GANN MINDSET", f"  Bias : {mindset_bias}"]
        if mindset_narr:
            narr = (mindset_narr[:250] + "...") if len(mindset_narr) > 250 else mindset_narr
            lines.append(f"  {narr}")

    # Multi-timeframe matrix
    _TF_ORDER = ("1d", "4h", "1h", "30m", "15m", "5m", "1m")
    matrix_rows = matrix.get("rows") or []
    tf_data = {row.get("timeframe"): row for row in matrix_rows if isinstance(row, dict)}
    show_tfs = [tf for tf in _TF_ORDER if tf in tf_data]
    if show_tfs:
        lines += ["", "MULTI-TIMEFRAME CONFLUENCE"]
        for tf in show_tfs:
            row = tf_data[tf]
            sig = str(row.get("signal") or "N/A")
            bias = str(row.get("bias_label") or "")
            conf = row.get("confidence")
            conf_str = f"{int(float(conf) * 100)}%" if conf is not None else ""
            stat = str(row.get("status") or "?")
            flag = f" [{stat}]" if stat not in ("ok", "stale_timeout") else ""
            sig_dir = ("BUY " if "BUY" in sig.upper() else ("SELL" if "SELL" in sig.upper() else "WAIT"))
            lines.append(f"  {tf:<6} {sig_dir:<5} {conf_str:<5} {bias}{flag}")

    return "\n".join(lines)


def _build_mcl_ai_phase_message(symbol: str, summary: dict) -> str:
    """Dedicated AI phase + market movement forecast using the normalized summary block."""
    forecast = summary.get("ai_phase_forecast") or {}
    drivers = forecast.get("gann_astro_drivers") or {}

    current_phase = str(forecast.get("current_phase") or summary.get("phase") or "UNKNOWN")
    phase_projection = str(forecast.get("phase_projection") or current_phase)
    movement_direction = str(forecast.get("market_movement_direction") or "WAIT")
    movement_label = str(forecast.get("market_movement_label") or "SIDEWAYS_OR_UNCLEAR")
    confidence_pct = float(forecast.get("confidence_pct") or 0.0)
    ai_buy = float(forecast.get("ai_buy_prob") or 0.0)
    ai_sell = float(forecast.get("ai_sell_prob") or 0.0)
    future_direction = str(forecast.get("future_direction") or "WAIT")
    signal_direction = str(forecast.get("signal_direction") or summary.get("signal") or "WAIT")
    compression_bias = str(forecast.get("compression_bias") or "")
    bias_label = str(forecast.get("bias_label") or summary.get("bias_label") or "NEUTRAL_BIAS")
    model_version = str(forecast.get("ai_model_version") or summary.get("ai_model_version") or "unknown")
    model_used = bool(forecast.get("ai_model_used"))

    lines = [
        f"MCL AI PHASE FORECAST — {symbol}",
        f"{_fmt_ist()}",
        "",
        "PHASE FORECAST",
        f"  Current phase   : {current_phase}",
        f"  Projected phase : {phase_projection}",
        f"  Movement        : {movement_direction} [{movement_label}]",
        f"  Confidence      : {confidence_pct:.1f}%",
        f"  AI probs        : Buy {ai_buy:.1f}% | Sell {ai_sell:.1f}%",
        f"  Consensus       : signal={signal_direction} | future={future_direction} | bias={bias_label}",
    ]

    if compression_bias:
        lines.append(f"  Compression bias: {compression_bias}")

    lines += [
        "",
        "GANN + ASTRO DRIVERS",
        f"  Moon phase  : {drivers.get('moon_phase') or '--'}",
        f"  Nakshatra   : {drivers.get('nakshatra') or '--'}",
        f"  Astro event : {drivers.get('nearby_event') or '--'}",
        f"  Impact      : {drivers.get('nearby_event_impact') or '--'}",
        f"  Gann degree : {drivers.get('gann_degree') if drivers.get('gann_degree') is not None else '--'}",
        f"  Angle prox  : {drivers.get('gann_angle_proximity') or '--'}",
        f"  Cycle event : {drivers.get('future_cycle_event') or '--'}",
        f"  Timing      : {drivers.get('timing_window') or '--'}",
        "",
        f"MODEL : {'ACTIVE' if model_used else 'FALLBACK'} | {model_version}",
    ]

    return "\n".join(lines)


def _build_mcl_gann_qa_message(symbol: str, gann_qa: dict) -> str:
    """Message 3 — Gann 52-question session: daily scored observation Q&A."""
    rows = gann_qa.get("rows") or []
    date_label = str(gann_qa.get("selected_date") or datetime.now(_IST).strftime("%Y-%m-%d"))

    lines = [
        f"MCL GANN Q&A SESSION — {symbol}",
        f"Date  : {date_label}",
        f"Items : {len(rows)} observation(s)",
        "",
    ]

    for i, row in enumerate(rows[:12]):
        q = str(row.get("question") or "")
        ans = str(row.get("answer") or "")
        period_tag = ""
        for prefix, label in (("PAST:", "PAST"), ("ACTIVE:", "NOW "), ("FUTURE:", "FUT ")):
            if ans.upper().startswith(prefix):
                period_tag = f"[{label}]"
                ans = ans[len(prefix):].strip()
                break
        q_short = (q[:65] + "...") if len(q) > 65 else q
        a_short = (ans[:160] + "...") if len(ans) > 160 else ans
        lines.append(f"{i + 1:>2}. {q_short}")
        lines.append(f"    {period_tag} {a_short}")
        lines.append("")

    if len(rows) > 12:
        lines.append(f"    ... +{len(rows) - 12} more | send /mcl for full refresh")

    return "\n".join(lines).rstrip()


def _send_mcl_messages(symbol: str) -> None:
    """Fetch all MCL data and send the MCL prediction briefing."""
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        _log(f"MCL briefing: fetching summary for {symbol}")
        summary = _fetch_mcl_summary(symbol, timeframe="1d", timeout=100)
        if not summary:
            _send_message(f"MCL [{_fmt_ist()}]\nFailed to fetch summary for {symbol}.")
            return
        matrix = _fetch_mcl_matrix(symbol, timeout=120)
        gann_qa = _fetch_mcl_gann_qa(symbol, today_utc)

        _send_message(_build_mcl_present_message(symbol, summary))
        time.sleep(0.8)
        _send_message(_build_mcl_ai_phase_message(symbol, summary))
        time.sleep(0.8)
        _send_message(_build_mcl_future_message(symbol, summary, matrix))
        time.sleep(0.8)
        _send_message(_build_mcl_gann_qa_message(symbol, gann_qa))
        _log(f"MCL briefing sent for {symbol}")
    except Exception as exc:
        _log(f"MCL send error: {exc}")
        _send_message(f"MCL error [{_fmt_ist()}]: {exc}")


def _mcl_daily_session(state: Dict[str, Any]) -> Dict[str, Any]:
    """Fire the daily MCL 3-message prediction briefing at TELEGRAM_MCL_DAILY_UTC."""
    if not _mcl_daily_enabled():
        return state

    now = datetime.now(timezone.utc)
    target_h, target_m = _mcl_daily_utc()
    today = now.strftime("%Y-%m-%d")

    if now.hour != target_h or now.minute < target_m:
        return state
    if str(state.get("last_mcl_daily_date", "")) == today:
        return state

    # Persist immediately so a restart within the same minute won't double-fire.
    state["last_mcl_daily_date"] = today
    _save_state(state)

    import threading
    _log(f"MCL daily session triggered for {_signal_symbol()}")
    threading.Thread(target=_send_mcl_messages, args=(_signal_symbol(),), daemon=True).start()
    return state


def _handle_command(text: str) -> Optional[str]:
    # Preserve original case for arguments (trade IDs are case-sensitive).
    raw = (text or "").strip()
    text = raw.lower()
    if text.startswith("/help"):
        return _command_help()
    if text.startswith("/daemon"):
        return _daemon_health_text()
    if text.startswith("/links"):
        return _links_block()
    if text.startswith("/status"):
        status = _get_json("/status")
        health = status.get("system_health", {}) if isinstance(status, dict) else {}
        phase = str(status.get("phase", "N/A")) if isinstance(status, dict) else "N/A"
        bal = status.get("balance") if isinstance(status, dict) else None
        balance = f"${float(bal):.2f}" if bal is not None else "N/A"
        dpnl = status.get("daily_loss") if isinstance(status, dict) else None
        daily = f"{'-' if (dpnl or 0) > 0 else '+'}{abs(float(dpnl or 0)):.2f}" if dpnl is not None else "N/A"
        halt = status.get("news_halt", False) if isinstance(status, dict) else False
        return (
            f"Status [{_fmt_ist()}]\n"
            f"Phase   : {phase} | Balance: {balance} | Daily PnL: {daily}\n"
            f"CPU     : {health.get('cpu_percent', '?')}% | MEM: {health.get('memory_percent', '?')}%\n"
            f"Celery  : {health.get('celery', 'N/A')} | Broker: {health.get('broker', 'N/A')}\n"
            f"News    : {'HALTED' if halt else 'clear'}"
        )
    if text.startswith("/signals"):
        if text.startswith("/signals_all"):
            return _multi_symbol_signals_text()
        symbol = _signal_symbol()
        mentor = _get_json("/ai/mentor", params={"symbol": symbol})
        sig = _extract_signal_context(mentor)
        news_flag = " [HALTED]" if str(sig.get('news_state', '')).upper() == 'HALT' else ""
        astro = sig.get('astro', {})
        astro_line = f"Astro   : {astro.get('astro_marker', 'N/A')} ({astro.get('astro_bias', 'N/A')})" if astro else ""
        return (
            f"Signal: {symbol} [{_fmt_ist()}]\n"
            f"Action  : {sig['signal']}\n"
            f"HTF bias: {sig['htf_bias']} | LTF: {sig['ltf_structure']}\n"
            f"Vol     : {sig['volatility']} | News: {sig['news_state']}{news_flag}\n"
            + (astro_line if astro_line else "")
        ).rstrip()
    if text.startswith("/astro"):
        symbol = _signal_symbol()
        mentor = _get_json("/ai/mentor", params={"symbol": symbol})
        sig = _extract_signal_context(mentor)
        astro = sig.get("astro", {}) if isinstance(sig.get("astro", {}), dict) else {}
        window_raw = astro.get('harmonic_window', False)
        window_active = bool(window_raw) and str(window_raw).upper() not in ('FALSE', 'NONE', 'N/A', '')
        window_str = "ACTIVE" if window_active else "inactive"
        return (
            f"Astrology: {symbol} [{_fmt_ist()}]\n"
            f"Window : {window_str}\n"
            f"Marker : {astro.get('astro_marker', 'N/A')}\n"
            f"Bias   : {astro.get('astro_bias', '--')}\n"
            f"Signal : {astro.get('signal', 'N/A')}\n"
            f"Reason : {astro.get('reason', 'N/A')}"
        )
    if text.startswith("/market"):
        try:
            from astroquant.engine.market_calendar import MarketCalendar
            symbols = ["XAUUSD", "NQ", "US30", "EURUSD"]
            lines = [f"Market Hours [{_fmt_ist()}]"]
            for sym in symbols:
                info = MarketCalendar.get_session_info(sym)
                status_icon = "OPEN" if info["is_open"] else "CLOSED"
                extra = ""
                if info.get("is_early_close") and info.get("holiday_name"):
                    extra = f" (early close — {info['holiday_name']})"
                elif not info["is_open"] and info.get("next_open_label"):
                    extra = f" — opens {info['next_open_label']}"
                lines.append(f"  {sym}: {status_icon}{extra}")
            # Upcoming events for main symbol
            events = MarketCalendar.get_upcoming_holidays("XAUUSD", days=90)
            if events:
                lines.append("\nUpcoming (XAUUSD):")
                for ev in events[:5]:
                    tag = "Holiday" if ev["type"] == "holiday" else "Early Close"
                    name = ev["name"].replace(" (Early Close)", "")
                    lines.append(f"  {ev['date']}  {name} [{tag}]")
            return "\n".join(lines)
        except Exception as exc:
            return f"Market hours error: {exc}"
    if text.startswith("/news"):
        status = _get_json("/status")
        news_halt = status.get("news_halt", False)
        next_news = status.get("next_news", [])
        halt_line = "HALTED - trading suspended" if news_halt else "clear"
        if isinstance(next_news, list) and next_news:
            news_lines = []
            for item in next_news[:5]:
                if isinstance(item, dict):
                    mins = item.get('minutes_to_event')
                    timing = f"T-{int(mins)}min" if mins is not None else item.get('time_utc', '')
                    impact = item.get('impact', '?')
                    forecast = item.get('forecast', '')
                    previous = item.get('previous', '')
                    actual = item.get('actual', '')
                    detail = ''
                    if actual:
                        detail = f" | Actual: {actual}"
                    elif forecast:
                        detail = f" | Fcst: {forecast}" + (f" Prev: {previous}" if previous else "")
                    news_lines.append(f"  [{impact}] {item.get('currency','?')} — {item.get('title','?')} ({timing}){detail}")
                else:
                    news_lines.append(f"  {item}")
            next_news_text = "\n".join(news_lines)
        else:
            next_news_text = "  None scheduled"
        reaction_text = _market_reaction_snapshot(list(_signal_symbols()))
        return (
            f"News [{_fmt_ist()}]\n"
            f"Halt  : {halt_line}\n"
            f"Upcoming:\n{next_news_text}\n"
            f"Market Reaction:\n{reaction_text}"
        )
    if text.startswith("/matrix"):
        return _handle_matrix_command(raw)
    if text.startswith("/orderflow"):
        return _handle_orderflow_command(raw)
    if text.startswith("/iceberg"):
        return _handle_iceberg_command(raw)
    if text.startswith("/absorption"):
        return _handle_absorption_command()
    if text.startswith("/phase"):
        return _handle_phase_command(raw)
    if text.startswith("/brain"):
        cal = _get_json("/market_causality/status")
        if not cal:
            return "Brain status unavailable — backend not responding."
        # Trigger auto-resolve for any expired pending predictions
        try:
            _ar = requests.post(
                f"{_api_base()}/market_causality/auto_resolve_pending",
                params={"symbol": _signal_symbol()},
                timeout=15,
            )
            auto = _ar.json() if _ar.ok and _ar.text else {}
        except Exception:
            auto = {}
        newly_resolved = int((auto or {}).get("resolved_count", 0))
        weights = _get_json("/market_causality/weights")
        wt = (weights or {}).get("weights", {})
        total_preds = int(cal.get("total_predictions") or 0)
        total_outs = int(cal.get("total_outcomes") or 0)
        pending_count = max(0, total_preds - total_outs)
        lines = [
            f"AI Brain [{_fmt_ist()}]",
            f"Confidence : {cal.get('model_confidence', 'N/A')}",
            f"Accuracy   : {round(float(cal.get('overall_accuracy') or 0) * 100, 1)}%",
            f"Predictions: {total_preds}  Resolved: {total_outs}  Pending: {pending_count}",
            f"Top signal : {cal.get('top_signal', 'N/A')}  Weak: {cal.get('weakest_signal', 'N/A')}",
        ]
        if wt:
            wt_line = "  ".join(f"{k[:3]}={round(v, 2)}" for k, v in sorted(wt.items(), key=lambda x: -x[1]))
            lines.append(f"Weights    : {wt_line}")
        if newly_resolved > 0:
            lines.append(f"Auto-resolved {newly_resolved} expired prediction(s) just now.")
        return "\n".join(lines)
    if text.startswith("/mcl"):
        symbol = _signal_symbol()
        import threading
        threading.Thread(target=_send_mcl_messages, args=(symbol,), daemon=True).start()
        return f"MCL briefing generating for {symbol}. 3 messages incoming (~80s for first message)..."
    if text.startswith("/report_short"):
        return _build_status_report(mode="short")
    if text.startswith("/report_full"):
        return _build_status_report(mode="full")
    if text.startswith("/pnl"):
        return _trade_digest_text()
    if text.startswith("/daily"):
        return _build_status_report(mode="full")
    if text.startswith("/report"):
        return _build_status_report(mode=_report_mode())
    if text.startswith("/pending"):
        return _pending_approvals_text()
    if text.startswith("/approve ") or text.startswith("/approve_"):
        trade_id = raw.split(None, 1)[1].strip() if " " in raw else raw[9:].strip()
        return _submit_approval(trade_id, approved=True)
    if text.startswith("/reject ") or text.startswith("/reject_"):
        trade_id = raw.split(None, 1)[1].strip() if " " in raw else raw[8:].strip()
        return _submit_approval(trade_id, approved=False)
    return None


def _answer_callback_query(callback_query_id: str) -> None:
    """Acknowledge a Telegram inline keyboard callback so the spinner goes away."""
    token = _command_token()
    if not token:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id},
            timeout=5,
        )
    except Exception:
        pass


def _poll_updates(state: Dict[str, Any]) -> Dict[str, Any]:
    token = _command_token()
    chat_id = _command_chat_id()
    if not token or not chat_id:
        return state

    backoff_until = int(state.get("poll_backoff_until", 0) or 0)
    if backoff_until and int(time.time()) < backoff_until:
        return state

    offset = int(state.get("last_update_id", 0)) + 1
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        r = requests.get(url, params={"timeout": 5, "offset": offset}, timeout=12)
        if r.status_code == 409:
            _throttled_error(
                "telegram:getUpdates:409",
                "getUpdates conflict (409): another poller/webhook is active for this bot token. Backing off 30s.",
                every_sec=60,
            )
            _prepare_polling()
            state["poll_backoff_until"] = int(time.time()) + 30
            return state
        r.raise_for_status()
        payload = r.json()
    except Exception as exc:
        _log(f"getUpdates failed: {exc}")
        return state

    if not payload.get("ok"):
        _log(f"getUpdates not ok: {payload}")
        return state

    for upd in payload.get("result", []):
        update_id = upd.get("update_id", state.get("last_update_id", 0))
        state["last_update_id"] = max(int(state.get("last_update_id", 0)), int(update_id))

        # --- Handle regular text messages ---
        msg = upd.get("message", {})
        msg_chat = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "")
        if msg_chat == str(chat_id) and text:
            reply = _handle_command(text)
            if reply:
                _send_command(reply)

        # --- Handle inline keyboard callback_query (e.g. approve/reject buttons) ---
        cbq = upd.get("callback_query", {})
        if cbq:
            cbq_chat = str(cbq.get("message", {}).get("chat", {}).get("id", ""))
            cbq_data = str(cbq.get("data", ""))
            cbq_id = str(cbq.get("id", ""))
            _answer_callback_query(cbq_id)
            if cbq_chat == str(chat_id) and cbq_data:
                reply = _handle_command(cbq_data)
                if reply:
                    _send_command(reply)

    return state


def _event_alerts(state: Dict[str, Any]) -> Dict[str, Any]:
    # Throttle: only do a full mentor poll every 30s; still update news/status every cycle.
    now_ts = int(time.time())
    last_mentor_ts = int(state.get("last_mentor_poll_ts", 0) or 0)
    do_mentor_poll = (now_ts - last_mentor_ts) >= 30

    status = _get_json("/status")
    news_halt = status.get("news_halt", None)
    next_news = status.get("next_news", [])
    # Build a stable signature so countdown fields (e.g. minutes_to_event)
    # do not trigger repeated "news update" messages every poll cycle.
    if isinstance(next_news, list):
        normalized_news = []
        for item in next_news[:3]:
            if isinstance(item, dict):
                normalized_news.append(
                    {
                        "title": item.get("title"),
                        "time_utc": item.get("time_utc"),
                        "impact": item.get("impact"),
                        "currency": item.get("currency"),
                    }
                )
            else:
                normalized_news.append(item)
        news_sig = json.dumps(normalized_news, ensure_ascii=True, sort_keys=True)
    else:
        news_sig = json.dumps(next_news, ensure_ascii=True, sort_keys=True)

    if do_mentor_poll:
        for symbol in _signal_symbols():
            mentor = _get_json("/ai/mentor", params={"symbol": symbol})
            sig = _extract_signal_context(mentor)
            bias = sig.get("htf_bias")
            signal = sig.get("signal", "N/A")
            astro = sig.get("astro", {}) if isinstance(sig.get("astro", {}), dict) else {}
            astro_sig = json.dumps(
                {
                    "harmonic_window": astro.get("harmonic_window"),
                    "astro_marker": astro.get("astro_marker"),
                    "astro_bias": astro.get("astro_bias"),
                    "signal": astro.get("signal"),
                    "reason": astro.get("reason"),
                },
                ensure_ascii=True,
                sort_keys=True,
            )

            last_bias_map = dict(state.get("last_bias_map", {}) or {})
            last_signal_map = dict(state.get("last_signal_map", {}) or {})
            last_astro_sig_map = dict(state.get("last_astro_sig_map", {}) or {})

            prev_bias = last_bias_map.get(symbol)
            prev_signal = last_signal_map.get(symbol)
            prev_astro_sig = last_astro_sig_map.get(symbol)

            if prev_bias not in (None, bias) or prev_signal not in (None, signal):
                # Only alert when the NEW signal is an actionable direction.
                if str(signal).upper() in _ACTIONABLE_SIGNALS:
                    reaction_text = _market_reaction_snapshot([symbol])
                    _send_message(
                        f"Signal Change: {symbol}\n"
                        f"HTF   : {prev_bias} -> {bias}\n"
                        f"Signal: {prev_signal} -> {signal}\n"
                        f"Vol   : {str(sig.get('volatility', 'N/A'))} | News: {str(sig.get('news_state', 'N/A'))}\n"
                        f"Time  : {_fmt_ist()}\n"
                        f"Market Reaction:\n{reaction_text}"
                    )

            if prev_astro_sig not in (None, "", astro_sig):
                # Only alert when the astro signal itself is actionable.
                if str(astro.get("signal", "")).upper() in _ACTIONABLE_SIGNALS:
                    _aw = astro.get('harmonic_window', False)
                    _aw_str = "ACTIVE" if bool(_aw) and str(_aw).upper() not in ('FALSE', 'NONE', 'N/A', '') else "inactive"
                    reaction_text = _market_reaction_snapshot([symbol])
                    _send_message(
                        f"Astro Update: {symbol} [{_fmt_ist()}]\n"
                        f"Window : {_aw_str}\n"
                        f"Marker : {astro.get('astro_marker', 'N/A')}\n"
                        f"Bias   : {astro.get('astro_bias', '--')}\n"
                        f"Signal : {astro.get('signal', 'N/A')}\n"
                        f"Reason : {astro.get('reason', 'N/A')}\n"
                        f"Market Reaction:\n{reaction_text}"
                    )

            last_bias_map[symbol] = bias
            last_signal_map[symbol] = signal
            last_astro_sig_map[symbol] = astro_sig
            state["last_bias_map"] = last_bias_map
            state["last_signal_map"] = last_signal_map
            state["last_astro_sig_map"] = last_astro_sig_map
        state["last_mentor_poll_ts"] = now_ts
    # Treat None (API unreachable) same as False to avoid halt toggle spam.
    news_halt_bool = bool(news_halt) if news_halt is not None else False
    last_halt_bool = bool(state.get("last_news_halt")) if state.get("last_news_halt") is not None else False

    if state.get("last_news_halt") is not None and last_halt_bool != news_halt_bool:
        halt_verb = "ACTIVATED - trading suspended" if news_halt_bool else "cleared - trading resumed"
        _send_message(
            f"News Halt {halt_verb}\n"
            f"Time: {_fmt_ist()}"
        )
    if state.get("last_news_sig") not in (None, "", news_sig):
        # Only send update when there are real HIGH/CRITICAL upcoming events.
        high_impact_items = [
            item for item in (next_news if isinstance(next_news, list) else [])
            if isinstance(item, dict) and str(item.get("impact", "")).upper() in ("HIGH", "CRITICAL")
        ]
        if high_impact_items:
            if isinstance(next_news, list) and next_news:
                upcoming_lines = []
                for item in next_news[:3]:
                    if isinstance(item, dict):
                        mins = item.get('minutes_to_event')
                        timing = f"T-{int(mins)}min" if mins is not None else item.get('time_utc', '')
                        impact = item.get('impact', '?')
                        forecast = item.get('forecast', '')
                        previous = item.get('previous', '')
                        actual = item.get('actual', '')
                        detail = ''
                        if actual:
                            detail = f" | Actual: {actual}"
                        elif forecast:
                            detail = f" | Fcst: {forecast}" + (f" Prev: {previous}" if previous else "")
                        upcoming_lines.append(
                            f"  [{impact}] {item.get('currency','?')} — {item.get('title','?')} ({timing}){detail}"
                        )
                    else:
                        upcoming_lines.append(f"  {item}")
                upcoming_text = "\n".join(upcoming_lines)
            else:
                upcoming_text = "  None"
            # Fetch live market reaction snapshot
            reaction_text = _market_reaction_snapshot(list(_signal_symbols()))
            _send_message(
                f"News Update [{_fmt_ist()}]\n"
                f"Halt     : {'YES' if news_halt_bool else 'no'}\n"
                f"Events   :\n{upcoming_text}\n"
                f"Market Reaction:\n{reaction_text}"
            )

    state["last_news_halt"] = news_halt
    state["last_news_sig"] = news_sig
    return state


def _trade_approval_alerts(state: Dict[str, Any]) -> Dict[str, Any]:
    """Poll /pending_trades for new requests and notify user via Telegram.

    Also send journal update alerts for newly completed trades.
    """
    now = int(time.time())
    last_check = int(state.get("last_trade_alert_check_ts", 0) or 0)
    if now - last_check < 30:
        return state

    # --- 1. Pending approval requests ---
    sent_ids: list = list(state.get("sent_approval_ids", []) or [])
    try:
        data = _get_json("/pending_trades")
        for rec in data.get("pending", []):
            tid = str(rec.get("trade_id", ""))
            if not tid or tid in sent_ids:
                continue
            # Only alert on genuinely new PENDING requests
            if str(rec.get("status", "")).upper() != "PENDING":
                continue
            # requested_at may be a Unix float or an ISO datetime string.
            try:
                raw_ts = rec.get("requested_at", now)
                if isinstance(raw_ts, str):
                    from datetime import datetime as _dt
                    req_ts = _dt.fromisoformat(raw_ts.replace("Z", "+00:00")).timestamp()
                else:
                    req_ts = float(raw_ts or now)
            except Exception:
                req_ts = float(now)
            age = now - req_ts
            if age > 240:  # Don't spam for near-expired entries
                continue
            ttl = max(0, 300 - int(age))
            entry_val = rec.get('entry')
            sl_val = rec.get('sl')
            tp_val = rec.get('tp')
            prices = f"  Entry {entry_val} | SL {sl_val} | TP {tp_val}" if entry_val else ""
            conf_raw = rec.get('confidence') or 0
            try:
                conf_f = float(conf_raw)
                conf_pct = f"{conf_f * 100:.0f}%" if conf_f <= 1 else f"{conf_f:.0f}%"
            except Exception:
                conf_pct = str(conf_raw)
            _send_message(
                f"TRADE REQUEST [{_fmt_ist()}]\n"
                f"Symbol : {rec.get('symbol')} {rec.get('direction')}\n"
                f"Model  : {rec.get('model')}\n"
                f"Conf   : {conf_pct} | RR: {rec.get('rr')}:1\n"
                + (prices + "\n" if prices else "")
                + f"Expires: {ttl}s\n"
                f"\n"
                f"/approve {tid}\n"
                f"/reject {tid}"
            )
            sent_ids.append(tid)
    except Exception as exc:
        _throttled_error("trade_approval_poll", f"pending_trades poll error: {exc}", every_sec=120)
    # Keep only last 200 sent ids to avoid unbounded growth
    state["sent_approval_ids"] = sent_ids[-200:]

    # --- 2. Journal completion alerts (new completed trades) ---
    for symbol in _signal_symbols():
        journal_rows = _get_json("/journal", params={"symbol": symbol, "limit": 1})
        if not isinstance(journal_rows, list) or not journal_rows:
            continue
        latest = journal_rows[0]
        if not isinstance(latest, list) or len(latest) < 5:
            continue

        ts = str(latest[0])
        row_symbol = _display_symbol(str(latest[1]))
        model = str(latest[2])
        result = str(latest[3])
        pnl = latest[4]

        # Unique key based on immutable fields — pnl + ts makes it stable
        key = f"{ts}|{row_symbol}|{model}|{result}|{pnl}"
        last_trade_key_map = dict(state.get("last_trade_key_map", {}) or {})
        prev_key = last_trade_key_map.get(symbol)
        if prev_key not in (None, "", key):
            pnl_float = float(pnl or 0)
            result_upper = str(result).upper()
            icon = "WIN" if result_upper in ("WIN", "TP") or pnl_float > 0 else ("LOSS" if result_upper in ("LOSS", "SL") or pnl_float < 0 else "CLOSED")
            pnl_sign = "+" if pnl_float >= 0 else ""
            # Convert stored UTC timestamp to IST for display
            try:
                ts_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                ts_display = ts_dt.astimezone(_IST).strftime("%d %b %I:%M %p IST")
            except Exception:
                ts_display = str(ts)
            _send_message(
                f"Trade {icon}: {row_symbol}\n"
                f"Model : {model}\n"
                f"Result: {result} | PnL: {pnl_sign}{pnl_float:.2f}\n"
                f"Time  : {ts_display}"
            )
        last_trade_key_map[symbol] = key
        state["last_trade_key_map"] = last_trade_key_map

    state["last_trade_alert_check_ts"] = now
    return state


def _acquire_pid_lock() -> bool:
    global _TOKEN_LOCK_FILE
    # Use O_EXCL for atomic singleton lock to avoid startup race duplicates.
    if not _acquire_lock_file(PID_FILE, os.getpid()):
        return False

    token_lock = _token_lock_path()
    if token_lock is not None:
        if not _acquire_lock_file(token_lock, os.getpid()):
            # Release local PID lock if token lock fails.
            try:
                PID_FILE.unlink(missing_ok=True)
            except Exception:
                pass
            return False
        _TOKEN_LOCK_FILE = token_lock

    return True


def _cleanup_pid(*_: Any) -> None:
    try:
        if PID_FILE.exists():
            pid_txt = PID_FILE.read_text(encoding="utf-8").strip()
            if pid_txt == str(os.getpid()):
                PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        if _TOKEN_LOCK_FILE and _TOKEN_LOCK_FILE.exists():
            pid_txt = _TOKEN_LOCK_FILE.read_text(encoding="utf-8").strip()
            if pid_txt == str(os.getpid()):
                _TOKEN_LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _handle_exit_signal(signum: int, _: Any) -> None:
    _cleanup_pid()
    raise SystemExit(128 + signum)


def _periodic_report(state: Dict[str, Any]) -> Dict[str, Any]:
    now = int(time.time())
    last = int(state.get("last_report_ts", 0))
    interval = _report_interval()
    if now - last >= interval:
        _send_health(_build_status_report(mode=_report_mode()))
        state["last_report_ts"] = now
    return state


def _periodic_daemon_health(state: Dict[str, Any]) -> Dict[str, Any]:
    now = int(time.time())
    last = int(state.get("last_daemon_health_ts", 0))
    interval = _daemon_health_interval()
    if now - last >= interval:
        _send_health(_daemon_health_text())
        state["last_daemon_health_ts"] = now
    return state


def _daily_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    if not _daily_summary_enabled():
        return state

    now = datetime.now(timezone.utc)
    target_h, target_m = _daily_summary_utc()
    today = now.strftime("%Y-%m-%d")
    last_day = str(state.get("last_daily_summary_date", ""))

    if now.hour == target_h and now.minute >= target_m and last_day != today:
        _send_health("Daily Summary\n" + _build_status_report(mode="full"))
        state["last_daily_summary_date"] = today
    return state


def _day_boundary_reports(state: Dict[str, Any]) -> Dict[str, Any]:
    if not _day_boundary_reports_enabled():
        return state

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    start_h, start_m = _day_start_utc()
    end_h, end_m = _day_end_utc()

    last_start_day = str(state.get("last_day_start_report_date", ""))
    last_end_day = str(state.get("last_day_end_report_date", ""))

    if now.hour == start_h and now.minute >= start_m and last_start_day != today:
        _send_health("Day Start Report\n" + _build_status_report(mode="full"))
        state["last_day_start_report_date"] = today

    if now.hour == end_h and now.minute >= end_m and last_end_day != today:
        _send_health("Day End Report\n" + _build_status_report(mode="full"))
        state["last_day_end_report_date"] = today

    return state


def _holiday_eve_alert(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check once per evening (around market close time) whether tomorrow is a
    CME holiday or early-close day.  If so, send a proactive alert to the
    health channel so the user knows in advance.

    Fires at the same time as the day-end report (TELEGRAM_DAY_END_UTC, default
    18:00 UTC = 11:30 PM IST) but only if tomorrow actually has an event.
    """
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    last_date = str(state.get("last_holiday_eve_alert_date", ""))
    if last_date == today:
        return state   # already fired today

    # Trigger window: within the same hour as the day-end report time
    end_h, end_m = _day_end_utc()
    if now.hour != end_h or now.minute < end_m:
        return state   # not yet the right time

    try:
        from astroquant.engine.market_calendar import MarketCalendar
        from datetime import date, timedelta

        tomorrow = date.today() + timedelta(days=1)
        # Check each tracked symbol for tomorrow's status
        symbols = ["XAUUSD", "NQ", "US30", "EURUSD"]
        alerts: list[str] = []
        seen: set[str] = set()

        for sym in symbols:
            info = MarketCalendar.get_session_info(sym, datetime(tomorrow.year, tomorrow.month, tomorrow.day, 12, 0, tzinfo=timezone.utc))
            if info["is_holiday"]:
                key = f"holiday:{tomorrow}"
                if key not in seen:
                    seen.add(key)
                    name = info.get("holiday_name") or "Market Holiday"
                    alerts.append(f"Tomorrow ({tomorrow.strftime('%a %b %d')}) is a FULL HOLIDAY — {name}")
                    alerts.append(f"All CME markets CLOSED: XAUUSD, NQ, US30, EURUSD")
                break
            if info["is_early_close"]:
                ec = (info.get("early_close_utc") or "")[:16].replace("T", " ")
                name = info.get("holiday_name") or "Early Close"
                # Deduplicate by close-time: group symbols that share the same close
                key = f"earlyclose:{ec}:{tomorrow}"
                if key not in seen:
                    seen.add(key)
                    alerts.append(f"Early Close ({tomorrow.strftime('%a %b %d')}) — {name}")
                    alerts.append(f"  Session ends {ec} UTC  [{sym}]")
                else:
                    # Append this symbol name to the existing close-time line
                    for i, line in enumerate(alerts):
                        if ec in line and "[" in line:
                            alerts[i] = line.rstrip("]") + f", {sym}]"
                            break

        if alerts:
            msg = (
                f"Market Alert [{_fmt_ist()}]\n"
                f"Tomorrow's Schedule:\n"
                + "\n".join(f"  {a}" for a in alerts)
            )
            _send_health(msg)

    except Exception as exc:
        _log(f"holiday_eve_alert error: {exc}")

    state["last_holiday_eve_alert_date"] = today
    return state


def main() -> int:
    _load_env(ENV_FILE)

    if not _acquire_pid_lock():
        _log("Telegram daemon already running, exiting duplicate instance")
        return 0
    atexit.register(_cleanup_pid)
    signal.signal(signal.SIGTERM, _handle_exit_signal)
    signal.signal(signal.SIGINT, _handle_exit_signal)

    if not _enabled():
        _log("Telegram daemon disabled")
        return 0

    if not _command_token() or not _command_chat_id():
        _log("Telegram daemon missing command token/chat_id")
        return 0

    _prepare_polling()
    _log("Telegram daemon started")
    state = _load_state()
    now = int(time.time())
    cooldown = _startup_online_cooldown_sec()
    last_online = int(state.get("last_online_alert_ts", 0) or 0)
    if now - last_online >= cooldown:
        # Send startup notice to both channels so the user knows the daemon is alive.
        msg = "AstroQuant daemon online. Send /help for commands."
        if _signals_chat_id() != _health_chat_id():
            _send_to(_signals_chat_id(), msg, token=_updates_token())
        if _send_health(msg):
            state["last_online_alert_ts"] = now
            _save_state(state)
    else:
        _log("startup online alert suppressed by cooldown")

    while True:
        try:
            state = _poll_updates(state)
            state = _event_alerts(state)
            state = _trade_approval_alerts(state)
            state = _periodic_report(state)
            state = _periodic_daemon_health(state)
            state = _daily_summary(state)
            state = _day_boundary_reports(state)
            state = _holiday_eve_alert(state)
            state = _mcl_daily_session(state)
            _save_state(state)
        except Exception as exc:
            _log(f"daemon loop error: {exc}")
        time.sleep(6)


if __name__ == "__main__":
    raise SystemExit(main())
