#!/bin/bash
# Launch Windows Chrome + CDP proxy from WSL2 bash.
# Solves WSL2→Windows networking: Chrome always binds CDP to 127.0.0.1 (Windows loopback)
# which WSL2 cannot reach. A Python TCP proxy runs on Windows and bridges the gap.
#
# Architecture:
#   WSL2 backend → WIN_IP:9222 → [cdp_proxy_windows.py on Windows] → 127.0.0.1:9222 → Chrome
#
# Usage: bash launch_chrome_windows.sh

# ── Config ──────────────────────────────────────────────────────────────────
BROKER_URL="${AQ_BROKER_URL:-https://manager.maven.markets/app/trade}"
CDP_PORT=9222
WIN_USER="${WIN_USER:-$(powershell.exe -Command '$env:USERNAME' 2>/dev/null | tr -d '\r\n')}"
PROFILE_WIN="C:\\Users\\${WIN_USER}\\AppData\\Local\\astroquant-profile"
PROFILE_MNT="/mnt/c/Users/${WIN_USER}/AppData/Local/astroquant-profile"
PROXY_WIN_PATH="C:\\Users\\${WIN_USER}\\AppData\\Local\\astroquant-profile\\cdp_proxy_windows.py"
PROXY_MNT_PATH="${PROFILE_MNT}/cdp_proxy_windows.py"
WIN_IP=$(ip route show default 2>/dev/null | awk '/default/{print $3}' | head -1)
WIN_IP="${WIN_IP:-192.168.16.1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Chrome binary ────────────────────────────────────────────────────────────
CHROME_PATHS=(
  "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"
  "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe"
  "/mnt/c/Users/${WIN_USER}/AppData/Local/Google/Chrome/Application/chrome.exe"
)
CHROME_WIN_PATHS=(
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"
  "C:\\Users\\${WIN_USER}\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe"
)
CHROME_BIN=""
CHROME_WIN=""
for i in "${!CHROME_PATHS[@]}"; do
  if [ -f "${CHROME_PATHS[$i]}" ]; then
    CHROME_BIN="${CHROME_PATHS[$i]}"
    CHROME_WIN="${CHROME_WIN_PATHS[$i]}"
    break
  fi
done

echo "========================================="
echo "  AstroQuant Chrome + CDP Proxy Launcher"
echo "========================================="
echo "Windows host IP : $WIN_IP"
echo "Chrome          : ${CHROME_WIN:-not found}"
echo "Profile         : $PROFILE_WIN"
echo "========================================="; echo ""

# ── Step 1: Kill ALL Chrome + any old proxy ──────────────────────────────────
echo "[1/5] Killing any existing Chrome and CDP proxy..."
taskkill.exe /F /IM chrome.exe 2>/dev/null || true
powershell.exe -Command "
  Get-Process -Name pythonw -ErrorAction SilentlyContinue |
    Where-Object { \$_.CommandLine -like '*cdp_proxy*' } |
    Stop-Process -Force -ErrorAction SilentlyContinue
" 2>/dev/null || true

echo "      Waiting 4s for processes to exit..."
sleep 4

# ── Step 2: Clean profile locks ───────────────────────────────────────────────
echo "[2/5] Cleaning Chrome profile locks..."
mkdir -p "$PROFILE_MNT"
rm -f "$PROFILE_MNT/SingletonLock" \
      "$PROFILE_MNT/SingletonCookie" \
      "$PROFILE_MNT/SingletonSocket" 2>/dev/null || true

# ── Step 3: Deploy cdp_proxy_windows.py to Windows ───────────────────────────
echo "[3/5] Deploying CDP proxy to Windows profile folder..."
if [ -f "$SCRIPT_DIR/cdp_proxy_windows.py" ]; then
  cp "$SCRIPT_DIR/cdp_proxy_windows.py" "$PROXY_MNT_PATH"
  echo "      Deployed: $PROXY_WIN_PATH"
else
  echo "      ERROR: cdp_proxy_windows.py not found in $SCRIPT_DIR"
  echo "      Run: git pull  to get the file"
  exit 1
fi

