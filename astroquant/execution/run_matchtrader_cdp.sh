#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="/workspaces/newcpu/.venv/bin/python"
EXECUTOR="$ROOT_DIR/execution/matchtrader_executor.py"

MODE="calibrate"
CDP_URL="http://127.0.0.1:9222"
DURATION_MIN="30"
POLL_SEC="2"
FUTURES_PRICE="2374.10"
MANUAL_LOGIN_TIMEOUT="120"
DAILY_LOSS="0"
LIVE_FLAG=""
RECALIBRATE_FLAG=""
LAUNCH_BROWSER="false"
BROWSER_BIN=""
BROWSER_PROFILE="/tmp/maven-cdp-profile"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  --mode calibrate|step1|step2|step3   Execution mode (default: calibrate)
  --cdp-url URL                         CDP endpoint (default: http://127.0.0.1:9222)
  --duration-min N                      Step1 duration minutes (default: 30)
  --poll-sec N                          Poll interval seconds (default: 2)
  --futures-price P                     Futures reference for step2/3 (default: 2374.10)
  --manual-login-timeout N              Wait timeout seconds (default: 120)
  --daily-loss V                        Daily loss input for guards (default: 0)
  --live                                Enable live click for step3 (challenge account only)
  --recalibrate                         Force recalibration before test mode
  --launch-browser                      Try launching local browser with remote debugging
  --browser-bin PATH                    Browser binary override
  -h, --help                            Show help

Examples:
  $(basename "$0") --mode calibrate
  $(basename "$0") --mode step1 --duration-min 2 --poll-sec 2
  $(basename "$0") --mode step3 --live --futures-price 2374.10
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --cdp-url) CDP_URL="$2"; shift 2 ;;
    --duration-min) DURATION_MIN="$2"; shift 2 ;;
    --poll-sec) POLL_SEC="$2"; shift 2 ;;
    --futures-price) FUTURES_PRICE="$2"; shift 2 ;;
    --manual-login-timeout) MANUAL_LOGIN_TIMEOUT="$2"; shift 2 ;;
    --daily-loss) DAILY_LOSS="$2"; shift 2 ;;
    --live) LIVE_FLAG="--live"; shift ;;
    --recalibrate) RECALIBRATE_FLAG="--recalibrate"; shift ;;
    --launch-browser) LAUNCH_BROWSER="true"; shift ;;
    --browser-bin) BROWSER_BIN="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python not found at $PYTHON_BIN" >&2
  exit 1
fi

if [[ "$LAUNCH_BROWSER" == "true" ]]; then
  if [[ -z "$BROWSER_BIN" ]]; then
    if command -v google-chrome >/dev/null 2>&1; then
      BROWSER_BIN="$(command -v google-chrome)"
    elif command -v chromium >/dev/null 2>&1; then
      BROWSER_BIN="$(command -v chromium)"
    elif command -v chromium-browser >/dev/null 2>&1; then
      BROWSER_BIN="$(command -v chromium-browser)"
    fi
  fi

  if [[ -n "$BROWSER_BIN" ]]; then
    echo "Launching browser for CDP attach: $BROWSER_BIN"
    "$BROWSER_BIN" \
      --remote-debugging-port=9222 \
      --user-data-dir="$BROWSER_PROFILE" \
      "https://manager.maven.markets/app/trade" >/dev/null 2>&1 &
    sleep 2
  else
    echo "No Chrome/Chromium binary found; open manually with remote debugging enabled." >&2
  fi
fi

CMD=(
  "$PYTHON_BIN" "$EXECUTOR"
  --mode "$MODE"
  --cdp-url "$CDP_URL"
  --duration-min "$DURATION_MIN"
  --poll-sec "$POLL_SEC"
  --futures-price "$FUTURES_PRICE"
  --manual-login-timeout "$MANUAL_LOGIN_TIMEOUT"
  --daily-loss "$DAILY_LOSS"
)

if [[ -n "$LIVE_FLAG" ]]; then
  CMD+=("$LIVE_FLAG")
fi
if [[ -n "$RECALIBRATE_FLAG" ]]; then
  CMD+=("$RECALIBRATE_FLAG")
fi

echo "Running: ${CMD[*]}"
cd "$ROOT_DIR"
"${CMD[@]}"
