#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "error: ${PYTHON_BIN} not found or not executable"
  echo "create the virtual environment first, then install requirements"
  exit 1
fi

"${PYTHON_BIN}" -m pytest -q \
  "${ROOT_DIR}/test_market_causality_router.py" \
  "${ROOT_DIR}/test_market_causality_panel_contract.py" \
  "${ROOT_DIR}/test_market_causality_25y_contract.py" \
  "${ROOT_DIR}/test_market_causality_e2e_smoke.py"
