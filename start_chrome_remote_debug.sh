#!/bin/bash
# CHROME TEMPORARILY DISABLED - high CPU causing VS Code instability
# Restore with: cp start_chrome_remote_debug.sh.bak start_chrome_remote_debug.sh
echo "[$(date)] Chrome launch suppressed to reduce CPU/memory load" >> /workspaces/newcpu/data/logs/chrome.log
exit 0
