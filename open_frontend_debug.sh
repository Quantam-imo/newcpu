#!/usr/bin/env bash
# Opens the AstroQuant frontend inside the existing debug Chrome session (CDP port 9222).
# Usage: bash open_frontend_debug.sh [url]
#   url defaults to http://127.0.0.1:8000/frontend/

set -euo pipefail

CDP_PORT="${CDP_PORT:-9222}"
TARGET_URL="${1:-http://127.0.0.1:8000/frontend/}"

OPENER_URL="http://127.0.0.1:${CDP_PORT}/json/new?${TARGET_URL}"

# Check CDP is reachable
if ! curl -sf "http://127.0.0.1:${CDP_PORT}/json/version" >/dev/null 2>&1; then
  echo "ERROR: Debug Chrome is not running on port ${CDP_PORT}."
  echo "Start it first: bash start_chrome_remote_debug.sh"
  exit 1
fi

echo "Opening in debug Chrome: ${TARGET_URL}"
RESULT=$(curl -sfX PUT "${OPENER_URL}" 2>&1)
if [ $? -eq 0 ] && [ -n "$RESULT" ]; then
  TAB_URL=$(echo "$RESULT" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("url","unknown"))' 2>/dev/null || echo "done")
  echo "Tab opened: ${TAB_URL}"
else
  echo "WARNING: Could not open tab via CDP. Try manually in your browser: ${OPENER_URL}"
  exit 1
fi