# ── Step 4: Find Windows Python ───────────────────────────────────────────────
echo "[4/5] Finding Windows Python..."
PYTHONW=""
PYTHON_SEARCH_PATHS=(
  "/mnt/c/Users/${WIN_USER}/AppData/Local/Programs/Python/Python312/pythonw.exe"
  "/mnt/c/Users/${WIN_USER}/AppData/Local/Programs/Python/Python311/pythonw.exe"
  "/mnt/c/Users/${WIN_USER}/AppData/Local/Programs/Python/Python310/pythonw.exe"
  "/mnt/c/Users/${WIN_USER}/AppData/Local/Programs/Python/Python39/pythonw.exe"
  "/mnt/c/Windows/py.exe"
  "/mnt/c/Users/${WIN_USER}/AppData/Local/Microsoft/WindowsApps/python3.exe"
)
for p in "${PYTHON_SEARCH_PATHS[@]}"; do
  if [ -f "$p" ]; then
    PYTHONW="$p"
    break
  fi
done
# Try cmd where as fallback
if [ -z "$PYTHONW" ]; then
  _py=$(cmd.exe /c "where pythonw.exe 2>nul" 2>/dev/null | head -1 | tr -d '\r\n')
  [ -n "$_py" ] && PYTHONW="/mnt/$(echo "$_py" | sed 's|\\|/|g; s|^\([A-Za-z]\):/|/mnt/\L\1/|')"
fi
if [ -z "$PYTHONW" ]; then
  # fallback to python.exe (will open a console window but will work)
  _py=$(cmd.exe /c "where python.exe 2>nul" 2>/dev/null | head -1 | tr -d '\r\n')
  [ -n "$_py" ] && PYTHONW="/mnt/$(echo "$_py" | sed 's|\\|/|g; s|^\([A-Za-z]\):/|/mnt/\L\1/|')"
fi
echo "      Python: ${PYTHONW:-NOT FOUND}"

if [ -z "$PYTHONW" ]; then
  echo ""
  echo "  ✗ Windows Python not found. Install Python for Windows from python.org"
  echo "    or the Microsoft Store, then rerun this script."
  exit 1
fi

# ── Step 5a: Launch Chrome via PowerShell Start-Process (truly detached) ─────
echo "[5/5] Launching Chrome (via PowerShell Start-Process — truly detached)..."
if [ -n "$CHROME_WIN" ]; then
  powershell.exe -Command "
    Start-Process -FilePath '${CHROME_WIN}' -ArgumentList @(
      '--remote-debugging-port=${CDP_PORT}',
      '--user-data-dir=${PROFILE_WIN}',
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-background-mode',
      '${BROKER_URL}'
    )
  " 2>/dev/null
  echo "      Chrome launched."
else
  echo "  ✗ Chrome not found. Please install Google Chrome."
  exit 1
fi

# Wait for Chrome to start listening
echo "      Waiting for Chrome CDP on 127.0.0.1:${CDP_PORT}..."
_chrome_ready=false
for i in $(seq 1 15); do
  if curl -s --max-time 1 "http://127.0.0.1:${CDP_PORT}/json/version" > /dev/null 2>&1; then
    _chrome_ready=true; break
  fi
  sleep 1
done
if [ "$_chrome_ready" = false ]; then
  echo "  ✗ Chrome CDP not responding on 127.0.0.1 after 15s."
  echo "    Chrome may have started but CDP isn't ready — continuing anyway..."
fi

# ── Step 5b: Launch CDP proxy on Windows ──────────────────────────────────────
echo "      Launching CDP proxy on Windows ($WIN_IP:${CDP_PORT} → 127.0.0.1:${CDP_PORT})..."

# Convert PROXY_WIN_PATH for use in powershell launch
powershell.exe -Command "
  Start-Process -FilePath '${PYTHONW//\//\\}' \
    -ArgumentList '${PROXY_WIN_PATH}', '${WIN_IP}' \
    -WindowStyle Hidden
" 2>/dev/null || \
powershell.exe -Command "
  \$p = Start-Process -FilePath '${PYTHONW//\//\\}' \
    -ArgumentList '\"${PROXY_WIN_PATH}\" \"${WIN_IP}\"' \
    -PassThru -WindowStyle Hidden
  Write-Host \"Proxy PID: \$(\$p.Id)\"
" 2>/dev/null || true

echo "      CDP proxy launched. Log: C:\\Users\\Public\\cdp_proxy.log"
sleep 3

