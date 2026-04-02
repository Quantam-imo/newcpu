#!/bin/bash
# Setup SSH key authentication with NPVPS CPU
# Run this once before using connect_cpu.sh

set -e

echo "╔════════════════════════════════════════════════════════╗"
echo "║  SSH Key Setup for NPVPS CPU Access                    ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

SSH_KEY_PATH="${HOME}/.ssh/id_rsa"
SSH_PUB_PATH="${HOME}/.ssh/id_rsa.pub"

# Step 1: Generate SSH key if needed
if [ ! -f "$SSH_KEY_PATH" ]; then
  echo "[1] Generating SSH key pair..."
  mkdir -p "${HOME}/.ssh"
  ssh-keygen -t rsa -b 4096 -f "$SSH_KEY_PATH" -N "" -C "astroquant@$(hostname)"
  chmod 600 "$SSH_KEY_PATH"
  chmod 644 "$SSH_PUB_PATH"
  echo "✓ SSH key generated: $SSH_KEY_PATH"
else
  echo "✓ SSH key already exists: $SSH_KEY_PATH"
fi

echo ""
echo "[2] Your public key:"
echo "════════════════════════════════════════════════════════"
cat "$SSH_PUB_PATH"
echo "════════════════════════════════════════════════════════"
echo ""

# Step 2: Instructions
echo "[3] Setup on NPVPS CPU:"
echo ""
echo "  SSH into your CPU:"
echo "    ssh cpu_user@CPU_IP"
echo ""
echo "  Add your public key to authorized_keys:"
echo "    mkdir -p ~/.ssh"
echo "    chmod 700 ~/.ssh"
echo "    echo '$(cat $SSH_PUB_PATH)' >> ~/.ssh/authorized_keys"
echo "    chmod 600 ~/.ssh/authorized_keys"
echo ""
echo "  Test connection:"
echo "    ssh cpu_user@CPU_IP"
echo ""

# Step 3: Test connection
echo "[4] Testing SSH connection..."
echo ""
echo "Enter your CPU IP address:"
read -p "  CPU_IP: " CPU_IP

if [ -z "$CPU_IP" ]; then
  echo "Skipped connection test"
  exit 0
fi

echo "Enter your CPU username (default: cpu):"
read -p "  CPU_USER [cpu]: " CPU_USER
CPU_USER="${CPU_USER:-cpu}"

echo "Enter SSH port (default: 22):"
read -p "  SSH_PORT [22]: " SSH_PORT
SSH_PORT="${SSH_PORT:-22}"

echo ""
echo "Testing connection to $CPU_USER@$CPU_IP:$SSH_PORT..."

if timeout 5 ssh \
  -p "$SSH_PORT" \
  -i "$SSH_KEY_PATH" \
  -o ConnectTimeout=5 \
  -o StrictHostKeyChecking=accept-new \
  "$CPU_USER@$CPU_IP" "echo 'SUCCESS'" 2>/dev/null; then
  
  echo "✓ SSH connection successful!"
  echo ""
  echo "Update your connect_cpu.sh script:"
  echo "  CPU_USER=\"$CPU_USER\""
  echo "  CPU_IP=\"$CPU_IP\""
  echo "  CPU_SSH_PORT=\"$SSH_PORT\""
  echo ""
else
  echo "✗ SSH connection failed"
  echo ""
  echo "Troubleshooting:"
  echo "  1. Verify CPU IP: ping $CPU_IP"
  echo "  2. Check SSH is running on CPU: sudo systemctl status ssh"
  echo "  3. Confirm public key is in /home/$CPU_USER/.ssh/authorized_keys"
  echo "  4. Try password auth first: ssh -p $SSH_PORT $CPU_USER@$CPU_IP"
  exit 1
fi

echo ""
echo "Setup complete! Now run:"
echo "  ./connect_cpu.sh"
