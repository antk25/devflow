#!/bin/bash
# PreCompact Hook — Save transcript snapshot before context compaction
# This preserves the full conversation before Claude compresses it.
# Runs async so it doesn't block the compaction.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Read hook input from stdin
INPUT=$(cat)

SESSION_ID=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null)
TRANSCRIPT_PATH=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null)

if [ -z "$SESSION_ID" ] || [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    exit 0
fi

# Save snapshot
python3 "$DEVFLOW_DIR/scripts/session-log.py" snapshot "$TRANSCRIPT_PATH" "$SESSION_ID" 2>/dev/null

exit 0
