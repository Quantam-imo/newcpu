#!/bin/bash
# Prepare local network DNS config
# Optional: Configure mDNS for hostname-based access

set -e

echo "╔════════════════════════════════════════════════════════╗"
echo "║  Local Network Setup - mDNS (Avahi)                   ║"
echo "╜════════════════════════════════════════════════════════╝"
echo ""

HOSTNAME="${1:-astroquant-cpu}"

echo "This script helps you access your CPU by hostname instead of IP"
echo "Example: ssh cpu_user@astroquant-cpu (instead of IP address)"
echo ""

# Check if running on CPU
if [ "$(whoami)" != "root" ] && [ "$(whoami)" != "ubuntu" ]; then
  echo "ERROR: Run this on the NPVPS CPU itself"
  echo "SSH to CPU first, then run."
  exit 1
fi

echo "[1] Installing mDNS (Avahi)..."
sudo apt-get update -qq
sudo apt-get install -y avahi-daemon avahi-utils 2>&1 | grep -v "^Get\|^Reading\|^Building" || true

echo "[2] Configuring hostname..."
echo "$HOSTNAME" | sudo tee /etc/hostname > /dev/null
sudo hostnamectl set-hostname "$HOSTNAME"

echo "[3] Updating /etc/hosts..."
sudo sed -i "s/^127.0.0.1.*/127.0.0.1 localhost $HOSTNAME/" /etc/hosts
sudo sed -i "s/^::1.*/::1 localhost $HOSTNAME/" /etc/hosts

echo "[4] Starting Avahi daemon..."
sudo systemctl restart avahi-daemon
sudo systemctl enable avahi-daemon

echo "[5] Testing mDNS..."
sleep 2

# Try to resolve from local machine
if getent hosts "$HOSTNAME.local" > /dev/null 2>&1; then
  RESOLVED_IP=$(getent hosts "$HOSTNAME.local" | awk '{print $1}')
  echo "✓ mDNS working: $HOSTNAME.local resolves to $RESOLVED_IP"
else
  echo "⚠ mDNS not yet registered (may take 30 seconds)"
  echo "  From other machines on network, access via:"
  echo "    ssh cpu_user@$HOSTNAME.local"
fi

echo ""
echo "✓ Setup complete!"
echo ""
echo "Now access CPU by hostname:"
echo "  ssh cpu_user@$HOSTNAME.local"
echo "  ssh cpu_user@$HOSTNAME (on some networks)"
echo ""
echo "Or configure in ~/.ssh/config:"
echo "  Host astroquant"
echo "    HostName $HOSTNAME.local"
echo "    User cpu_user"
echo ""
