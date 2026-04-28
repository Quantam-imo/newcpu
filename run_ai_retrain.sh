#!/bin/bash
# AstroQuant scheduled AI retraining runner
# - lock-protected (no overlapping runs)
# - logs to data/logs
# - runs full multi-timeframe retrain pipeline

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
LAB_DIR="$WORKSPACE/market-causality-lab"
VENV_ACTIVATE="$WORKSPACE/.venv/bin/activate"
LOG_DIR="$WORKSPACE/data/logs"
LOCK_FILE="/tmp/astroquant_ai_retrain.lock"
SUCCESS_MARKER="$LOG_DIR/ai_retrain_last_success.json"
NODE_WAVE_MARKER="$LOG_DIR/ai_node_wave_last_success.json"
API_BASE="${AQ_API_BASE:-http://localhost:8000}"
NODE_WAVE_TFS="${AQ_NODE_WAVE_TFS:-1d,4h,1h,15m,5m}"

mkdir -p "$LOG_DIR"

log() {
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  echo "[$ts] $*"
}

if [[ ! -d "$LAB_DIR" ]]; then
  log "ERROR: missing lab directory: $LAB_DIR"
  exit 1
fi

if [[ ! -f "$VENV_ACTIVATE" ]]; then
  log "ERROR: missing venv activate script: $VENV_ACTIVATE"
  exit 1
fi

if [[ ! -f "$LAB_DIR/train_all_complete.sh" ]]; then
  log "ERROR: missing train script: $LAB_DIR/train_all_complete.sh"
  exit 1
fi

# Single-run lock: skip if another retrain is active.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "Another AI retrain is already running. Skipping this schedule tick."
  exit 0
fi

echo $$ 1>&9

RUN_TS="$(date '+%Y%m%d_%H%M%S')"
OUT_LOG="$LOG_DIR/ai_retrain_${RUN_TS}.log"

log "Starting scheduled AI retrain"
log "Log: $OUT_LOG"

cd "$LAB_DIR"
source "$VENV_ACTIVATE"

# Lower IO/CPU priority a bit so live services remain responsive.
if command -v ionice >/dev/null 2>&1; then
  ionice -c2 -n7 nice -n 10 bash train_all_complete.sh 2>&1 | tee "$OUT_LOG"
else
  nice -n 10 bash train_all_complete.sh 2>&1 | tee "$OUT_LOG"
fi

# Mark run as successful only if final 1m timeframe completed and trained.
one_min_seen=0
one_min_trained=0
if grep -q 'Training: 1-Minute (1m)' "$OUT_LOG"; then
  one_min_seen=1
fi
one_min_trained="$(python - <<'PY' "$OUT_LOG"
import json
import sys
from pathlib import Path

log_path = Path(sys.argv[1])
text = log_path.read_text(encoding="utf-8", errors="ignore")
start = text.rfind('{\n  "trained_any"')
if start < 0:
    print(0)
    raise SystemExit(0)

try:
    payload = json.loads(text[start:])
except json.JSONDecodeError:
    print(0)
    raise SystemExit(0)

results = payload.get("results") or []
matched = any(
    str(item.get("timeframe") or "").strip().lower() == "1m"
    and bool(item.get("trained"))
    for item in results
    if isinstance(item, dict)
)
print(1 if matched else 0)
PY
)"

if [[ "$one_min_seen" -eq 1 && "$one_min_trained" -eq 1 ]]; then
  latest_version=""
  if [[ -f "$LAB_DIR/data/ai_models/latest.json" ]]; then
    latest_version="$(grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$LAB_DIR/data/ai_models/latest.json" | head -1 | cut -d '"' -f4 || true)"
  fi

  {
    echo "{"
    echo "  \"status\": \"ok\"," 
    echo "  \"completed_at_utc\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"," 
    echo "  \"log_file\": \"$OUT_LOG\"," 
    echo "  \"contains_1m\": true,"
    echo "  \"latest_version\": \"$latest_version\""
    echo "}"
  } > "$SUCCESS_MARKER"
  log "Full-cycle success marker written: $SUCCESS_MARKER"
