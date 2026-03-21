#!/bin/bash
# Auto-start script for AstroQuant full stack

# Activate Python environment
source /workspaces/newcpu/.venv/bin/activate

# Start Redis (if not already running)
if ! pgrep -x redis-server > /dev/null; then
  redis-server &
  echo "Redis started."
else
  echo "Redis already running."
fi

# Start FastAPI backend with PM2
pm2 start "bash -c 'export PYTHONPATH=/workspaces/newcpu && uvicorn astroquant.backend.main:app --host 0.0.0.0 --port 8000 --reload'" --name astroquant-backend

# Start Celery worker with PM2
pm2 start "celery -A astroquant.backend.tasks.celery_worker worker --loglevel=info" --name astroquant-worker

# Start Signal Orchestrator with PM2
pm2 start start_astroquant.py --interpreter python3 --name astroquant-orchestrator

# Start Cloudflare tunnel with PM2
pm2 start "cloudflared tunnel --url http://localhost:8000" --name astroquant-tunnel

# Save PM2 process list and enable startup on boot
pm2 save
pm2 startup

echo "AstroQuant auto-start setup complete. All services are running under PM2."
