#!/bin/bash
# Auto-approve hook for Claude Code
# This hook automatically approves ALL tool calls except for explicitly blocked ones

# Read the tool call from stdin
INPUT=$(cat)

# Parse tool name and input for blocking check
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // .tool // empty')
TOOL_INPUT=$(echo "$INPUT" | jq -r '.tool_input // .input // empty' 2>/dev/null)

# Combine for pattern matching
FULL_INPUT="$TOOL_NAME $TOOL_INPUT"

# === Always-blocked patterns (safety) ===
if [[ "$FULL_INPUT" == *"git push"* ]] || \
   [[ "$FULL_INPUT" == *"git remote"* ]] || \
   [[ "$TOOL_NAME" == "gh" ]] || \
   [[ "$FULL_INPUT" == *" gh "* ]] || \
   [[ "$FULL_INPUT" == *"ssh "* ]] || \
   [[ "$FULL_INPUT" == *"scp "* ]] || \
   [[ "$FULL_INPUT" == *"rsync "* ]]; then
    # Exit without output - Claude Code will prompt user
    exit 0
fi

# === Careful mode: extra blocks when activated ===
# Check for careful-mode flag file in the project
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAREFUL_FILE="$SCRIPT_DIR/../data/careful-mode.json"

if [[ -f "$CAREFUL_FILE" ]]; then
    # Read blocked patterns from the JSON file
    PATTERNS=$(jq -r '.blocked_patterns[]' "$CAREFUL_FILE" 2>/dev/null)
    if [[ -n "$PATTERNS" ]]; then
        while IFS= read -r pattern; do
            if [[ -n "$pattern" && "$FULL_INPUT" == *"$pattern"* ]]; then
                # Blocked by careful mode — prompt user for approval
                exit 0
            fi
        done <<< "$PATTERNS"
    fi
fi

# Auto-approve everything else (Read, Write, Edit, Bash, Task, MCP tools, etc.)
echo '{"decision": "approve"}'
