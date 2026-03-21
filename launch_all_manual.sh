#!/bin/bash
# Robust AstroQuant manual launch script for non-systemd environments
set -euo pipefail

cd /workspaces/newcpu

# Activate Python virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Start Redis if available
if command -v redis-server > /dev/null; then
    nohup redis-server > logs/redis.log 2>&1 &
    echo "Redis started."
fi

export PYTHONPATH=/workspaces/newcpu
# Start backend (FastAPI)
nohup uvicorn astroquant.backend.main:app --host 0.0.0.0 --port 8000 > logs/backend.log 2>&1 &
echo "Backend started."

# Start live sync engine
nohup python3 start_live_sync.py > logs/livesync.log 2>&1 &
echo "Live sync engine started."

# Start orchestrator
nohup python3 start_astroquant.py > logs/orchestrator.log 2>&1 &
echo "Orchestrator started."

# Start Celery worker
nohup .venv/bin/celery -A astroquant.backend.tasks.celery_worker worker --loglevel=info > logs/celery.log 2>&1 &
echo "Celery worker started."

# Start calibration (if needed)
nohup bash astroquant_calibrate.service > logs/calibrate.log 2>&1 &
echo "Calibration started."

# Start health check (if needed)
nohup bash health_check.sh > logs/healthcheck.log 2>&1 &
echo "Health check started."

# Start Chrome with remote debugging (if available)
if command -v google-chrome > /dev/null; then
    nohup google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-profile --no-sandbox --disable-gpu --disable-software-rasterizer --disable-dev-shm-usage --disable-extensions --disable-background-networking --disable-sync --disable-translate --disable-default-apps --disable-popup-blocking --disable-background-timer-throttling --disable-renderer-backgrounding --disable-device-discovery-notifications --disable-features=TranslateUI --window-size=1280,900 https://manager.maven.markets/app/trade > logs/chrome.log 2>&1 &
    echo "Chrome with remote debugging started."
fi

# Start Cloudflare tunnel (if available)
if command -v cloudflared > /dev/null; then
    nohup cloudflared tunnel --url http://localhost:8000 > logs/cloudflared.log 2>&1 &
    echo "Cloudflare tunnel started."
fi

echo "All AstroQuant services launched. Open http://localhost:8000 in your browser."
