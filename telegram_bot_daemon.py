#!/usr/bin/env python3
"""AstroQuant Telegram daemon.

Features:
- Chat commands: /status, /signals, /news, /report, /links, /help
- Periodic reports with system health, signals, and news context
- Event-driven alerts when key signal bias changes or news halt changes
- Daily scheduled summary and trade-journal digest

Env (.env):
- TELEGRAM_ALERT_ENABLED=true
- TELEGRAM_BOT_TOKEN=<token>
- TELEGRAM_CHAT_ID=<chat_id>
- TELEGRAM_REPORT_INTERVAL_SEC=900
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests

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
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {msg}\n")


def _api_base() -> str:
    return "http://127.0.0.1:8000"


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _chat_id() -> str:
    return os.getenv("TELEGRAM_CHAT_ID", "").strip()


def _enabled() -> bool:
    return os.getenv("TELEGRAM_ALERT_ENABLED", "false").strip().lower() == "true"


def _report_interval() -> int:
    try:
        return max(60, int(os.getenv("TELEGRAM_REPORT_INTERVAL_SEC", "900")))
    except Exception:
        return 900


def _signal_symbol() -> str:
    return os.getenv("TELEGRAM_SIGNAL_SYMBOL", "XAUUSD").strip() or "XAUUSD"


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


def _daemon_health_interval() -> int:
    try:
        return max(60, int(os.getenv("TELEGRAM_DAEMON_HEALTH_INTERVAL_SEC", "300")))
    except Exception:
        return 300


def _send_message(text: str) -> bool:
    token = _token()
    chat_id = _chat_id()
    if not token or not chat_id:
        _log("send skipped: missing TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID")
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=12)
        ok = r.status_code == 200
        if not ok:
            _log(f"send failed: HTTP {r.status_code} {r.text[:200]}")
        return ok
    except Exception as exc:
        _log(f"send exception: {exc}")
        return False


def _prepare_polling() -> None:
    token = _token()
    if not token:
        return
    try:
        # Ensure getUpdates long polling is allowed; webhook and polling cannot coexist.
        url = f"https://api.telegram.org/bot{token}/deleteWebhook"
        requests.post(url, data={"drop_pending_updates": "false"}, timeout=12)
    except Exception as exc:
        _throttled_error("telegram:deleteWebhook", f"deleteWebhook failed: {exc}", every_sec=600)


def _token_lock_path() -> Optional[Path]:
    token = _token()
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
        "last_bias": None,
        "last_news_halt": None,
        "last_news_sig": "",
        "last_daily_summary_date": "",
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
    ctx = mentor_payload.get("context", {}) if isinstance(mentor_payload, dict) else {}

    def walk(obj: Any) -> Optional[str]:
        if isinstance(obj, dict):
            for key in ("signal", "action", "recommendation", "bias"):
                if key in obj and obj[key] not in (None, ""):
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
        "signal": signal or "N/A",
        "htf_bias": ctx.get("htf_bias", "N/A"),
        "ltf_structure": ctx.get("ltf_structure", "N/A"),
        "volatility": ctx.get("volatility", "N/A"),
        "news_state": ctx.get("news_state", "N/A"),
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
        return f"Journal digest unavailable: {d.get('reason', 'unknown')}"
    return (
        f"Trade Digest\n"
        f"Total trades: {d['total']}\n"
        f"Recent sampled: {d['sampled']}\n"
        f"Wins/Losses: {d['wins']}/{d['losses']}\n"
        f"Win rate: {d['win_rate']}%\n"
        f"Recent PnL sum: {d['pnl_sum']}"
    )


def _build_status_report(mode: str = "full") -> str:
    status = _get_json("/status")
    health = status.get("system_health", {}) if isinstance(status, dict) else {}
    symbol = _signal_symbol()
    mentor = _get_json("/ai/mentor", params={"symbol": symbol})
    sig = _extract_signal_context(mentor)

    news_halt = status.get("news_halt", "N/A")
    next_news = status.get("next_news", [])
    next_news_text = ", ".join([str(x) for x in next_news[:3]]) if isinstance(next_news, list) else str(next_news)
    if not next_news_text:
        next_news_text = "None"

    if mode == "short":
        return (
            f"AstroQuant Short Report ({datetime.now(timezone.utc).strftime('%H:%M UTC')})\n"
            f"CPU/MEM: {health.get('cpu_percent', 'N/A')}% / {health.get('memory_percent', 'N/A')}%\n"
            f"Signal({symbol}): {sig['signal']} | HTF: {sig['htf_bias']}\n"
            f"News halt: {news_halt}\n"
            f"{_links_block()}"
        )

    digest = _trade_digest_text()
    return (
        f"AstroQuant Report ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})\n"
        f"CPU: {health.get('cpu_percent', 'N/A')}% | MEM: {health.get('memory_percent', 'N/A')}%\n"
        f"DB: {health.get('database', 'N/A')} | Celery: {health.get('celery', 'N/A')} | Orchestrator: {health.get('orchestrator', 'N/A')}\n"
        f"Broker: {health.get('broker', 'N/A')}\n"
        f"Signal symbol: {symbol}\n"
        f"Signal: {sig['signal']} | HTF: {sig['htf_bias']} | LTF: {sig['ltf_structure']}\n"
        f"Volatility: {sig['volatility']} | News state: {sig['news_state']}\n"
        f"News halt: {news_halt}\n"
        f"Next news: {next_news_text}\n"
        f"{digest}\n"
        f"{_links_block()}"
    )


def _command_help() -> str:
    return (
        "AstroQuant bot commands:\n"
        "/status - system health summary\n"
        "/daemon - daemon singleton health\n"
        "/signals - current signal snapshot\n"
        "/news - news halt and upcoming events\n"
        "/report - report (mode from TELEGRAM_REPORT_MODE)\n"
        "/report_short - compact report\n"
        "/report_full - full report\n"
        "/pnl - trade journal digest\n"
        "/daily - run daily summary now\n"
        "/links - app + desktop links\n"
        "/help - this help"
    )


def _daemon_health_text() -> str:
    pid = os.getpid()
    pidfile = PID_FILE.read_text(encoding="utf-8").strip() if PID_FILE.exists() else "missing"
    proc_count = 1
    backend_ok = "NO"
    broker_ok = "NO"
    cdp_ok = "NO"
    app_url = (DATA_DIR / "tunnel_url.txt").read_text(encoding="utf-8", errors="ignore").strip() if (DATA_DIR / "tunnel_url.txt").exists() else "PENDING"
    novnc_url = (DATA_DIR / "novnc_tunnel_url.txt").read_text(encoding="utf-8", errors="ignore").strip() if (DATA_DIR / "novnc_tunnel_url.txt").exists() else "PENDING"

    try:
        status = _get_json("/status")
        if status:
            backend_ok = "YES"
            broker_ok = "YES" if bool(status.get("connected_broker", False)) else "NO"
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
    singleton = "YES" if proc_count == 1 and pidfile == str(pid) else "NO"
    return (
        f"Daemon Health ({datetime.now(timezone.utc).strftime('%H:%M UTC')})\n"
        f"PID: {pid}\n"
        f"PID file: {pidfile}\n"
        f"Running daemon procs: {proc_count}\n"
        f"Singleton OK: {singleton}\n"
        f"Backend /status: {backend_ok}\n"
        f"Broker connected: {broker_ok}\n"
        f"Chrome CDP 9222: {cdp_ok}\n"
        f"App URL: {app_url}\n"
        f"Desktop URL: {novnc_url}"
    )


def _handle_command(text: str) -> Optional[str]:
    text = (text or "").strip().lower()
    if text.startswith("/help"):
        return _command_help()
    if text.startswith("/daemon"):
        return _daemon_health_text()
    if text.startswith("/links"):
        return _links_block()
    if text.startswith("/status"):
        status = _get_json("/status")
        health = status.get("system_health", {}) if isinstance(status, dict) else {}
        return (
            f"Status\nCPU: {health.get('cpu_percent', 'N/A')}%\n"
            f"MEM: {health.get('memory_percent', 'N/A')}%\n"
            f"Celery: {health.get('celery', 'N/A')}\n"
            f"Orchestrator: {health.get('orchestrator', 'N/A')}\n"
            f"Broker: {health.get('broker', 'N/A')}"
        )
    if text.startswith("/signals"):
        symbol = _signal_symbol()
        mentor = _get_json("/ai/mentor", params={"symbol": symbol})
        sig = _extract_signal_context(mentor)
        return (
            f"Signals ({symbol})\n"
            f"Signal: {sig['signal']}\n"
            f"HTF bias: {sig['htf_bias']}\n"
            f"LTF structure: {sig['ltf_structure']}\n"
            f"Volatility: {sig['volatility']}\n"
            f"News state: {sig['news_state']}"
        )
    if text.startswith("/news"):
        status = _get_json("/status")
        news_halt = status.get("news_halt", "N/A")
        next_news = status.get("next_news", [])
        next_news_text = "\n".join([f"- {x}" for x in (next_news[:5] if isinstance(next_news, list) else [str(next_news)])])
        if not next_news_text:
            next_news_text = "- None"
        return f"News\nHalt: {news_halt}\nUpcoming:\n{next_news_text}"
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
    return None


def _poll_updates(state: Dict[str, Any]) -> Dict[str, Any]:
    token = _token()
    chat_id = _chat_id()
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

        msg = upd.get("message", {})
        msg_chat = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "")

        if msg_chat != str(chat_id):
            continue

        reply = _handle_command(text)
        if reply:
            _send_message(reply)

    return state


def _event_alerts(state: Dict[str, Any]) -> Dict[str, Any]:
    status = _get_json("/status")
    news_halt = status.get("news_halt", None)
    next_news = status.get("next_news", [])
    news_sig = json.dumps(next_news[:3] if isinstance(next_news, list) else next_news, ensure_ascii=True)

    mentor = _get_json("/ai/mentor", params={"symbol": _signal_symbol()})
    sig = _extract_signal_context(mentor)
    bias = sig.get("htf_bias")

    if state.get("last_bias") not in (None, bias):
        _send_message(
            f"Signal change detected\n"
            f"Symbol: {_signal_symbol()}\n"
            f"HTF bias: {state.get('last_bias')} -> {bias}\n"
            f"Signal: {sig.get('signal', 'N/A')}"
        )
    if state.get("last_news_halt") not in (None, news_halt):
        _send_message(f"News halt changed: {state.get('last_news_halt')} -> {news_halt}")
    if state.get("last_news_sig") not in (None, "", news_sig):
        _send_message(
            "News update\n"
            f"Halt: {news_halt}\n"
            f"Upcoming: {next_news[:3] if isinstance(next_news, list) else next_news}"
        )

    state["last_bias"] = bias
    state["last_news_halt"] = news_halt
    state["last_news_sig"] = news_sig
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
        _send_message(_build_status_report(mode=_report_mode()))
        state["last_report_ts"] = now
    return state


def _periodic_daemon_health(state: Dict[str, Any]) -> Dict[str, Any]:
    now = int(time.time())
    last = int(state.get("last_daemon_health_ts", 0))
    interval = _daemon_health_interval()
    if now - last >= interval:
        _send_message(_daemon_health_text())
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
        _send_message("Daily Summary\n" + _build_status_report(mode="full"))
        state["last_daily_summary_date"] = today
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

    if not _token() or not _chat_id():
        _log("Telegram daemon missing token/chat_id")
        return 0

    _prepare_polling()
    _log("Telegram daemon started")
    _send_message("AstroQuant Telegram daemon online. Send /help for commands.")

    state = _load_state()
    while True:
        try:
            state = _poll_updates(state)
            state = _event_alerts(state)
            state = _periodic_report(state)
            state = _periodic_daemon_health(state)
            state = _daily_summary(state)
            _save_state(state)
        except Exception as exc:
            _log(f"daemon loop error: {exc}")
        time.sleep(6)


if __name__ == "__main__":
    raise SystemExit(main())
