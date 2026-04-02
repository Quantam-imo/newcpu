#!/bin/bash
# Setup script for AstroQuant Trading Bot systemd services
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
SERVICE_USER="${AQ_SERVICE_USER:-${SUDO_USER:-$USER}}"
chmod +x "$WORKSPACE/watchdog_autorecover.sh" 2>/dev/null || true

install_service_template() {
  local template_name="$1"
  sudo sed \
    -e "s|__WORKSPACE__|$WORKSPACE|g" \
    -e "s|__SERVICE_USER__|$SERVICE_USER|g" \
    "$WORKSPACE/$template_name" > "/tmp/$template_name"
  sudo mv "/tmp/$template_name" "/etc/systemd/system/$template_name"
}


# Check if systemd is available
if pidof systemd > /dev/null; then
  # Copy service files to systemd directory
  install_service_template astroquant_tradingbot.service
  install_service_template astroquant_watchdog.service
  install_service_template astroquant_watchdog.timer

  # Reload systemd to recognize new services
  sudo systemctl daemon-reload

  # Enable services to start on boot
  sudo systemctl enable astroquant_tradingbot.service
  sudo systemctl enable astroquant_watchdog.timer
  echo "Enabled: astroquant_tradingbot.service + astroquant_watchdog.timer"
else
  echo "systemd is not available. Using service commands and manual steps."
  # Start redis-server if available
  if command -v service > /dev/null; then
    sudo service redis-server start || echo "redis-server could not be started."
  fi
  # Start backend manually if not running
  if ! pgrep -f "uvicorn.*astroquant.backend.main:app" > /dev/null; then
    if [ -f "$WORKSPACE/.venv/bin/activate" ]; then
      source "$WORKSPACE/.venv/bin/activate"
      export PYTHONPATH="$WORKSPACE"
      nohup uvicorn astroquant.backend.main:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn.log 2>&1 &
      echo "Uvicorn backend started in fallback mode."
    fi
  fi
  # Advise user to open frontend manually
  echo "Please open http://localhost:8000 in your browser to access the frontend."
  echo "If Chrome/Chromium is not installed, install it for browser automation."
fi

# Fallback: Start backend with uvicorn if systemd is not available
if ! pgrep -f "uvicorn.*astroquant.backend.main:app" > /dev/null; then
  if [ -f "$WORKSPACE/.venv/bin/activate" ]; then
    source "$WORKSPACE/.venv/bin/activate"
    export PYTHONPATH="$WORKSPACE"
    nohup uvicorn astroquant.backend.main:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn.log 2>&1 &
    echo "Uvicorn backend started in fallback mode."
  fi
fi

echo "AstroQuant autostart configured with single startup authority."
