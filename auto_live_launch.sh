#!/bin/bash
# Master automation script for AstroQuant live trading deployment
# Usage: bash auto_live_launch.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PATH="$PROJECT_ROOT/.venv"
DEPLOY_SCRIPT="$PROJECT_ROOT/deploy.sh"
LAUNCH_SCRIPT="$PROJECT_ROOT/LIVE_LAUNCH.sh"
LOG_FILE="$PROJECT_ROOT/logs/auto_live_launch.log"

function log {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "Starting AstroQuant CPU and live trading automation."

# 1. Activate Python environment
if [ -d "$VENV_PATH" ]; then
    log "Activating Python environment."
    source "$VENV_PATH/bin/activate"
else
    log "ERROR: Python virtual environment not found at $VENV_PATH"
    exit 1
fi

# 2. Deploy project
if [ -x "$DEPLOY_SCRIPT" ]; then
    log "Running deployment script."
    bash "$DEPLOY_SCRIPT"
else
    log "ERROR: Deployment script not found or not executable: $DEPLOY_SCRIPT"
    exit 1
fi

# 3. Launch live trading
if [ -x "$LAUNCH_SCRIPT" ]; then
    log "Launching live trading."
    bash "$LAUNCH_SCRIPT"
else
    log "ERROR: Live launch script not found or not executable: $LAUNCH_SCRIPT"
    exit 1
fi

log "AstroQuant live trading automation complete. Monitor logs for status."
