#!/bin/bash
# Send AstroQuant remote-access alert to Telegram bot chat.
# Configure in .env:
#   TELEGRAM_ALERT_ENABLED=true
#   TELEGRAM_BOT_TOKEN=123456:ABCDEF...
#   TELEGRAM_CHAT_ID=123456789

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
DATA_DIR="$WORKSPACE/data"
LOG_DIR="$DATA_DIR/logs"
ENV_FILE="$WORKSPACE/.env"
LOG_FILE="$LOG_DIR/telegram_alert.log"
LAST_HASH_FILE="$DATA_DIR/last_telegram_alert.hash"

mkdir -p "$LOG_DIR" "$DATA_DIR"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

if [ "${TELEGRAM_ALERT_ENABLED:-false}" != "true" ]; then
  echo "[$(date)] Telegram alert disabled" >> "$LOG_FILE"
  exit 0
fi

BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT_ID="${TELEGRAM_CHAT_ID:-}"
if [ -z "$BOT_TOKEN" ] || [ -z "$CHAT_ID" ]; then
  echo "[$(date)] Telegram alert skipped: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID" >> "$LOG_FILE"
  exit 0
fi

APP_URL=$(cat "$DATA_DIR/tunnel_url.txt" 2>/dev/null || echo "PENDING")
NOVNC_URL=$(cat "$DATA_DIR/novnc_tunnel_url.txt" 2>/dev/null || echo "PENDING")
HOSTNAME_VALUE=$(hostname 2>/dev/null || echo "cpu")
EVENT_NAME="${1:-startup}"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S %Z')

MESSAGE=$(cat <<EOF
AstroQuant ${EVENT_NAME} alert
Host: ${HOSTNAME_VALUE}
Time: ${TIMESTAMP}
App: ${APP_URL}
Remote desktop: ${NOVNC_URL}
EOF
)

PAYLOAD_HASH=$(printf '%s' "$MESSAGE" | sha256sum | awk '{print $1}')

if [ "${FORCE_ALERT:-0}" != "1" ] && [ -f "$LAST_HASH_FILE" ] && [ "$(cat "$LAST_HASH_FILE" 2>/dev/null)" = "$PAYLOAD_HASH" ]; then
  echo "[$(date)] Telegram alert skipped: unchanged payload" >> "$LOG_FILE"
  exit 0
fi

HTTP_CODE=$(curl -sS -o /tmp/astroquant_telegram_alert.out -w '%{http_code}' \
  --request POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${CHAT_ID}" \
  --data-urlencode "text=${MESSAGE}")

if [ "$HTTP_CODE" = "200" ]; then
  echo "$PAYLOAD_HASH" > "$LAST_HASH_FILE"
  echo "[$(date)] Telegram alert sent successfully" >> "$LOG_FILE"
else
  echo "[$(date)] Telegram alert failed (HTTP $HTTP_CODE): $(cat /tmp/astroquant_telegram_alert.out 2>/dev/null)" >> "$LOG_FILE"
fi