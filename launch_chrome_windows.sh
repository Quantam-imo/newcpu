#!/bin/bash
# Launch Windows Chrome with remote debugging from inside WSL2 bash.
# Usage: bash launch_chrome_windows.sh

set -euo pipefail

BROKER_URL="${AQ_BROKER_URL:-https://manager.maven.markets/app/trade}"
PORT=9222
WIN_USER="${WIN_USER:-$(powershell.exe -Command 'echo $env:USERNAME' 2>/dev/null | tr -d '\r\n')}"
PROFILE_DIR="C:\\Users\\${WIN_USER}\\AppData\\Local\\astroquant-profile"

# Common Chrome install paths on Windows
CHROME_PATHS=(
  "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"
  "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe"
  "/mnt/c/Users/${WIN_USER}/AppData/Local/Google/Chrome/Application/chrome.exe"
)

CHROME_BIN=""
for p in "${CHROME_PATHS[@]}"; do
  if [ -f "$p" ]; then
    CHROME_BIN="$p"
    break
  fi
done

if [ -z "$CHROME_BIN" ]; then
  echo "Chrome not found in standard Windows paths."
  echo "Trying via powershell.exe..."
  powershell.exe -Command "Start-Process 'chrome.exe' -ArgumentList '--remote-debugging-port=${PORT} --user-data-dir=${PROFILE_DIR} ${BROKER_URL}'"
  echo "Chrome launched via PowerShell."
  exit 0
fi

echo "Launching Windows Chrome: $CHROME_BIN"
echo "  CDP port : $PORT"
echo "  Profile  : $PROFILE_DIR"
echo "  URL      : $BROKER_URL"

"$CHROME_BIN" \
  "--remote-debugging-port=${PORT}" \
  "--user-data-dir=${PROFILE_DIR}" \
  --no-first-run \
  --no-default-browser-check \
  "$BROKER_URL" \
  > /tmp/chrome_windows.log 2>&1 &

echo "Chrome started (PID: $!). Log: /tmp/chrome_windows.log"
echo ""
echo "Now log into your broker in the Chrome window that opened on Windows."
echo "Then run:  curl -s http://localhost:8000/health"
