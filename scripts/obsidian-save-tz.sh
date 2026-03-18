#!/bin/bash
# obsidian-save-tz.sh — Save/update task description (TZ) to Obsidian vault
#
# Usage: obsidian-save-tz.sh <project> <branch> <title> [--update]
#   project   — project name from projects.json
#   branch    — work branch name (used as slug)
#   title     — feature title for the TZ
#   --update  — update existing TZ (append new content from stdin)
#
# Content is read from stdin.
#
# Output: full path to saved TZ file
# Exit codes:
#   0 = success
#   1 = vault not configured or not accessible
#   2 = invalid arguments

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$SCRIPT_DIR")"
PROJECTS_FILE="$DEVFLOW_DIR/.claude/data/projects.json"

PROJECT="${1:-}"
BRANCH="${2:-}"
TITLE="${3:-}"
UPDATE=false

for arg in "$@"; do
    [ "$arg" = "--update" ] && UPDATE=true
done

if [ -z "$PROJECT" ] || [ -z "$BRANCH" ] || [ -z "$TITLE" ]; then
    echo "ERROR: Required: project, branch, title" >&2
    echo "HINT: Usage: echo 'content' | obsidian-save-tz.sh <project> <branch> <title>" >&2
    exit 2
fi

# Read vault path from projects.json
VAULT_PATH=$(python3 -c "
import json
with open('$PROJECTS_FILE') as f:
    data = json.load(f)
print(data.get('obsidian_vault', ''))
" 2>/dev/null)

if [ -z "$VAULT_PATH" ] || [ ! -d "$VAULT_PATH" ]; then
    echo "ERROR: Obsidian vault not configured or not accessible: $VAULT_PATH" >&2
    exit 1
fi

TZ_DIR="$VAULT_PATH/projects/$PROJECT/tz"
mkdir -p "$TZ_DIR"

# Slugify branch for filename
SLUG=$(echo "$BRANCH" | sed 's/[\/]/-/g' | sed 's/-work$//')
TZ_FILE="$TZ_DIR/${SLUG}-tz.md"

CONTENT=$(cat)

if [ "$UPDATE" = true ] && [ -f "$TZ_FILE" ]; then
    # Append new content with timestamp
    TIMESTAMP=$(date +"%Y-%m-%d %H:%M")
    {
        echo ""
        echo "---"
        echo ""
        echo "## Дополнение ($TIMESTAMP)"
        echo ""
        echo "$CONTENT"
    } >> "$TZ_FILE"
else
    # Create new TZ file
    DATE=$(date +"%Y-%m-%d")
    cat > "$TZ_FILE" <<TZEOF
---
created: $DATE
project: $PROJECT
type: tz
branch: $BRANCH
status: active
tags: [тз, $PROJECT]
---

# $TITLE

$CONTENT
TZEOF
fi

echo "$TZ_FILE"
