#!/bin/bash

# Aden Hive Background Watcher
# Tracks assignments and PR status to alert you in real-time.

REPO="aden-hive/hive"
STATE_FILE="/tmp/hive_watcher_state.json"
INTERVAL=300 # 5 minutes

# Initialize state if not exists
if [ ! -f "$STATE_FILE" ]; then
    echo "{}" > "$STATE_FILE"
fi

notify() {
    local title="$1"
    local message="$2"
    osascript -e "display notification \"$message\" with title \"$title\""
}

check_updates() {
    # 1. Check for new assignments
    assignments=$(gh issue list --repo "$REPO" --assignee "@me" --state open --json number,title)
    assigned_count=$(echo "$assignments" | jq '. | length')
    
    # Simple state tracking for assignments
    prev_assigned=$(jq -r '.assigned_count // 0' "$STATE_FILE")
    if [ "$assigned_count" -gt "$prev_assigned" ]; then
        new_issue=$(echo "$assignments" | jq -r '.[-1] | "\(.number): \(.title)"')
        notify "Hive: New Assignment!" "You were assigned to #$new_issue"
    fi

    # 2. Check specific PR statuses
    # We track our active PRs: 7097, 7107, 7151
    for pr in 7097 7107 7151; do
        status_json=$(gh pr view "$pr" --repo "$REPO" --json state,statusCheckRollup 2>/dev/null)
        if [ -n "$status_json" ]; then
            state=$(echo "$status_json" | jq -r '.state')
            # Check if all checks passed
            checks_passing=$(echo "$status_json" | jq -r '.statusCheckRollup[]?.conclusion // "PENDING"' | grep -v "SUCCESS" | grep -v "NEUTRAL" | wc -l)
            
            prev_state=$(jq -r ".pr_$pr.state // \"\"" "$STATE_FILE")
            prev_checks=$(jq -r ".pr_$pr.checks // \"\"" "$STATE_FILE")

            if [ "$state" != "$prev_state" ] || ([ "$checks_passing" -eq 0 ] && [ "$prev_checks" != "GREEN" ]); then
                if [ "$checks_passing" -eq 0 ]; then
                    notify "Hive PR #$pr Status" "All checks passed! State: $state"
                    tmp_checks="GREEN"
                else
                    notify "Hive PR #$pr Update" "State changed to $state"
                    tmp_checks="PENDING"
                fi
                # Update local state
                jq ".pr_$pr = {\"state\": \"$state\", \"checks\": \"$tmp_checks\"}" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
            fi
        fi
    done

    # Update assigned count in state
    jq ".assigned_count = $assigned_count" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
}

echo "Hive Watcher started. Polling every $INTERVAL seconds..."
while true; do
    check_updates
    sleep "$INTERVAL"
done
