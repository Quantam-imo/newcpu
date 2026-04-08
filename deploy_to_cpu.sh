#!/bin/bash
# Deploy to NPVPS CPU - All-in-one script
# Usage: ./deploy_to_cpu.sh cpu_user@CPU_IP

set -e

if [ -z "$1" ]; then
  echo "Usage: ./deploy_to_cpu.sh cpu_user@192.168.1.100"
  exit 1
fi

DEST="$1"
CPU_USER=$(echo "$DEST" | cut -d@ -f1)
CPU_IP=$(echo "$DEST" | cut -d@ -f2)

echo "╔════════════════════════════════════════════════════════╗"
echo "║  AstroQuant Deployment to NPVPS CPU                    ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "Source:      /workspaces/newcpu"
echo "Destination: $DEST:/home/newcpu"
echo ""

# Step 1: Check connectivity
echo "[1/5] Testing connection to CPU..."
if ! timeout 5 ssh -o ConnectTimeout=5 "$DEST" "echo 'OK'" > /dev/null 2>&1; then
  echo "✗ Cannot connect to CPU"
  echo "  Fix: Update CPU_IP or set up SSH keys"
  exit 1
fi
echo "✓ SSH connection successful"
echo ""

# Step 2: Prepare CPU directory
echo "[2/5] Preparing directory on CPU..."
ssh "$DEST" "
  mkdir -p /home/$CPU_USER/newcpu/data/logs
  echo '✓ Directory created'
"
echo ""

# Step 3: Copy files
echo "[3/5] Copying project files..."
echo "      (this may take a minute for first copy)"
rsync -avz \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='*.pyc' \
  /workspaces/newcpu/ "$DEST":/home/$CPU_USER/newcpu/ 2>&1 | tail -20

echo ""
echo "✓ Files copied successfully"
echo ""

# Step 4: Set permissions
echo "[4/5] Setting script permissions on CPU..."
ssh "$DEST" "
  cd /home/$CPU_USER/newcpu
  chmod +x *.sh
  chmod 755 data/logs 2>/dev/null || true
  echo '✓ Permissions set'
"
echo ""

# Step 5: Summary
echo "[5/5] Deployment complete!"
echo ""
echo "════════════════════════════════════════════════════════"
echo "Next steps:"
echo "════════════════════════════════════════════════════════"
echo ""
echo "Option A - Start remotely:"
echo "  ./connect_cpu.sh start"
echo ""
echo "Option B - SSH and start manually:"
echo "  ssh $DEST"
echo "  cd /home/$CPU_USER/newcpu"
echo "  bash npvps_auto_start.sh"
echo ""
echo "Monitor:"
echo "  ./connect_cpu.sh monitor"
echo ""
echo "Access dashboard:"
echo "  ./connect_cpu.sh dashboard"
echo "  Or: ./connect_cpu.sh tunnel-url"
echo ""
