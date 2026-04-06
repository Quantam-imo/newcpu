#!/bin/bash
# Launch Chrome with remote debugging for AstroQuant (container/WSL compatible)

set -euo pipefail

CHROME_BIN=$(which google-chrome || which chromium-browser || which chromium)
if [ -z "$CHROME_BIN" ]; then
  echo "Chrome/Chromium not found. Please install it first."
  exit 1
fi

PROFILE_DIR="${AQ_CHROME_PROFILE_DIR:-/workspaces/newcpu/data/browser_session/chrome-profile}"
FORCE_FRESH_LOGIN="${AQ_FORCE_FRESH_LOGIN:-false}"
PORT=9222
URL="${AQ_BROKER_URL:-https://manager.maven.markets/app/trade}"
API_BASE="${AQ_API_BASE:-http://127.0.0.1:8000}"
DASHBOARD_URL="${AQ_DASHBOARD_URL:-}"
AUTO_OPEN_DASHBOARD="${AQ_AUTO_OPEN_DASHBOARD:-true}"
USE_XVFB_WHEN_HEADLESS_ENV="${AQ_USE_XVFB:-true}"
XVFB_DISPLAY="${AQ_XVFB_DISPLAY:-:99}"

CHROME_MODE="${AQ_CHROME_MODE:-headed}"
HEADLESS_FLAG=""

start_xvfb_if_needed() {
  local display_ok=false

  if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    display_ok=true
  elif [ -n "${DISPLAY:-}" ]; then
    if command -v xset >/dev/null 2>&1; then
      if xset -display "${DISPLAY}" q >/dev/null 2>&1; then
        display_ok=true
      fi
    elif [ -n "${DISPLAY:-}" ]; then
      # If xset is unavailable, best-effort: assume DISPLAY is usable.
      display_ok=true
    fi
  fi

  if [ "$display_ok" = true ]; then
    return 0
  fi

  if [ "$USE_XVFB_WHEN_HEADLESS_ENV" != "true" ]; then
    return 1
  fi
  if ! command -v Xvfb >/dev/null 2>&1; then
    return 1
  fi
  if ! pgrep -f "Xvfb ${XVFB_DISPLAY}" >/dev/null 2>&1; then
    nohup Xvfb "${XVFB_DISPLAY}" -screen 0 1280x900x24 -ac +extension GLX +render -noreset >/tmp/xvfb-astroquant.log 2>&1 &
    sleep 1
  fi
  export DISPLAY="${XVFB_DISPLAY}"
  return 0
}

if [ "$CHROME_MODE" = "headless" ]; then
  HEADLESS_FLAG="--headless=new"
elif [ "$CHROME_MODE" = "headed" ]; then
  if start_xvfb_if_needed; then
    # Keep headed mode when a usable display is present or Xvfb was started.
    if [ -n "${DISPLAY:-}" ] && [ "${DISPLAY}" = "${XVFB_DISPLAY}" ]; then
      echo "Using virtual display ${XVFB_DISPLAY} for headed Chrome."
    fi
    HEADLESS_FLAG=""
  else
    echo "AQ_CHROME_MODE=headed requested but no usable display/Xvfb available; falling back to headless mode."
    HEADLESS_FLAG="--headless=new"
  fi
