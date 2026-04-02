#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing .env at $ENV_FILE"
  exit 1
fi

read -r -p "Maven email: " MAVEN_EMAIL
read -r -s -p "Maven password: " MAVEN_PASSWORD
echo

if [[ -z "${MAVEN_EMAIL}" || -z "${MAVEN_PASSWORD}" ]]; then
  echo "Email and password are required."
  exit 1
fi

upsert_key() {
  local key="$1"
  local value="$2"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf "\n%s=%s\n" "$key" "$value" >> "$ENV_FILE"
  fi
}

upsert_key "MAVEN_EMAIL" "$MAVEN_EMAIL"
upsert_key "MAVEN_PASSWORD" "$MAVEN_PASSWORD"
upsert_key "EXECUTION_LOGIN_USERNAME" "$MAVEN_EMAIL"
upsert_key "EXECUTION_LOGIN_PASSWORD" "$MAVEN_PASSWORD"

echo "Credentials saved to .env"
echo "Restarting backend and reconnecting execution..."

pkill -f "uvicorn astroquant.backend.main:app" 2>/dev/null || true
sleep 1

source "$ROOT_DIR/.venv/bin/activate"
nohup uvicorn astroquant.backend.main:app --host 127.0.0.1 --port 8000 --log-level info >/tmp/aq-backend.log 2>&1 &
sleep 4

curl -s -X POST "http://127.0.0.1:8000/execution/reconnect?force=true" | python -m json.tool
