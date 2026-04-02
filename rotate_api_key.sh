#!/bin/bash
# rotate_api_key.sh — Update a key in .env and send Telegram notification.
#
# Usage:
#   bash rotate_api_key.sh DATABENTO_API_KEY db-newkeyvalue...
#   bash rotate_api_key.sh TELEGRAM_BOT_TOKEN 123456:ABCDEF...
#   bash rotate_api_key.sh list          — show which keys are configured
#
# Supported rotatable keys:
#   DATABENTO_API_KEY
#   TELEGRAM_BOT_TOKEN
#   TELEGRAM_CHAT_ID
#   MAVEN_USERNAME  MAVEN_PASSWORD
#   CF_APP_TUNNEL_NAME  CF_APP_PUBLIC_URL
#   BROKER_API_KEY  BROKER_SECRET

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
ENV_FILE="$WORKSPACE/.env"
DATA_DIR="$WORKSPACE/data"
LOG_DIR="$DATA_DIR/logs"
LOG_FILE="$LOG_DIR/key_rotation.log"

mkdir -p "$LOG_DIR"

_log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# ── Send Telegram notification ────────────────────────────────
_notify() {
  local msg="$1"
  if [ -f "$ENV_FILE" ]; then
    set -a; . "$ENV_FILE"; set +a
  fi
  local tok="${TELEGRAM_BOT_TOKEN:-}"
  local cid="${TELEGRAM_CHAT_ID:-}"
  if [ "${TELEGRAM_ALERT_ENABLED:-false}" = "true" ] && [ -n "$tok" ] && [ -n "$cid" ]; then
    curl -sS --request POST "https://api.telegram.org/bot${tok}/sendMessage" \
      --data-urlencode "chat_id=${cid}" \
      --data-urlencode "text=${msg}" \
      -o /dev/null 2>/dev/null || true
  fi
}

# ── List mode ─────────────────────────────────────────────────
if [ "${1:-}" = "list" ]; then
  echo ""
  echo "=== Rotatable keys in .env ==="
  for key in DATABENTO_API_KEY TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID \
             MAVEN_USERNAME MAVEN_PASSWORD \
             CF_APP_TUNNEL_NAME CF_APP_PUBLIC_URL \
             BROKER_API_KEY BROKER_SECRET; do
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
      _val=$(grep "^${key}=" "$ENV_FILE" | cut -d= -f2-)
      _masked=$(echo "$_val" | sed 's/.\{4\}$/****/;s/^.\{6\}/******/')
      echo "  $key = $_masked"
    else
      echo "  $key = [NOT SET]"
    fi
  done
  echo ""
  exit 0
fi

# ── Argument validation ───────────────────────────────────────
KEY_NAME="${1:-}"
NEW_VALUE="${2:-}"

if [ -z "$KEY_NAME" ] || [ -z "$NEW_VALUE" ]; then
  echo "Usage: bash rotate_api_key.sh <KEY_NAME> <NEW_VALUE>"
  echo "       bash rotate_api_key.sh list"
  echo ""
  echo "Example:"
  echo "  bash rotate_api_key.sh DATABENTO_API_KEY db-newkey123..."
  exit 1
fi

# Safety: only allow known rotatable keys to prevent accidental .env corruption
ALLOWED_KEYS="DATABENTO_API_KEY TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID MAVEN_USERNAME MAVEN_PASSWORD CF_APP_TUNNEL_NAME CF_APP_PUBLIC_URL BROKER_API_KEY BROKER_SECRET"
_allowed=false
for k in $ALLOWED_KEYS; do
  [ "$k" = "$KEY_NAME" ] && _allowed=true && break
done
if [ "$_allowed" = "false" ]; then
  echo "ERROR: '$KEY_NAME' is not in the allowed rotation list."
  echo "Allowed keys: $ALLOWED_KEYS"
  exit 1
fi

# ── Backup .env before modifying ─────────────────────────────
BACKUP_FILE="$WORKSPACE/.env.backup_$(date '+%Y%m%d_%H%M%S')"
cp "$ENV_FILE" "$BACKUP_FILE"
_log "Backed up .env → $BACKUP_FILE"

# ── Rotate the key ────────────────────────────────────────────
OLD_VALUE=$(grep "^${KEY_NAME}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- || echo "[not set]")
OLD_MASKED=$(echo "$OLD_VALUE" | sed 's/.\{4\}$/****/;s/^.\{6\}/******/')
NEW_MASKED=$(echo "$NEW_VALUE"  | sed 's/.\{4\}$/****/;s/^.\{6\}/******/')

if grep -q "^${KEY_NAME}=" "$ENV_FILE"; then
  # Replace existing entry
  # Use awk for safe replacement (handles values with special chars)
  awk -v key="$KEY_NAME" -v val="$NEW_VALUE" \
    'BEGIN{FS=OFS="="} $1==key {$2=val; print; next} {print}' \
    "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"
  _log "Rotated $KEY_NAME: $OLD_MASKED  →  $NEW_MASKED"
else
  # Append new entry
  echo "${KEY_NAME}=${NEW_VALUE}" >> "$ENV_FILE"
  _log "Added $KEY_NAME: $NEW_MASKED"
fi

# ── Telegram notification ─────────────────────────────────────
HOST=$(hostname 2>/dev/null || echo "cpu")
_notify "AstroQuant KEY ROTATED
Host: $HOST
Key: $KEY_NAME
Old (masked): $OLD_MASKED
New (masked): $NEW_MASKED
Time: $(date '+%Y-%m-%d %H:%M:%S %Z')
Action: Restart services if required."

echo ""
echo "=== Key rotation complete ==="
echo "  Key:    $KEY_NAME"
echo "  Before: $OLD_MASKED"
echo "  After:  $NEW_MASKED"
echo "  Backup: $BACKUP_FILE"
echo ""
echo "Next steps:"
echo "  • Restart backends to pick up new key:"
echo "      bash stop_24h_fullstack.sh && bash start_24h_fullstack.sh"
echo "  • Or use /reload command in Telegram if live-reload is available"
echo "  • Keep backup for rollback: cp $BACKUP_FILE .env"
echo ""

_log "Key rotation complete for $KEY_NAME"