else
  log "WARNING: run finished without confirmed 1m success marker"
fi

# Optional: keep MCL node/wave learning in sync with timeframe-aware calibration.
if command -v curl >/dev/null 2>&1; then
  if curl --max-time 8 -fsS "$API_BASE/market_causality/status" >/dev/null 2>&1; then
    log "Starting node/wave post-training calibration via API: $API_BASE"
    node_wave_rows=""

    # Resolve expired pending predictions first so training uses the freshest outcomes.
    RESOLVE_OUT="$(curl --max-time 25 -fsS -X POST "$API_BASE/market_causality/auto_resolve_pending?symbol=XAUUSD" || true)"
    if [[ -n "$RESOLVE_OUT" ]]; then
      resolved_count="$(echo "$RESOLVE_OUT" | grep -o '"resolved_count"[[:space:]]*:[[:space:]]*[0-9]\+' | head -1 | grep -o '[0-9]\+' || true)"
      log "auto_resolve_pending resolved_count=${resolved_count:-0}"
    else
      log "WARNING: auto_resolve_pending returned empty response"
    fi

    IFS=',' read -r -a _tf_arr <<< "$NODE_WAVE_TFS"
    for _tf in "${_tf_arr[@]}"; do
      _tf="$(echo "$_tf" | xargs)"
      [[ -z "$_tf" ]] && continue
      TRAIN_OUT="$(curl --max-time 240 -fsS -X POST "$API_BASE/market_causality/train_node_wave_model?timeframe=${_tf}" -H "Content-Type: application/json" -d '{"dry_run": false}' || true)"
      if [[ -n "$TRAIN_OUT" ]]; then
        _acc="$(echo "$TRAIN_OUT" | grep -o '"overall_accuracy"[[:space:]]*:[[:space:]]*[0-9.]*' | tail -1 | cut -d: -f2 | tr -d ' ' || true)"
        _out="$(echo "$TRAIN_OUT" | grep -o '"total_outcomes"[[:space:]]*:[[:space:]]*[0-9]\+' | tail -1 | grep -o '[0-9]\+' || true)"
        _batch="$(echo "$TRAIN_OUT" | grep -o '"batch_accuracy_pct"[[:space:]]*:[[:space:]]*[0-9.]*' | head -1 | cut -d: -f2 | tr -d ' ' || true)"
        log "node_wave tf=$_tf overall_accuracy=${_acc:-n/a} total_outcomes=${_out:-0} batch_accuracy_pct=${_batch:-n/a}"
        _acc_json="${_acc:-null}"
        _batch_json="${_batch:-null}"
        _out_json="${_out:-0}"
        node_wave_rows+="{\"timeframe\":\"$_tf\",\"overall_accuracy\":${_acc_json},\"total_outcomes\":${_out_json},\"batch_accuracy_pct\":${_batch_json}},"
      else
        log "WARNING: node_wave training call failed for timeframe=$_tf"
      fi
    done

    node_wave_rows="${node_wave_rows%,}"
    {
      echo "{" 
      echo "  \"status\": \"ok\"," 
      echo "  \"completed_at_utc\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"," 
      echo "  \"api_base\": \"$API_BASE\"," 
      echo "  \"resolved_count\": ${resolved_count:-0}," 
      echo "  \"timeframes\": [${node_wave_rows}]" 
      echo "}" 
    } > "$NODE_WAVE_MARKER"
    log "Node/wave success marker written: $NODE_WAVE_MARKER"
  else
    log "WARNING: API unavailable at $API_BASE; skipping node/wave post-training calibration"
  fi
else
  log "WARNING: curl not found; skipping node/wave post-training calibration"
fi

log "Scheduled AI retrain completed"
