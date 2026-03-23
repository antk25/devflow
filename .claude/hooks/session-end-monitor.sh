#!/bin/bash
# Session End Hook — Run monitor quick check
# Triggered on SessionEnd to detect problems in recent sessions.
# Runs async so it doesn't block session exit.
# Appends findings to ~/.claude/sessions-log/monitor/checks.jsonl

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
MONITOR_DIR="$HOME/.claude/sessions-log/monitor"

# Ensure monitor directory exists
mkdir -p "$MONITOR_DIR"

# Run quick check
FINDINGS=$(python3 "$DEVFLOW_DIR/scripts/monitor-check.py" quick 2>/tmp/monitor-notifications.txt)

# Skip if no findings or empty array
if [ -z "$FINDINGS" ] || [ "$FINDINGS" = "[]" ]; then
    rm -f /tmp/monitor-notifications.txt
    exit 0
fi

# Append to checks.jsonl with timestamp
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "{\"timestamp\": \"$TIMESTAMP\", \"findings\": $FINDINGS}" >> "$MONITOR_DIR/checks.jsonl"

# Send desktop notification if there were critical/high findings
NOTIFICATIONS=$(cat /tmp/monitor-notifications.txt 2>/dev/null)
rm -f /tmp/monitor-notifications.txt

if [ -n "$NOTIFICATIONS" ]; then
    "$DEVFLOW_DIR/scripts/notify.sh" "DevFlow Monitor" "$NOTIFICATIONS" "normal" "dialog-warning"
fi

exit 0
