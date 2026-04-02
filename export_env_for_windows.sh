#!/bin/bash
# ============================================================
#  Export .env from Codespaces → file you copy to Windows
#  Run this in Codespaces terminal:
#    bash export_env_for_windows.sh
#  Then download the output file and place it on Windows Desktop
#  as: C:\Users\<you>\Desktop\astroquant_env.txt
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
ENV_FILE="$WORKSPACE/.env"
OUTPUT_FILE="$WORKSPACE/astroquant_env_EXPORT.txt"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env file not found at $ENV_FILE"
    exit 1
fi

# Copy .env to an export file
cp "$ENV_FILE" "$OUTPUT_FILE"

echo ""
echo "============================================================"
echo "  .env exported for Windows transfer"
echo "============================================================"
echo ""
echo "  Output file: $OUTPUT_FILE"
echo ""
echo "  HOW TO TRANSFER TO WINDOWS:"
echo ""
echo "  Option 1 — VS Code (easiest):"
echo "    Right-click 'astroquant_env_EXPORT.txt' in VS Code Explorer"
echo "    → 'Download...'"
echo "    → Save to Desktop as 'astroquant_env.txt'"
echo ""
echo "  Option 2 — Browser download URL:"
echo "    Open the file in VS Code and use File > Download"
echo ""
echo "  After download, place on Windows Desktop as:"
echo "    C:\\Users\\<YourName>\\Desktop\\astroquant_env.txt"
echo ""
echo "  The windows_wsl2_setup.ps1 script will auto-inject it into WSL2."
echo ""
echo "  SECURITY NOTE: This file contains API keys and passwords."
echo "  Delete it from Downloads/Desktop after WSL2 setup is complete."
echo ""
