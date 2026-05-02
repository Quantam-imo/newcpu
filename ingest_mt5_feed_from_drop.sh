#!/bin/bash
# Ingest a newer MT5 feed CSV from drop locations into incoming path.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_FILE="${MT5_INGEST_DEST_FILE:-$ROOT_DIR/market-causality-lab/data/live/mt5/incoming/XAUUSD_feed_latest.csv}"
DROP_DIR="${MT5_INGEST_DROP_DIR:-$ROOT_DIR/transfer_out}"
TMP_DIR="${MT5_INGEST_TMP_DIR:-/tmp/mt5_ingest}"
GLOB_PATTERN="${MT5_INGEST_GLOB:-*XAUUSD*feed*.csv}"
ARCHIVE_GLOB="${MT5_INGEST_ARCHIVE_GLOB:-*.tar.gz}"
ONCE_LOG_PREFIX="[mt5-ingest]"
MAX_CONTENT_LAG_SEC="${MT5_INGEST_MAX_CONTENT_LAG_SEC:-900}"

mkdir -p "$(dirname "$DEST_FILE")"
mkdir -p "$TMP_DIR"

_tmp_extract="$TMP_DIR/XAUUSD_feed_latest.from_archive.csv"
rm -f "$_tmp_extract"

declare -a candidates=()

_parse_content_epoch() {
  local file_path="$1"
  python3 - <<'PY' "$file_path"
import csv, datetime, sys

path = sys.argv[1]
try:
  with open(path, 'r', encoding='utf-8', errors='ignore', newline='') as f:
    rows = list(csv.reader(f, delimiter=';'))
except Exception:
  print('')
  raise SystemExit(0)

if len(rows) < 2:
  print('')
  raise SystemExit(0)

last = rows[-1]
if not last:
  print('')
  raise SystemExit(0)

date_time_raw = (last[0] or '').strip().replace('.', '-')
if not date_time_raw:
  print('')
  raise SystemExit(0)

for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
  try:
    dt = datetime.datetime.strptime(date_time_raw, fmt).replace(tzinfo=datetime.timezone.utc)
    print(int(dt.timestamp()))
    raise SystemExit(0)
  except Exception:
    pass

print('')
PY
}

# 1) Directly provided drop file
if [[ -n "${MT5_DROP_FILE:-}" && -f "${MT5_DROP_FILE}" ]]; then
  candidates+=("${MT5_DROP_FILE}")
fi

# 2) CSVs in drop dir matching pattern
if [[ -d "$DROP_DIR" ]]; then
  while IFS= read -r -d '' f; do
    candidates+=("$f")
  done < <(find "$DROP_DIR" -maxdepth 2 -type f -name "$GLOB_PATTERN" -print0 2>/dev/null || true)

  # Also include canonical name if present
  if [[ -f "$DROP_DIR/XAUUSD_feed_latest.csv" ]]; then
    candidates+=("$DROP_DIR/XAUUSD_feed_latest.csv")
  fi
fi

# 3) Latest archive extraction candidate
latest_archive=""
if [[ -d "$DROP_DIR" ]]; then
  latest_archive="$(find "$DROP_DIR" -maxdepth 1 -type f -name "$ARCHIVE_GLOB" -printf '%T@|%p\n' 2>/dev/null | sort -nr | head -1 | cut -d'|' -f2-)"
fi
if [[ -n "$latest_archive" && -f "$latest_archive" ]]; then
  if tar -xOf "$latest_archive" "market-causality-lab/data/live/mt5/incoming/XAUUSD_feed_latest.csv" > "$_tmp_extract" 2>/dev/null; then
    if [[ -s "$_tmp_extract" ]]; then
      candidates+=("$_tmp_extract")
    fi
  fi
fi

