#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

export PYTHONPATH="core:examples/templates"
export HIVE_AGENT_STORAGE_ROOT="/tmp/hive_agents_demo_record"

WATCH_API="/tmp/watched_requests_api"
WATCH_CSV="/tmp/watched_requests_csv"
LOG_API="/tmp/procurement_demo_api.log"
LOG_CSV="/tmp/procurement_demo_csv.log"
FIFO_API="/tmp/procurement_demo_api.fifo"
FIFO_CSV="/tmp/procurement_demo_csv.fifo"

API_RESULT="$WATCH_API/results/request_api.result.json"
CSV_RESULT="$WATCH_CSV/results/request_csv.result.json"

pause() {
  local seconds="$1"
  echo "[demo] sleeping ${seconds}s..."
  sleep "$seconds"
}

step() {
  echo
  echo "=================================================="
  echo "[demo] $1"
  echo "=================================================="
}

start_monitor() {
  local watch_dir="$1"
  local log_file="$2"
  local fifo_path="$3"

  rm -f "$fifo_path"
  mkfifo "$fifo_path"

  python -m procurement_approval_agent monitor \
    --watch-dir "$watch_dir" \
    --poll-interval 1.0 \
    --mock \
    --interactive \
    < "$fifo_path" \
    > "$log_file" 2>&1 &

  MON_PID=$!
  echo "[demo] monitor pid: $MON_PID"
}

feed_answers() {
  local fifo_path="$1"
  local process_answer="$2"
  local has_qb_answer="$3"
  local sync_answer="$4"

  (
    exec 3>"$fifo_path"
    pause 3
    printf "%s\n" "$process_answer" >&3
    pause 2
    printf "%s\n" "$has_qb_answer" >&3
    pause 2
    printf "%s\n" "$sync_answer" >&3
    exec 3>&-
  ) &
  FEED_PID=$!
}

wait_for_file() {
  local file_path="$1"
  local timeout_seconds="${2:-30}"
  local elapsed=0

  while [[ $elapsed -lt $timeout_seconds ]]; do
    if [[ -f "$file_path" ]]; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  return 1
}

stop_monitor() {
  if [[ -n "${FEED_PID:-}" ]] && kill -0 "$FEED_PID" 2>/dev/null; then
    wait "$FEED_PID" 2>/dev/null || true
  fi

  if [[ -n "${MON_PID:-}" ]] && kill -0 "$MON_PID" 2>/dev/null; then
    kill "$MON_PID" 2>/dev/null || true
    wait "$MON_PID" 2>/dev/null || true
    echo "[demo] monitor stopped (pid: $MON_PID)"
  fi

  MON_PID=""
  FEED_PID=""
}

cleanup() {
  stop_monitor
  rm -f "$FIFO_API" "$FIFO_CSV"
}

trap cleanup EXIT

step "Pre-flight checks"
which ollama
ollama list

echo "[demo] checking model availability (expect llama3.2)"
if ! ollama list | grep -q "llama3.2"; then
  echo "[demo] WARNING: llama3.2 not found in ollama list output"
fi
pause 2

step "Clear previous state"
pkill -f "procurement_approval_agent monitor" || true
rm -rf "$WATCH_API" "$WATCH_CSV" "$HIVE_AGENT_STORAGE_ROOT"
rm -f "$LOG_API" "$LOG_CSV" "$FIFO_API" "$FIFO_CSV"
mkdir -p "$WATCH_API" "$WATCH_CSV"

rm -f examples/templates/procurement_approval_agent/data/qb_mock_responses.json
rm -f examples/templates/procurement_approval_agent/data/po/*_qb_manual_import.csv
rm -f examples/templates/procurement_approval_agent/data/po/*_qb_import_instructions.md
pause 2

step "Phase 1: API path request (interactive prompts)"
python -m procurement_approval_agent reset-setup
export QUICKBOOKS_CLIENT_ID="demo-client-id"
export QUICKBOOKS_CLIENT_SECRET="demo-client-secret"
export QUICKBOOKS_REALM_ID="demo-realm-id"
export QUICKBOOKS_USE_MOCK="true"

start_monitor "$WATCH_API" "$LOG_API" "$FIFO_API"
pause 3

cat > "$WATCH_API/request_api.json" <<'JSON'
{
  "item": "MacBook Pro 16",
  "cost": 2899,
  "department": "engineering",
  "requester": "richard@company.com",
  "justification": "Need high-memory build machine for release engineering and incident response.",
  "vendor": "TechSource LLC"
}
JSON

echo "[demo] dropped request: $WATCH_API/request_api.json"
feed_answers "$FIFO_API" "yes" "yes" "yes"

if wait_for_file "$API_RESULT" 45; then
  echo "[demo] API result file detected"
else
  echo "[demo] ERROR: API result file not detected within timeout"
fi
pause 2
stop_monitor
pause 2

step "Phase 2: CSV fallback request (interactive prompts)"
python -m procurement_approval_agent reset-setup
unset QUICKBOOKS_CLIENT_ID QUICKBOOKS_CLIENT_SECRET QUICKBOOKS_REALM_ID QUICKBOOKS_USE_MOCK || true

start_monitor "$WATCH_CSV" "$LOG_CSV" "$FIFO_CSV"
pause 3

cat > "$WATCH_CSV/request_csv.json" <<'JSON'
{
  "item": "Security License Renewal",
  "cost": 1800,
  "department": "operations",
  "requester": "ops-lead@company.com",
  "justification": "Renew endpoint security licenses to maintain compliance and coverage.",
  "vendor": "Global Industrial"
}
JSON

echo "[demo] dropped request: $WATCH_CSV/request_csv.json"
feed_answers "$FIFO_CSV" "yes" "no" "yes"

if wait_for_file "$CSV_RESULT" 45; then
  echo "[demo] CSV result file detected"
else
  echo "[demo] ERROR: CSV result file not detected within timeout"
fi
pause 2
stop_monitor
pause 2

step "Monitor console output (API phase)"
sed \
  -e '/paused_at=None is not a valid node, falling back to entry point/d' \
  -e '/end_run called but no run for execution/d' \
  "$LOG_API"
pause 2

step "Monitor console output (CSV phase)"
sed \
  -e '/paused_at=None is not a valid node, falling back to entry point/d' \
  -e '/end_run called but no run for execution/d' \
  "$LOG_CSV"
pause 2

step "Generated files"
echo "[demo] API watch files"
find "$WATCH_API" -maxdepth 3 -type f | sort

echo "[demo] CSV watch files"
find "$WATCH_CSV" -maxdepth 3 -type f | sort

echo "[demo] agent data artifacts"
find examples/templates/procurement_approval_agent/data -maxdepth 4 -type f | sort
pause 2

step "Result JSON (API path)"
cat "$API_RESULT"
pause 2

step "Result JSON (CSV path)"
cat "$CSV_RESULT"
pause 2

step "Demo complete"
echo "[demo] Finished. Ready for screen recording replay."
