#!/bin/bash
# One-time setup for permanent Cloudflare named tunnels.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
ENV_FILE="$WORKSPACE/.env"

CF_APP_TUNNEL_NAME="${CF_APP_TUNNEL_NAME:-astroquant-cpu}"
CF_NOVNC_TUNNEL_NAME="${CF_NOVNC_TUNNEL_NAME:-astroquant-novnc}"
CF_APP_HOSTNAME="${CF_APP_HOSTNAME:-}"
CF_NOVNC_HOSTNAME="${CF_NOVNC_HOSTNAME:-}"

echo "========================================="
echo "Cloudflare Named Tunnel Setup"
echo "========================================="

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is not installed"
  exit 1
fi

echo "Step 1/4: Cloudflare login"
cloudflared tunnel login

echo "Step 2/4: Create or reuse tunnels"
cloudflared tunnel create "$CF_APP_TUNNEL_NAME" 2>/dev/null || true
cloudflared tunnel create "$CF_NOVNC_TUNNEL_NAME" 2>/dev/null || true

echo "Step 3/4: Route DNS hostnames (if provided)"
if [ -n "$CF_APP_HOSTNAME" ]; then
  cloudflared tunnel route dns "$CF_APP_TUNNEL_NAME" "$CF_APP_HOSTNAME" 2>/dev/null || true
fi
if [ -n "$CF_NOVNC_HOSTNAME" ]; then
  cloudflared tunnel route dns "$CF_NOVNC_TUNNEL_NAME" "$CF_NOVNC_HOSTNAME" 2>/dev/null || true
fi

echo "Step 4/4: Persist settings to .env"
if ! grep -q '^CF_TUNNEL_MODE=' "$ENV_FILE" 2>/dev/null; then
  echo "CF_TUNNEL_MODE=named" >> "$ENV_FILE"
else
  sed -i 's/^CF_TUNNEL_MODE=.*/CF_TUNNEL_MODE=named/' "$ENV_FILE"
fi

for key in CF_APP_TUNNEL_NAME CF_NOVNC_TUNNEL_NAME CF_APP_PUBLIC_URL CF_NOVNC_PUBLIC_URL; do
  sed -i "/^${key}=/d" "$ENV_FILE" 2>/dev/null || true
done

echo "CF_APP_TUNNEL_NAME=$CF_APP_TUNNEL_NAME" >> "$ENV_FILE"
echo "CF_NOVNC_TUNNEL_NAME=$CF_NOVNC_TUNNEL_NAME" >> "$ENV_FILE"
[ -n "$CF_APP_HOSTNAME" ] && echo "CF_APP_PUBLIC_URL=https://$CF_APP_HOSTNAME" >> "$ENV_FILE"
[ -n "$CF_NOVNC_HOSTNAME" ] && echo "CF_NOVNC_PUBLIC_URL=https://$CF_NOVNC_HOSTNAME" >> "$ENV_FILE"

echo ""
echo "Named tunnel setup complete."
echo "Restart stack to apply:"
echo "  bash $WORKSPACE/stop_24h_fullstack.sh"
echo "  bash $WORKSPACE/npvps_auto_start.sh --no-chrome"