# ── Verify CDP via Windows host IP ────────────────────────────────────────────
echo ""
echo "Verifying CDP reachability from WSL2 via $WIN_IP:${CDP_PORT}..."
for i in $(seq 1 15); do
  if curl -s --max-time 1 "http://${WIN_IP}:${CDP_PORT}/json/version" > /dev/null 2>&1; then
    echo ""
    echo "✓ CDP LIVE at $WIN_IP:${CDP_PORT}"
    curl -s "http://${WIN_IP}:${CDP_PORT}/json/version" | \
      python3 -c "import sys,json; d=json.load(sys.stdin); print('  Browser:', d.get('Browser','?'))" 2>/dev/null || true

    # Update .env with correct WIN_IP
    echo ""
    echo "Updating .env CDP endpoints → $WIN_IP ..."
    sed -i "s|ws://127.0.0.1:9222|ws://${WIN_IP}:9222|g" .env
    sed -i "s|http://127.0.0.1:9222|http://${WIN_IP}:9222|g" .env
    grep -E "^(CDP_ENDPOINT|EXECUTION_BROWSER_CDP_URL|AQ_CDP_BASE)" .env 2>/dev/null || true

    echo ""
    echo "========================================="
    echo "  Chrome + CDP proxy running!"
    echo "========================================="
    echo "  Log into your broker in the Chrome window on Windows."
    echo "  Then restart the backend to pick up new .env:"
    echo ""
    echo "  pkill -f start_24h_fullstack.sh"
    echo "  rm -f /tmp/astroquant_fullstack.lock"
    echo "  bash npvps_auto_start.sh"
    echo "========================================="
    exit 0
  fi
  sleep 1
done

echo ""
echo "✗ CDP proxy not reachable at $WIN_IP:${CDP_PORT} after 15s."
echo ""
echo "Check proxy log:  cat /mnt/c/Users/Public/cdp_proxy.log"
echo ""
echo "Possible causes:"
echo "  • Windows Firewall blocking port 9222 — run in PowerShell (admin):"
echo "    New-NetFirewallRule -DisplayName AstroQuant-CDP -Direction Inbound -Protocol TCP -LocalPort 9222 -Action Allow"
echo "  • Python not found or proxy crashed — check the log above"


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

# Step 1: Kill ALL Chrome instances so new launch gets --remote-debugging-address=0.0.0.0
echo "Killing ALL Chrome instances (required for clean debug launch)..."
taskkill.exe /F /IM chrome.exe 2>/dev/null || true
# Also kill anything holding port 9222 via PowerShell
powershell.exe -Command "
  \$pids = (Get-NetTCPConnection -LocalPort 9222 -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
  foreach (\$p in \$pids) { Stop-Process -Id \$p -Force -ErrorAction SilentlyContinue }
" 2>/dev/null || true
echo "Waiting 5s for Chrome to fully exit..."
sleep 5

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
  # Also try Windows host IP (WSL2 NAT mode) — try both resolv.conf and ip route
  WIN_IP=$(grep nameserver /etc/resolv.conf 2>/dev/null | awk '{print $2}' | head -1)
  WIN_IP2=$(ip route show default 2>/dev/null | awk '/default/{print $3}' | head -1)
  for _wip in "$WIN_IP" "$WIN_IP2"; do
    [ -z "$_wip" ] && continue
    if curl -s --max-time 1 "http://${_wip}:${PORT}/json/version" > /dev/null 2>&1; then
      echo "✓ Chrome CDP reachable via Windows host IP: ${_wip}:${PORT}"
      echo "  Updating .env CDP endpoints to use ${_wip}..."
      sed -i "s|ws://127.0.0.1:9222|ws://${_wip}:9222|g" .env 2>/dev/null || true
      echo "  Creating socat bridge: 127.0.0.1:9222 → ${_wip}:9222"
      pkill -f "socat TCP-LISTEN:9222" 2>/dev/null || true
      sleep 1
      nohup socat TCP-LISTEN:9222,fork,reuseaddr TCP:"${_wip}":9222 </dev/null >/tmp/socat_cdp.log 2>&1 &
      echo "  socat bridge PID: $!"
      echo ""
      echo "Restart stack: pkill -f start_24h_fullstack.sh; rm -f /tmp/astroquant_fullstack.lock; bash npvps_auto_start.sh"
      exit 0
    fi
  done
  sleep 1
done

echo ""
echo "✗ Chrome CDP not responding after 20s. Check log:"
cat /tmp/chrome_windows.log 2>/dev/null | tail -20
echo ""
echo "Try manually opening Chrome with:"
echo "  powershell.exe -Command \"Start-Process 'chrome.exe' -ArgumentList '--remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --user-data-dir=C:\\\\Users\\\\${WIN_USER}\\\\AppData\\\\Local\\\\astroquant-profile ${BROKER_URL}'\""

