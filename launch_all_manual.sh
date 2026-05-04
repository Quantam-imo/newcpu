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
    nohup bash /workspaces/newcpu/start_cloudflare_tunnel.sh > logs/cloudflare_tunnel_launcher.log 2>&1 &
    echo "Cloudflare tunnel manager started."

    # Wait briefly for tunnel URL publication and send a forced link alert.
    for i in {1..20}; do
        if [ -s /workspaces/newcpu/data/tunnel_url.txt ] && grep -Eq 'https://.*(trycloudflare|cloudflare)' /workspaces/newcpu/data/tunnel_url.txt; then
            break
        fi
        sleep 1
    done

    if [ -x /workspaces/newcpu/send_telegram_alert.sh ]; then
        FORCE_ALERT=1 bash /workspaces/newcpu/send_telegram_alert.sh launch-all-manual || true
    fi
fi

# Start MT5 bridge sync daemon (receives candles POSTed from Windows MT5 machine)
if [ -x /workspaces/newcpu/start_mt5_bridge_sync.sh ]; then
    echo "Starting MT5 bridge sync daemon..."
    bash /workspaces/newcpu/start_mt5_bridge_sync.sh > /workspaces/newcpu/logs/mt5_bridge_sync.log 2>&1 || true
fi

echo "All AstroQuant services launched. Open http://localhost:8000 in your browser."
