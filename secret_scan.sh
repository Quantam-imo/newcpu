#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Running tracked-file secret scan...${NC}"

# High-confidence patterns only to keep false positives low.
PATTERN='(db-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{35}|ghp_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY-----)'

MATCHES=$(git grep -nE "$PATTERN" -- . \
  ':(exclude).venv/*' \
  ':(exclude)secret_scan.sh' \
  ':(exclude)*.md' || true)

if [[ -n "$MATCHES" ]]; then
  echo -e "${RED}Secret scan detected potential credential material:${NC}"
  echo "$MATCHES"
  exit 1
fi

echo -e "${GREEN}Secret scan passed (no high-confidence secrets detected).${NC}"
