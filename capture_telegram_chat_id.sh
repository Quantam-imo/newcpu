#!/bin/bash
# Capture Telegram chat id from bot updates and persist to .env.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
ENV_FILE="$WORKSPACE/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "Missing TELEGRAM_BOT_TOKEN in .env"
  exit 1
fi

echo "Fetching updates..."
RESP=$(curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates")
CHAT_ID=$(printf '%s' "$RESP" | python - <<'PY'
import json,sys
try:
    obj=json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)
updates=obj.get("result",[])
chat_id=""
for u in reversed(updates):
    msg=u.get("message") or u.get("edited_message") or {}
    chat=msg.get("chat") or {}
    cid=chat.get("id")
    if cid is not None:
        chat_id=str(cid)
        break
print(chat_id)
PY
)

if [ -z "$CHAT_ID" ]; then
  echo "No chat id found yet. Send /start to your bot, then rerun this script."
  exit 2
fi

sed -i '/^TELEGRAM_CHAT_ID=/d' "$ENV_FILE" 2>/dev/null || true
echo "TELEGRAM_CHAT_ID=$CHAT_ID" >> "$ENV_FILE"

echo "Captured TELEGRAM_CHAT_ID=$CHAT_ID"
