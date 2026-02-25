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

# Blocked patterns - these always require manual approval
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

# Auto-approve everything else (Read, Write, Edit, Bash, Task, MCP tools, etc.)
echo '{"decision": "approve"}'