if [[ ${#candidates[@]} -eq 0 ]]; then
  echo "$ONCE_LOG_PREFIX no candidates found (drop_dir=$DROP_DIR)"
  exit 1
fi

# Pick best candidate by freshest parsed candle time, with mtime as tie-breaker.
best_file=""
best_mtime=0
best_content_epoch=0
fresh_candidates=0
for c in "${candidates[@]}"; do
  [[ -f "$c" ]] || continue
  c_mtime="$(stat -c %Y "$c" 2>/dev/null || echo 0)"
  c_content_epoch="$(_parse_content_epoch "$c")"
  if [[ -n "$c_content_epoch" ]]; then
    now_epoch="$(date +%s)"
    c_content_lag="$((now_epoch - c_content_epoch))"
    if [[ "$c_content_lag" -le "$MAX_CONTENT_LAG_SEC" ]]; then
      fresh_candidates="$((fresh_candidates + 1))"
      newer_content=0
      newer_tiebreak_mtime=0
      if [[ "$c_content_epoch" -gt "$best_content_epoch" ]]; then
        newer_content=1
      fi
      if [[ "$c_content_epoch" -eq "$best_content_epoch" && "$c_mtime" -gt "$best_mtime" ]]; then
        newer_tiebreak_mtime=1
      fi
      if [[ "$newer_content" -eq 1 || "$newer_tiebreak_mtime" -eq 1 ]]; then
        best_content_epoch="$c_content_epoch"
        best_mtime="$c_mtime"
        best_file="$c"
      fi
    fi
  fi
done

if [[ -z "$best_file" ]]; then
  if [[ "$fresh_candidates" -eq 0 ]]; then
    echo "$ONCE_LOG_PREFIX no fresh candidates within max_content_lag_s=$MAX_CONTENT_LAG_SEC"
    exit 0
  fi
  echo "$ONCE_LOG_PREFIX candidates exist but none readable"
  exit 1
fi

dest_mtime=0
if [[ -f "$DEST_FILE" ]]; then
  dest_mtime="$(stat -c %Y "$DEST_FILE" 2>/dev/null || echo 0)"
fi

best_human="$(date -u -d "@$best_mtime" '+%Y-%m-%d %H:%M:%S UTC' 2>/dev/null || echo "$best_mtime")"
dest_human="$(date -u -d "@$dest_mtime" '+%Y-%m-%d %H:%M:%S UTC' 2>/dev/null || echo "$dest_mtime")"

if [[ -f "$DEST_FILE" ]]; then
  src_hash="$(sha256sum "$best_file" 2>/dev/null | awk '{print $1}')"
  dst_hash="$(sha256sum "$DEST_FILE" 2>/dev/null | awk '{print $1}')"
  if [[ -n "$src_hash" && -n "$dst_hash" && "$src_hash" == "$dst_hash" ]]; then
    echo "$ONCE_LOG_PREFIX no update (candidate content identical to destination)"
    echo "$ONCE_LOG_PREFIX best_candidate=$best_file"
    exit 0
  fi
fi

if [[ "$best_mtime" -le "$dest_mtime" ]]; then
  echo "$ONCE_LOG_PREFIX candidate content fresh but mtime not newer; applying update due to content freshness"
fi

cp -f "$best_file" "$DEST_FILE"
chmod 664 "$DEST_FILE" 2>/dev/null || true
new_mtime="$(stat -c %Y "$DEST_FILE" 2>/dev/null || echo 0)"
new_human="$(date -u -d "@$new_mtime" '+%Y-%m-%d %H:%M:%S UTC' 2>/dev/null || echo "$new_mtime")"

echo "$ONCE_LOG_PREFIX updated dest from candidate"
echo "$ONCE_LOG_PREFIX source=$best_file mtime=$best_human"
echo "$ONCE_LOG_PREFIX dest=$DEST_FILE new_mtime=$new_human"

# Show last 2 lines for quick verification
{ tail -n 2 "$DEST_FILE" 2>/dev/null || true; } | sed "s/^/$ONCE_LOG_PREFIX tail: /"

# Validate content recency from the last CSV row timestamp.
content_epoch="$(_parse_content_epoch "$DEST_FILE")"


if [[ -n "$content_epoch" ]]; then
  now_epoch="$(date +%s)"
  content_lag="$((now_epoch - content_epoch))"
  content_human="$(date -u -d "@$content_epoch" '+%Y-%m-%d %H:%M:%S UTC' 2>/dev/null || echo "$content_epoch")"
  if [[ "$content_lag" -le "$MAX_CONTENT_LAG_SEC" ]]; then
    echo "$ONCE_LOG_PREFIX content_fresh=true content_last=$content_human content_lag_s=$content_lag"
  else
    echo "$ONCE_LOG_PREFIX content_fresh=false content_last=$content_human content_lag_s=$content_lag max_content_lag_s=$MAX_CONTENT_LAG_SEC"
  fi
else
  echo "$ONCE_LOG_PREFIX content_fresh=unknown (could not parse last row timestamp)"
fi
exit 0
