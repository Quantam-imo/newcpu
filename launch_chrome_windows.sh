#!/bin/bash
# Launch Windows Chrome with remote debugging from inside WSL2 bash.
# Usage: bash launch_chrome_windows.sh

BROKER_URL="${AQ_BROKER_URL:-https://manager.maven.markets/app/trade}"
PORT=9222
WIN_USER="${WIN_USER:-$(powershell.exe -Command 'echo $env:USERNAME' 2>/dev/null | tr -d '\r\n')}"
PROFILE_DIR="C:\\Users\\${WIN_USER}\\AppData\\Local\\astroquant-profile"
PROFILE_MOUNT="/mnt/c/Users/${WIN_USER}/AppData/Local/astroquant-profile"

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

# Step 1: Kill any existing Chrome using the debug port or our profile
echo "Killing any existing Chrome debug instances..."
taskkill.exe /F /FI "IMAGENAME eq chrome.exe" /FI "WINDOWTITLE eq *astroquant*" 2>/dev/null || true
# Kill anything holding port 9222
powershell.exe -Command "
  \$pids = (Get-NetTCPConnection -LocalPort 9222 -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
  foreach (\$p in \$pids) { Stop-Process -Id \$p -Force -ErrorAction SilentlyContinue }
" 2>/dev/null || true
sleep 2

# Step 2: Remove SingletonLock so Chrome doesn't refuse to start
if [ -d "$PROFILE_MOUNT" ]; then
  rm -f "$PROFILE_MOUNT/SingletonLock" \
        "$PROFILE_MOUNT/SingletonCookie" \
        "$PROFILE_MOUNT/SingletonSocket" 2>/dev/null || true
  echo "Cleaned profile locks in $PROFILE_MOUNT"
fi

if [ -z "$CHROME_BIN" ]; then
  echo "Chrome not found in standard paths. Trying via PowerShell..."
  powershell.exe -Command "Start-Process 'chrome.exe' -ArgumentList '--remote-debugging-port=${PORT} --remote-debugging-address=0.0.0.0 --user-data-dir=${PROFILE_DIR} --no-first-run ${BROKER_URL}'"
else
  echo "Launching: $CHROME_BIN"
  echo "  CDP port    : $PORT (all interfaces)"
  echo "  Profile     : $PROFILE_DIR"
  echo "  URL         : $BROKER_URL"
  "$CHROME_BIN" \
    "--remote-debugging-port=${PORT}" \
    "--remote-debugging-address=0.0.0.0" \
    "--user-data-dir=${PROFILE_DIR}" \
    --no-first-run \
    --no-default-browser-check \
    --no-sandbox \
    --disable-background-mode \
    "$BROKER_URL" \
    > /tmp/chrome_windows.log 2>&1 &
  echo "Chrome started (PID: $!)."
fi

# Step 3: Wait for CDP to be reachable
echo "Waiting for Chrome CDP on port ${PORT}..."
for i in $(seq 1 20); do
  if curl -s --max-time 1 "http://127.0.0.1:${PORT}/json/version" > /dev/null 2>&1; then
    echo "✓ Chrome CDP is live on 127.0.0.1:${PORT}"
    curl -s "http://127.0.0.1:${PORT}/json/version" | python3 -c "import sys,json; d=json.load(sys.stdin); print('  Browser:', d.get('Browser','?'))" 2>/dev/null || true
    echo ""
    echo "Now log into your broker in the Chrome window."
    echo "Then run:  curl -X POST http://localhost:8000/status/broker_bridge/recover?force_reconnect=true"
    exit 0
  fi
  # Also try Windows host IP (WSL2 NAT mode)
  WIN_IP=$(ip route show default 2>/dev/null | awk '/default/{print $3}' | head -1)
  if [ -n "$WIN_IP" ] && curl -s --max-time 1 "http://${WIN_IP}:${PORT}/json/version" > /dev/null 2>&1; then
    echo "✓ Chrome CDP reachable via Windows host IP: ${WIN_IP}:${PORT}"
    echo "  Updating .env CDP endpoints to use ${WIN_IP}..."
    sed -i "s|ws://127.0.0.1:9222|ws://${WIN_IP}:9222|g" .env 2>/dev/null || true
    echo "  CDP_ENDPOINT=ws://${WIN_IP}:9222"
    echo ""
    echo "Restart the stack: pkill -f start_24h_fullstack.sh; rm -f /tmp/astroquant_fullstack.lock; bash npvps_auto_start.sh"
    exit 0
  fi
  sleep 1
done

echo ""
echo "✗ Chrome CDP not responding after 20s. Check log:"
cat /tmp/chrome_windows.log 2>/dev/null | tail -20
echo ""
echo "Try manually opening Chrome with:"
echo "  powershell.exe -Command \"Start-Process 'chrome.exe' -ArgumentList '--remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --user-data-dir=C:\\\\Users\\\\${WIN_USER}\\\\AppData\\\\Local\\\\astroquant-profile ${BROKER_URL}'\""