elif [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  HEADLESS_FLAG="--headless=new"
fi

if [ "$FORCE_FRESH_LOGIN" = "true" ]; then
  # Optional hard reset of browser session/cookies so broker always asks login.
  pkill -f "remote-debugging-port=${PORT}" 2>/dev/null || true
  sleep 1
  rm -rf "$PROFILE_DIR"
fi

mkdir -p "$PROFILE_DIR"

start_chrome() {
  local headless_flag="$1"
  nohup "$CHROME_BIN" \
    --remote-debugging-port=$PORT \
    --user-data-dir="$PROFILE_DIR" \
    --no-sandbox \
    --disable-gpu \
    --disable-software-rasterizer \
    --disable-dev-shm-usage \
    --disable-extensions \
    --disable-background-networking \
    --disable-sync \
    --disable-translate \
    --disable-default-apps \
    --disable-popup-blocking \
    --disable-background-timer-throttling \
    --disable-renderer-backgrounding \
    --disable-device-discovery-notifications \
    --disable-features=TranslateUI \
    --disable-blink-features=AutomationControlled \
    --disable-webgl \
    --disable-webgl2 \
    --disable-accelerated-2d-canvas \
    --disable-canvas-aa \
    --disable-gpu-compositing \
    --window-size=1280,900 \
    $headless_flag \
    "$URL" > /tmp/chrome-astroquant.log 2>&1 &
}

wait_for_cdp() {
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -sS --max-time 2 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

ensure_tab() {
  local target_url="$1"
  local must_contain="$2"
  local list
  list=$(curl -sS --max-time 4 "http://127.0.0.1:${PORT}/json/list" 2>/dev/null || echo "[]")
  if echo "$list" | grep -q "$must_contain"; then
    return 0
  fi
  curl -sS -X PUT --max-time 4 "http://127.0.0.1:${PORT}/json/new?${target_url}" >/dev/null 2>&1 || true
}

dedupe_page_tabs() {
  local target_url="$1"
  python3 - <<PY
import json, urllib.request
target = ${target_url@Q}
tabs = json.load(urllib.request.urlopen('http://127.0.0.1:${PORT}/json/list', timeout=5))
seen = False
for tab in tabs:
    if tab.get('type') != 'page':
        continue
    if str(tab.get('url') or '') != target:
        continue
    if not seen:
        seen = True
        continue
    tid = tab.get('id')
    if tid:
        urllib.request.urlopen(f'http://127.0.0.1:${PORT}/json/close/{tid}', timeout=5).read()
PY
}

resolve_dashboard_url() {
  if [ -n "$DASHBOARD_URL" ]; then
    echo "$DASHBOARD_URL"
    return 0
  fi

  if curl -sS --max-time 2 "http://127.0.0.1:8001/frontend/" >/dev/null 2>&1; then
    echo "http://127.0.0.1:8001/frontend/"
    return 0
  fi

  echo "http://127.0.0.1:8000/frontend/"
}

if curl -sS --max-time 2 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  echo "Chrome remote debug already running on port $PORT, reusing existing session/profile."
else
  start_chrome "$HEADLESS_FLAG"
  if ! wait_for_cdp; then
    if [ -z "$HEADLESS_FLAG" ]; then
      echo "Headed launch did not expose CDP on port $PORT; retrying in headless mode."
      pkill -f "remote-debugging-port=${PORT}" 2>/dev/null || true
      sleep 1
      HEADLESS_FLAG="--headless=new"
      start_chrome "$HEADLESS_FLAG"
      wait_for_cdp || {
        echo "Failed to start Chrome debug on port $PORT. Check /tmp/chrome-astroquant.log"
        exit 1
      }
    else
      echo "Failed to start Chrome debug on port $PORT. Check /tmp/chrome-astroquant.log"
      exit 1
    fi
  fi
fi

# Keep both broker and dashboard in the same CDP browser session.
ensure_tab "$URL" "$URL"
dedupe_page_tabs "$URL"
if [ "$AUTO_OPEN_DASHBOARD" = "true" ]; then
  DASHBOARD_URL="$(resolve_dashboard_url)"
  ensure_tab "$DASHBOARD_URL" "$DASHBOARD_URL"
  dedupe_page_tabs "$DASHBOARD_URL"
fi

if [ -n "$HEADLESS_FLAG" ]; then
  echo "Chrome launched in headless mode with remote debugging on port $PORT."
  echo "Tip: for broker login/Cloudflare challenges, rerun with AQ_CHROME_MODE=headed in a session with DISPLAY."
else
  echo "Chrome launched in headed mode with remote debugging on port $PORT."
fi

echo "Target broker URL: $URL"
if [ "$AUTO_OPEN_DASHBOARD" = "true" ]; then
  echo "Target dashboard URL: $DASHBOARD_URL"
fi
echo "Profile dir: $PROFILE_DIR"
echo "Force fresh login: $FORCE_FRESH_LOGIN"
echo ""
echo "Next steps:"
echo "  1. Complete any Cloudflare challenge in the broker tab."
echo "  2. Log into Maven/MatchTrader and wait for the order entry form to appear."
echo "  3. Keep Maven and AstroQuant dashboard tabs in this same browser session."
echo ""
echo "Validation commands:"
echo "  curl $API_BASE/status/broker_bridge"
echo "  bash /workspaces/newcpu/preflight_unattended.sh $API_BASE"
echo ""
echo "Expected unattended-ready signals:"
echo "  - broker_tab_title is not 'Just a moment...'"
echo "  - challenge_detected is false"
echo "  - order_panel.ready is true or quote is present"
