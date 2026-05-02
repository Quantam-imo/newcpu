#!/bin/bash
# Poll drop location and ingest MT5 feed whenever a newer candidate appears.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTERVAL_SEC="${MT5_INGEST_WATCH_INTERVAL_SEC:-60}"

if ! [[ "$INTERVAL_SEC" =~ ^[0-9]+$ ]] || [[ "$INTERVAL_SEC" -lt 1 ]]; then
  echo "Invalid MT5_INGEST_WATCH_INTERVAL_SEC=$INTERVAL_SEC (must be integer >= 1)"
  exit 2
fi

echo "Starting MT5 drop ingest watcher (interval=${INTERVAL_SEC}s)"
echo "Using script: $ROOT_DIR/ingest_mt5_feed_from_drop.sh"
echo "Press Ctrl+C to stop"
echo

while true; do
  "$ROOT_DIR/ingest_mt5_feed_from_drop.sh" || true
  sleep "$INTERVAL_SEC"
done
