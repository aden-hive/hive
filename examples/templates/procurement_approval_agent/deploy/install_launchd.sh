#!/usr/bin/env bash
set -euo pipefail

PLIST_SRC="examples/templates/procurement_approval_agent/deploy/com.hive.procurement-approval-agent.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.hive.procurement-approval-agent.plist"

mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DST"

launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load -w "$PLIST_DST"

echo "Installed launchd service: $PLIST_DST"
echo "Log: /tmp/procurement_approval_agent_launchd.log"
