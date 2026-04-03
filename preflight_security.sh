#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: Python venv not found at $PYTHON_BIN"
  exit 1
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS_COUNT=0
FAIL_COUNT=0

pass() {
  echo -e "${GREEN}PASS${NC}: $*"
  PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
  echo -e "${RED}FAIL${NC}: $*"
  FAIL_COUNT=$((FAIL_COUNT + 1))
}

info() {
  echo -e "${BLUE}INFO${NC}: $*"
}

run_pytest_gate() {
  local tests=("$@")
  set +e
  local output
  output=$("$PYTHON_BIN" -m pytest -q "${tests[@]}" 2>&1)
  local code=$?
  set -e
  if [[ $code -eq 0 ]]; then
    pass "Pytest gate passed: ${tests[*]}"
  else
    fail "Pytest gate failed: ${tests[*]}"
    echo "$output"
  fi
}

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

wait_for_http() {
  local url="$1"
  local tries=0
  while [[ $tries -lt 40 ]]; do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    tries=$((tries + 1))
    sleep 0.25
  done
  return 1
}

start_server_bg() {
  local env_mode="$1"
  local port="$2"
  local extra_env="$3"

  local cmd="cd '$ROOT_DIR' && source '$ROOT_DIR/.venv/bin/activate' && APP_ENV='$env_mode' $extra_env uvicorn astroquant.backend.main:app --host 127.0.0.1 --port '$port'"
  bash -lc "$cmd" >/tmp/preflight_security_server.log 2>&1 &
  SERVER_PID=$!

  if wait_for_http "http://127.0.0.1:${port}/health"; then
    return 0
  fi

  if kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  return 1
}

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  AstroQuant Security Preflight${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# 0) Fast unit-test gate for market-causality adapter/fallback behavior
info "Running market-causality unit-test gate"
run_pytest_gate \
  "$ROOT_DIR/test_market_causality_router.py" \
  "$ROOT_DIR/test_market_causality_fallback.py"

# 1) Production must block insecure startup
info "Checking production startup guard blocks insecure config"
set +e
BLOCK_OUTPUT=$(bash -lc "cd '$ROOT_DIR' && source '$ROOT_DIR/.venv/bin/activate' && APP_ENV=production uvicorn astroquant.backend.main:app --host 127.0.0.1 --port 8020" 2>&1)
BLOCK_EXIT=$?
set -e
if [[ $BLOCK_EXIT -ne 0 ]] && echo "$BLOCK_OUTPUT" | grep -q "Production startup blocked:"; then
  pass "Production startup blocked when secure secrets are missing"
else
  fail "Production startup guard did not block insecure configuration"
fi

# 2) Dev mode should not mount admin control routes by default
info "Checking admin control routes are not mounted in insecure dev mode"
SERVER_PID=""
if start_server_bg "dev" "8011" ""; then
  DEV_CODE=$(curl -s -o /tmp/preflight_admin_dev.out -w "%{http_code}" http://127.0.0.1:8011/admin/control/state)
  if [[ "$DEV_CODE" == "404" ]]; then
    pass "Admin control routes are not mounted in insecure dev mode"
  else
    fail "Expected 404 for /admin/control/state in insecure dev mode, got $DEV_CODE"
  fi
else
  fail "Could not start dev server for route exposure check"
fi
cleanup
SERVER_PID=""

# 3) Production with secure values should start and pass auth checks
info "Checking secure production startup and admin endpoint auth behavior"
SECURE_ENV="ADMIN_API_TOKEN=securetoken MENTOR_ADMIN_PASSWORD=securementor DATABENTO_API_KEY=test"
if start_server_bg "production" "8010" "$SECURE_ENV"; then
  STATUS_JSON=$(curl -fsS http://127.0.0.1:8010/status/security)

  STATUS_EVAL=$(STATUS_JSON="$STATUS_JSON" "$PYTHON_BIN" - <<'PY'
import json, os
payload = json.loads(os.environ.get("STATUS_JSON", "{}"))
ok = (
    payload.get("running_in_production") is True
    and payload.get("production_ready") is True
    and payload.get("startup_blocked_now") is False
    and payload.get("admin_control_routes_enabled") is True
)
print("OK" if ok else "BAD")
PY
)

  if [[ "$STATUS_EVAL" == "OK" ]]; then
    pass "Security posture endpoint reports production-ready secure state"
  else
    fail "Security posture endpoint did not report expected secure production state"
  fi

  UNAUTH_CODE=$(curl -s -o /tmp/preflight_admin_unauth.out -w "%{http_code}" http://127.0.0.1:8010/admin/control/state)
  AUTH_CODE=$(curl -s -o /tmp/preflight_admin_auth.out -w "%{http_code}" -H "x-admin-token: securetoken" -H "x-admin-role: ADMIN" http://127.0.0.1:8010/admin/control/state)

  if [[ "$UNAUTH_CODE" == "401" ]]; then
    pass "Admin control endpoint rejects unauthenticated access"
  else
    fail "Expected 401 for unauthenticated admin access, got $UNAUTH_CODE"
  fi

  if [[ "$AUTH_CODE" == "200" ]]; then
    pass "Admin control endpoint accepts authenticated access"
  else
    fail "Expected 200 for authenticated admin access, got $AUTH_CODE"
  fi
else
  fail "Could not start production server with secure configuration"
fi

cleanup
SERVER_PID=""

echo ""
echo "Summary: $PASS_COUNT passed, $FAIL_COUNT failed"
if [[ $FAIL_COUNT -gt 0 ]]; then
  echo -e "${RED}SECURITY PREFLIGHT: BLOCKED${NC}"
  exit 1
fi

echo -e "${GREEN}SECURITY PREFLIGHT: READY${NC}"
