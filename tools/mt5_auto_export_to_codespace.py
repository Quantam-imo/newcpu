"""
mt5_auto_export_to_codespace.py
================================
Run this script on your LOCAL WINDOWS machine (where MetaTrader5 is installed).
It will automatically:
  1. Connect to MT5 and pull the latest 500 XAUUSD M5 candles
  2. Format them as CSV matching the expected bridge format
  3. POST the CSV to your Codespace backend via HTTP every 60 seconds

HOW TO RUN (Windows terminal / PowerShell):
  pip install MetaTrader5 requests
  python mt5_auto_export_to_codespace.py

CONFIGURATION — change CODESPACE_URL below to your Codespace public URL.
"""

import logging
import os
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5
import requests

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION  — edit these as needed
# ─────────────────────────────────────────────────────────────────────────────
CODESPACE_URL = (
    "https://humble-goggles-q7r79pgxw79q245rq-8000.app.github.dev"
)
UPLOAD_ENDPOINT = "/market_causality/mt5_upload?symbol=XAUUSD&timeframe=5m"
UPLOAD_TOKEN = os.getenv("MCL_MT5_UPLOAD_TOKEN", "").strip()

SYMBOL = "XAUUSD"
TIMEFRAME = mt5.TIMEFRAME_M5
BARS = 500                  # number of candles to export each cycle
INTERVAL_SECONDS = 60       # push interval (seconds); MT5 updates every ~1–5 min
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("mt5_auto_export")


def _rates_to_csv(rates) -> str:
    """Convert MT5 rates array to semicolon-delimited CSV expected by the bridge."""
    lines = ["Date;Open;High;Low;Close;TickVolume;Volume;Spread"]
    for r in rates:
        # r is a named tuple: time, open, high, low, close, tick_volume, spread, real_volume
        dt_str = datetime.fromtimestamp(r[0], tz=timezone.utc).strftime("%Y.%m.%d %H:%M:%S")
        lines.append(
            f"{dt_str};{r[1]:.5f};{r[2]:.5f};{r[3]:.5f};{r[4]:.5f};{int(r[5])};{int(r[7])};{int(r[6])}"
        )
    return "\n".join(lines)


def _push_csv(csv_text: str) -> bool:
    url = CODESPACE_URL.rstrip("/") + UPLOAD_ENDPOINT
    try:
        headers = {"Content-Type": "text/csv"}
        if UPLOAD_TOKEN:
            headers["x-mt5-upload-token"] = UPLOAD_TOKEN
        resp = requests.post(
            url,
            data=csv_text.encode("utf-8"),
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 200:
            j = resp.json()
            log.info(
                "Upload OK - %d bytes, rows=%s, latest=%s",
                j.get("bytes", 0),
                j.get("rows", "?"),
                j.get("latest_date", "?"),
            )
            return True
        log.warning("Upload HTTP %s: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:
        log.error("Upload failed: %s", exc)
        return False


def run():
    log.info("Initialising MetaTrader5 …")
    if not mt5.initialize():
        log.error("mt5.initialize() failed: %s", mt5.last_error())
        return

    log.info("MT5 connected. Starting export loop every %ds …", INTERVAL_SECONDS)
    last_candle_epoch = None

    try:
        while True:
            rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, BARS)
            if rates is None or len(rates) == 0:
                log.warning("No rates returned — MT5 error: %s", mt5.last_error())
            else:
                current_last_epoch = int(rates[-1][0])
                last_dt = datetime.fromtimestamp(current_last_epoch, tz=timezone.utc)
                log.info("Pulled %d bars, latest candle: %s UTC", len(rates), last_dt)

                # Skip re-upload if no new candle has arrived since last push.
                if last_candle_epoch == current_last_epoch:
                    log.info("No new candle yet - skipping upload")
                else:
                    csv_text = _rates_to_csv(rates)
                    if _push_csv(csv_text):
                        last_candle_epoch = current_last_epoch

            time.sleep(INTERVAL_SECONDS)

    except KeyboardInterrupt:
        log.info("Stopped by user.")
    finally:
        mt5.shutdown()
        log.info("MT5 disconnected.")


if __name__ == "__main__":
    run()
