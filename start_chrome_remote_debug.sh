#!/bin/bash
# Launch Chrome with remote debugging for AstroQuant (container/WSL compatible)

CHROME_BIN=$(which google-chrome || which chromium-browser || which chromium)
if [ -z "$CHROME_BIN" ]; then
  echo "Chrome/Chromium not found. Please install it first."
  exit 1
fi

PROFILE_DIR="/tmp/chrome-profile"
PORT=9222
URL="https://manager.maven.markets/app/trade"

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
  --window-size=1280,900 \
  --headless=new \
  "$URL" > /tmp/chrome-astroquant.log 2>&1 &

echo "Chrome launched with remote debugging on port $PORT."
