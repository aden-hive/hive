#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO_ROOT"

PLIST_DST="${PLIST_DST:-$HOME/Library/LaunchAgents/com.hive.procurement-approval-agent.plist}"
WATCH_DIR="${WATCH_DIR:-$HOME/procurement_approval_agent/watched_requests}"
LOG_FILE="${LOG_FILE:-/tmp/procurement_approval_agent_launchd.log}"
POLL_INTERVAL="${POLL_INTERVAL:-2.0}"

mkdir -p "$HOME/Library/LaunchAgents" "$WATCH_DIR"

uv run python -m examples.templates.procurement_approval_agent write-launchd \
  --destination "$PLIST_DST" \
  --watch-dir "$WATCH_DIR" \
  --poll-interval "$POLL_INTERVAL" \
  --log-file "$LOG_FILE"

launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load -w "$PLIST_DST"

echo "Installed launchd service: $PLIST_DST"
echo "Watch directory: $WATCH_DIR"
echo "Log: $LOG_FILE"
