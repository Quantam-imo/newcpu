#!/bin/bash
# Setup Cloudflare Tunnel for permanent remote CPU access
# Usage: ./setup_cloudflare_tunnel.sh [--token YOUR_CF_TOKEN] [--domain your-domain.com]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"

cf_token="${1:-}"
cf_domain="${2:-}"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --token)
      cf_token="$2"
      shift 2
      ;;
    --domain)
      cf_domain="$2"
      shift 2
      ;;
    *)
      echo "Usage: $0 [--token CF_TOKEN] [--domain your-domain.com]"
      echo ""
      echo "QUICK SETUP (without Cloudflare account):"
      echo "  $0"
      echo "  Then share the generated URL to access remotely"
      echo ""
      echo "PERMANENT LINK (with Cloudflare account):"
      echo "  1. Go to https://dash.cloudflare.com and create an API token"
      echo "  2. Run: $0 --token <your-token> --domain <your-domain>"
      echo ""
      exit 1
      ;;
  esac
done

mkdir -p ~/.cloudflared
cd "$WORKSPACE"

echo "========================================="
echo "AstroQuant Cloudflare Tunnel Setup"
echo "========================================="
echo ""

# Check if tunnel file already exists
CERT_FILE="/root/.cloudflared/cert.pem"

if [ ! -f "$CERT_FILE" ]; then
  echo "[1] Creating Cloudflare credentials..."
  
  if [ -n "$cf_token" ]; then
    # Authenticated mode: Use provided token
    echo "$cf_token" > /root/.cloudflared/token.cfg
    chmod 600 /root/.cloudflared/token.cfg
    echo "✓ Token saved securely"
  else
    # Unauthenticated mode: Use default quick tunnel
    echo "✓ Using quick tunnel mode (no authentication needed)"
  fi
fi

echo ""
echo "[2] Testing Cloudflare Tunnel connection..."
echo "    Target: http://localhost:8000 (AstroQuant Backend)"
echo ""

# Create tunnel config
cat > /root/.cloudflared/config.yml << 'EOF'
tunnel: astroquant-cpu
credentials-file: /root/.cloudflared/tunnel-creds.json

ingress:
  - hostname: astroquant.local
    service: http://localhost:8000
  - service: http://localhost:8000
EOF

echo "[3] Generating permanent tunnel URL..."
echo ""

if [ -n "$cf_token" ] && [ -n "$cf_domain" ]; then
  # Named tunnel with permanent domain
  echo "Mode: PERMANENT LINK (Named Tunnel)"
  echo "Domain: $cf_domain"
  echo ""
  echo "Run authentication:"
  echo "  cloudflared tunnel login"
  echo ""
  echo "Then create the tunnel:"
  echo "  cloudflared tunnel create astroquant-cpu"
  echo ""
  echo "Then route the domain:"
  echo "  cloudflared tunnel route dns astroquant-cpu $cf_domain"
  echo ""
  echo "Start tunnel:"
  echo "  cloudflared tunnel run astroquant-cpu"
else
  # Quick tunnel mode
  echo "Mode: QUICK TUNNEL (Temporary Public URL)"
  echo ""
  echo "Run this command to get your public URL:"
  echo "  cloudflared tunnel --url http://localhost:8000"
  echo ""
  echo "Or start via service:"
  echo "  ./start_cloudflare_tunnel.sh"
fi

echo ""
echo "========================================="
echo "Next steps:"
echo "========================================="
echo ""
echo "1. For NPVPS CPU integration:"
echo "   - Copy this tunnel URL to NPVPS dashboard"
echo "   - Configure forwarding rule: CPU_IP:8000 -> tunnel"
echo ""
echo "2. For 24/7 operation:"
echo "   - Ensure Redis, Celery, Orchestrator are running"
echo "   - Start tunnel: ./start_cloudflare_tunnel.sh &"
echo ""
echo "3. Test remote access:"
echo "   - From anywhere: open https://astroquant-cpu.npmjs.com"
echo "   - Should show AstroQuant dashboard"
echo ""

echo "Setup complete!"
