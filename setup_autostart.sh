#!/bin/bash
# Setup script for AstroQuant Trading Bot systemd services
set -e


# Check if systemd is available
if pidof systemd > /dev/null; then
  # Copy service files to systemd directory
  sudo cp /workspaces/newcpu/astroquant_tradingbot.service /etc/systemd/system/
  sudo cp /workspaces/newcpu/cloudflared_tunnel.service /etc/systemd/system/
  sudo cp /workspaces/newcpu/chrome_remote_debug.service /etc/systemd/system/

  # Reload systemd to recognize new services
  sudo systemctl daemon-reload

  # Enable services to start on boot
  sudo systemctl enable astroquant_tradingbot.service
  sudo systemctl enable cloudflared_tunnel.service
  sudo systemctl enable chrome_remote_debug.service

  # Start Chrome with remote debugging (container/WSL compatible)
  /workspaces/newcpu/start_chrome_remote_debug.sh
else
  echo "systemd is not available. Using service commands and manual steps."
  # Start redis-server if available
  if command -v service > /dev/null; then
    sudo service redis-server start || echo "redis-server could not be started."
  fi
  # Start backend manually if not running
  if ! pgrep -f "uvicorn.*astroquant.backend.main:app" > /dev/null; then
    if [ -f "/workspaces/newcpu/.venv/bin/activate" ]; then
      source /workspaces/newcpu/.venv/bin/activate
      export PYTHONPATH=/workspaces/newcpu
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
  if [ -f "/workspaces/newcpu/.venv/bin/activate" ]; then
    source /workspaces/newcpu/.venv/bin/activate
    export PYTHONPATH=/workspaces/newcpu
    nohup uvicorn astroquant.backend.main:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn.log 2>&1 &
    echo "Uvicorn backend started in fallback mode."
  fi
fi

echo "AstroQuant Trading Bot and Cloudflare Tunnel are set to start automatically on CPU boot."
