#!/bin/bash
# Automated Databento API Key Scanner for AstroQuant
# Scans for hardcoded Databento API keys and key-like strings in the codebase
# Usage: ./scan_databento_keys.sh

PATTERNS=(
    'DATABENTO_API_KEY'
    'api_key'
    'databento_key'
    'db-[a-zA-Z0-9]\{32\}'
    'sk_live_[a-zA-Z0-9]\{64\}'
    'db-[a-zA-Z0-9]+'
    'databento'
)

FOUND=0
for pattern in "${PATTERNS[@]}"; do
    echo "Scanning for pattern: $pattern"
    grep -rIn --exclude-dir="__pycache__" --exclude="*.pyc" --exclude="*.log" --exclude="*.sqlite3" --exclude="scan_databento_keys.sh" "$pattern" .
    if [ $? -eq 0 ]; then
        FOUND=1
    fi
done

if [ $FOUND -eq 0 ]; then
    echo "No Databento API keys or key-like strings found. Codebase is clean."
else
    echo "WARNING: Potential Databento API key(s) or key-like strings found above. Review and redact as needed."
    exit 1
fi
