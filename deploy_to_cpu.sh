#!/bin/bash
# Deploy AstroQuant to Physical CPU (32GB RAM / 1TB SSD)
# Usage: ./deploy_to_cpu.sh user@CPU_IP
# Example: ./deploy_to_cpu.sh astroquant@192.168.1.100

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 user@CPU_IP"
  exit 1
fi

DEST="$1"
CPU_USER=$(echo "$DEST" | cut -d@ -f1)
WORKSPACE="/home/$CPU_USER/newcpu"

echo "╔════════════════════════════════════════════════════════╗"
echo "║  AstroQuant Deploy → Physical CPU (32GB / 1TB)         ║"
echo "╚════════════════════════════════════════════════════════╝"
echo "Destination: $DEST:$WORKSPACE"
echo ""

# Step 1: Check connectivity
echo "[1/6] Testing SSH connection..."
if ! timeout 8 ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$DEST" "echo OK" > /dev/null 2>&1; then
  echo "✗ Cannot connect. Run: ssh-copy-id $DEST"
  exit 1
fi
echo "✓ SSH OK"

# Step 2: Ensure dependencies on target
echo "[2/6] Checking CPU dependencies..."
ssh "$DEST" bash << 'REMOTE'
set -e
echo "  → Python3: $(python3 --version 2>&1)"
echo "  → Git:     $(git --version 2>&1)"
command -v google-chrome >/dev/null 2>&1 && echo "  → Chrome:  $(google-chrome --version 2>&1)" || \
  command -v chromium-browser >/dev/null 2>&1 && echo "  → Chrome:  $(chromium-browser --version 2>&1)" || \
  echo "  ⚠ Chrome not found — install with: sudo apt install -y chromium-browser"
command -v redis-cli >/dev/null 2>&1 && echo "  → Redis:   OK" || \
  echo "  ⚠ Redis not found — install with: sudo apt install -y redis-server"
REMOTE

# Step 3: Copy files
echo "[3/6] Syncing project files (exclude .venv / __pycache__)..."
rsync -az --delete \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache' \
  --exclude='.mypy_cache' \
  --exclude='data/logs/*.log' \
  --exclude='data/browser_session/' \
  /workspaces/newcpu/ "$DEST":"$WORKSPACE"/ 2>&1 | tail -10
echo "✓ Files synced"

# Step 4: Set up virtual env and install deps
echo "[4/6] Setting up Python venv on CPU..."
ssh "$DEST" bash << REMOTE
set -e
cd "$WORKSPACE"
if [ ! -d .venv ]; then
  echo "  → Creating venv..."
  python3 -m venv .venv
fi
echo "  → Installing requirements..."
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo "  ✓ Python env ready"
REMOTE

# Step 5: Set permissions + configure autostart
echo "[5/6] Configuring autostart (systemd / cron)..."
ssh "$DEST" bash << REMOTE
set -e
cd "$WORKSPACE"
chmod +x *.sh 2>/dev/null || true
mkdir -p data/logs data/browser_session
echo "  → Running enable_boot_autostart.sh..."
bash enable_boot_autostart.sh
echo "  ✓ Boot autostart configured"
REMOTE

# Step 6: Summary
echo ""
echo "[6/6] ✓ Deployment complete!"
echo ""
echo "════════════════════════════════════════════════════════"
echo "FIRST BOOT on physical CPU:"
echo "════════════════════════════════════════════════════════"
echo "  1. Reboot the CPU — AstroQuant auto-starts on boot"
echo "  2. Open browser (VNC or local): $WORKSPACE/data/browser_session/chrome-profile"
echo "     Log into Maven Markets when Chrome opens"
echo "  3. Verify: curl http://CPU_IP:8000/health"
echo ""
echo "Manual start (if needed):"
echo "  ssh $DEST"
echo "  cd $WORKSPACE && bash start_24h_fullstack.sh"
echo ""
echo "Monitor logs:"
echo "  ssh $DEST tail -f $WORKSPACE/data/logs/fullstack.log"
echo ""
echo "Dashboard: http://CPU_IP:8000/frontend/"
echo "════════════════════════════════════════════════════════"
