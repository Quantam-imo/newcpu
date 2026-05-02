"""
mt5_auto_export_via_ghcp.py
==========================
Run this script on your LOCAL machine where MetaTrader5 terminal is installed.
It exports XAUUSD M5 candles and pushes fresh CSV files into the Codespace drop folder
using `gh cs cp` (no public HTTP endpoint needed).

Prerequisites on local machine:
  - MetaTrader5 Python package
  - GitHub CLI installed (`gh`)
  - Authenticated: gh auth login
  - Codespaces extension available: gh extension install github/gh-codespace (if needed)

Run:
  pip install MetaTrader5
  python mt5_auto_export_via_ghcp.py
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5

CODESPACE_NAME = os.getenv("AQ_CODESPACE_NAME", "humble-goggles-q7r79pgxw79q245rq")
REMOTE_DROP_DIR = os.getenv("AQ_REMOTE_DROP_DIR", "/workspaces/newcpu/transfer_out/mt5_drop")
SYMBOL = os.getenv("AQ_SYMBOL", "XAUUSD")
BARS = int(os.getenv("AQ_BARS", "500"))
INTERVAL_SECONDS = int(os.getenv("AQ_INTERVAL_SECONDS", "60"))
TIMEFRAME = mt5.TIMEFRAME_M5


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("mt5_ghcp")


def _rates_to_csv(rates) -> str:
    lines = ["Date;Open;High;Low;Close;TickVolume;Volume;Spread"]
    for row in rates:
        dt_str = datetime.fromtimestamp(int(row[0]), tz=timezone.utc).strftime("%Y.%m.%d %H:%M:%S")
        lines.append(
            f"{dt_str};{row[1]:.5f};{row[2]:.5f};{row[3]:.5f};{row[4]:.5f};{int(row[5])};{int(row[7])};{int(row[6])}"
        )
    return "\n".join(lines) + "\n"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _check_prereqs() -> None:
    if shutil.which("gh") is None:
        raise RuntimeError("GitHub CLI not found in PATH. Install gh first.")

    auth = _run(["gh", "auth", "status"])
    if auth.returncode != 0:
        raise RuntimeError("GitHub CLI is not authenticated. Run: gh auth login")


def _ensure_remote_dir() -> None:
    cmd = ["gh", "cs", "ssh", "-c", f"mkdir -p {REMOTE_DROP_DIR}", "-c", CODESPACE_NAME]
    res = _run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to create remote drop dir: {res.stderr.strip() or res.stdout.strip()}")


def _push_csv(csv_text: str, epoch_tag: int) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="\n") as tmp:
        tmp.write(csv_text)
        local_path = Path(tmp.name)

    try:
        remote_name = f"{SYMBOL}_feed_{epoch_tag}.csv"
        remote_target = f"{CODESPACE_NAME}:{REMOTE_DROP_DIR.rstrip('/')}/{remote_name}"
        cmd = ["gh", "cs", "cp", str(local_path), remote_target]
        res = _run(cmd)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip() or res.stdout.strip() or "gh cs cp failed")
        log.info("Pushed %s to %s", local_path.name, remote_target)
    finally:
        try:
            local_path.unlink(missing_ok=True)
        except Exception:
            pass


def run() -> None:
    _check_prereqs()
    log.info("Ensuring remote drop directory exists: %s", REMOTE_DROP_DIR)
    _ensure_remote_dir()

    log.info("Initializing MT5")
    if not mt5.initialize():
        log.error("mt5.initialize() failed: %s", mt5.last_error())
        return

    last_candle_epoch = None
    log.info("Starting loop interval=%ss, bars=%s", INTERVAL_SECONDS, BARS)

    try:
        while True:
            rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, BARS)
            if rates is None or len(rates) == 0:
                log.warning("No rates returned: %s", mt5.last_error())
                time.sleep(INTERVAL_SECONDS)
                continue

            current_epoch = int(rates[-1][0])
            current_dt = datetime.fromtimestamp(current_epoch, tz=timezone.utc)
            log.info("Fetched %d bars, latest=%s UTC", len(rates), current_dt)

            if last_candle_epoch == current_epoch:
                log.info("No new candle; skipping push")
            else:
                csv_text = _rates_to_csv(rates)
                try:
                    _push_csv(csv_text, current_epoch)
                    last_candle_epoch = current_epoch
                except Exception as exc:
                    log.error("Push failed: %s", exc)

            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        log.info("Stopped by user")
    finally:
        mt5.shutdown()
        log.info("MT5 disconnected")


if __name__ == "__main__":
    run()
