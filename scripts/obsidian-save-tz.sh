#!/bin/bash
# obsidian-save-tz.sh — Save/update task description (TZ) to Obsidian vault
#
# Usage: obsidian-save-tz.sh <project> <branch> <title> [--update]
#   project   — project name
#   branch    — work branch name (used as slug)
#   title     — feature title for the TZ
#   --update  — update existing TZ (append new content from stdin)
#
# Reads vault path from:
#   1. <cwd>/.claude/data/project.json (local config)
#   2. devflow/.claude/data/projects.json (central, fallback)
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

# Read vault path from local project.json or central projects.json
VAULT_INFO=$(python3 -c "
import json, os

# Try local project.json
local_config = os.path.join(os.getcwd(), '.claude', 'data', 'project.json')
if os.path.isfile(local_config):
    with open(local_config) as f:
        cfg = json.load(f)
    obsidian = cfg.get('obsidian', {})
    vault = obsidian.get('vault', '')
    project_dir = obsidian.get('project_dir', f'projects/${PROJECT}')
    if vault:
        print(f'{vault}|{project_dir}')
        exit()

# Fallback: central projects.json
projects_file = '$DEVFLOW_DIR/.claude/data/projects.json'
if os.path.isfile(projects_file):
    with open(projects_file) as f:
        data = json.load(f)
    vault = data.get('obsidian_vault', '')
    if vault:
        print(f'{vault}|projects/${PROJECT}')
        exit()

print('')
" 2>/dev/null)

VAULT_PATH=$(echo "$VAULT_INFO" | cut -d'|' -f1)
PROJECT_DIR=$(echo "$VAULT_INFO" | cut -d'|' -f2)

if [ -z "$VAULT_PATH" ] || [ ! -d "$VAULT_PATH" ]; then
    echo "ERROR: Obsidian vault not configured or not accessible: $VAULT_PATH" >&2
    exit 1
fi

TZ_DIR="$VAULT_PATH/$PROJECT_DIR/tz"
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
