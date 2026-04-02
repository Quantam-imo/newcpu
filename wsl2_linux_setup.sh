#!/bin/bash
# ============================================================
#  AstroQuant WSL2 Linux Setup Script
#  Runs INSIDE WSL2 Ubuntu — do NOT run on Windows directly.
#
#  Usage (inside WSL2 Ubuntu terminal):
#    bash wsl2_linux_setup.sh
#
#  Or run automatically by windows_wsl2_setup.ps1
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
GITHUB_REPO="https://github.com/Quantam-imo/newcpu.git"
INSTALL_DIR="/home/${USER}/newcpu"
LOG_DIR="$INSTALL_DIR/data/logs"

echo ""
echo "============================================================"
echo "  AstroQuant WSL2 Linux Setup"
echo "  Install dir: $INSTALL_DIR"
echo "============================================================"
echo ""

# ── 1. System packages ──────────────────────────────────────
echo "[1/7] Installing system packages..."
sudo apt-get update -qq 2>/dev/null
sudo apt-get install -y -qq \
    python3 python3-pip python3-venv \
    redis-server git curl wget unzip cron \
    build-essential libssl-dev libffi-dev \
    libpq-dev libjpeg-dev zlib1g-dev \
    xvfb x11vnc x11-utils \
    2>/dev/null
echo "  [OK] System packages installed"

# Ensure cron service is enabled where systemd is active.
sudo systemctl enable cron 2>/dev/null || true

# ── 2. Google Chrome ────────────────────────────────────────
echo "[2/7] Checking Google Chrome..."
if ! command -v google-chrome &>/dev/null && ! command -v google-chrome-stable &>/dev/null; then
    echo "  --> Downloading Google Chrome..."
    curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb 2>/dev/null
    sudo dpkg -i /tmp/chrome.deb 2>/dev/null || sudo apt-get install -f -y -qq 2>/dev/null
    rm -f /tmp/chrome.deb
    echo "  [OK] Google Chrome installed"
else
    echo "  [OK] Google Chrome already installed: $(google-chrome --version 2>/dev/null || google-chrome-stable --version 2>/dev/null)"
fi

# ── 3. Clone / update project ───────────────────────────────
echo "[3/7] Cloning AstroQuant project..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  Already exists — pulling latest..."
    cd "$INSTALL_DIR"
    git pull --ff-only 2>/dev/null || git fetch origin && git reset --hard origin/main
else
    git clone "$GITHUB_REPO" "$INSTALL_DIR"
fi
mkdir -p "$LOG_DIR"
echo "  [OK] Project ready at $INSTALL_DIR"

# ── 4. Python venv ──────────────────────────────────────────
echo "[4/7] Setting up Python virtual environment..."
cd "$INSTALL_DIR"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip -q
echo "  --> Installing Python packages (may take a few minutes)..."
pip install -r requirements.txt -q
# Install Playwright browser for broker automation
python -m playwright install chromium 2>/dev/null || true
echo "  [OK] Python environment ready ($(python --version))"

# ── 5. WSL2 systemd + boot config ───────────────────────────
echo "[5/7] Configuring WSL2 boot..."
sudo tee /etc/wsl.conf > /dev/null <<'WSLCONF'
[boot]
systemd=true
command=/bin/bash /home/astroquant/newcpu/non_systemd_autostart_bootstrap.sh >> /home/astroquant/newcpu/data/logs/wsl_boot.log 2>&1

[automount]
enabled = true
options = "metadata"
WSLCONF

# Replace hardcoded user in wsl.conf with current actual user
ACTUAL_HOME="/home/$USER"
sudo sed -i "s|/home/astroquant|$ACTUAL_HOME|g" /etc/wsl.conf
echo "  [OK] /etc/wsl.conf written (systemd + boot command)"

# ── 6. Script permissions + autostart hook ──────────────────
echo "[6/7] Registering autostart..."
cd "$INSTALL_DIR"
chmod +x *.sh 2>/dev/null || true

# Install shell login fallback (works even without systemd)
AQ_WORKSPACE="$INSTALL_DIR" bash "$INSTALL_DIR/enable_boot_autostart.sh" || true
echo "  [OK] Autostart hooks installed in ~/.bashrc and ~/.profile"

# ── 7. .env check ─────────────────────────────────────────
echo "[7/7] Checking configuration..."
if [ -f "$INSTALL_DIR/.env" ]; then
    KEY_COUNT=$(grep -c "=" "$INSTALL_DIR/.env" 2>/dev/null || echo 0)
    echo "  [OK] .env present ($KEY_COUNT config keys)"
else
    # Try importing from Windows Desktop
    WIN_USER=$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r\n' || echo "")
    WIN_ENV_PATH="/mnt/c/Users/$WIN_USER/Desktop/astroquant_env.txt"
    if [ -f "$WIN_ENV_PATH" ]; then
        cp "$WIN_ENV_PATH" "$INSTALL_DIR/.env"
        echo "  [OK] .env imported from Windows Desktop (C:\\Users\\$WIN_USER\\Desktop\\astroquant_env.txt)"
    else
        echo "  [WARN] .env not found — project will start but API keys not configured."
        echo "         Copy your .env file to: $INSTALL_DIR/.env"
        echo "         Or place astroquant_env.txt on Windows Desktop and re-run this script."
    fi
fi

# ── Done ────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  WSL2 Linux Setup COMPLETE"
echo "============================================================"
echo ""
echo "  NEXT STEPS:"
echo ""
echo "  1. Restart WSL2 to activate systemd (run in PowerShell):"
echo "       wsl --shutdown"
echo ""
echo "  2. Reopen Ubuntu / restart Windows"
echo ""
echo "  3. AstroQuant will start automatically. Verify with:"
echo "       curl http://localhost:8000/status"
echo ""
echo "  Manual start anytime:"
echo "       cd $INSTALL_DIR && bash npvps_auto_start.sh"
echo ""
echo "  Logs:"
echo "       tail -f $LOG_DIR/fullstack.log"
echo ""
