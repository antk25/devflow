#!/bin/bash
# Session End Hook — Summarize session transcript
# Triggered on SessionEnd to create a structured summary of the conversation.
# Runs async so it doesn't block session exit.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Read hook input from stdin
INPUT=$(cat)

SESSION_ID=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null)
TRANSCRIPT_PATH=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null)

if [ -z "$SESSION_ID" ] || [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    exit 0
fi

# Check minimum file size (skip trivial sessions < 5KB)
FILE_SIZE=$(stat -c%s "$TRANSCRIPT_PATH" 2>/dev/null || echo "0")
if [ "$FILE_SIZE" -lt 5000 ]; then
    exit 0
fi

# Run summarization
python3 "$DEVFLOW_DIR/scripts/session-log.py" summarize "$TRANSCRIPT_PATH" "$SESSION_ID" 2>/dev/null

exit 0
