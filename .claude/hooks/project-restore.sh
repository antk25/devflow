#!/bin/bash
# Project Context Auto-Restore
# Runs at SessionStart to output active project info for Claude to restore context.
#
# Reads from: .claude/data/project.json (local, per-project config)
# Fallback:   devflow/.claude/data/projects.json (central registry)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Try local project.json first (new per-project config)
LOCAL_CONFIG="$(pwd)/.claude/data/project.json"

if [ -f "$LOCAL_CONFIG" ]; then
    # Read from local project config
    project_info=$(python3 -c "
import json
with open('$LOCAL_CONFIG') as f:
    p = json.load(f)
name = p.get('name', '')
ptype = p.get('type', '')
docker_start = (p.get('docker') or {}).get('start', '')
print('PROJECT_RESTORE')
print(f'name={name}')
print(f'type={ptype}')
print(f'path=$(pwd)')
print(f'docker_start={docker_start}')
" 2>/dev/null)

    active=$(python3 -c "
import json
with open('$LOCAL_CONFIG') as f:
    print(json.load(f).get('name', ''))
" 2>/dev/null)
else
    # Fallback: read from central projects.json
    PROJECTS_FILE="$DEVFLOW_DIR/.claude/data/projects.json"

    if [ ! -f "$PROJECTS_FILE" ]; then
        exit 0
    fi

    active=$(python3 -c "
import json, sys
with open('$PROJECTS_FILE') as f:
    data = json.load(f)
print(data.get('active', '') or '')
" 2>/dev/null)

    if [ -z "$active" ]; then
        exit 0
    fi

    project_info=$(python3 -c "
import json
with open('$PROJECTS_FILE') as f:
    data = json.load(f)
p = data['projects'].get('$active', {})
print('PROJECT_RESTORE')
print(f'name=$active')
print(f'type={p.get(\"type\",\"\")}')
print(f'path={p.get(\"path\",\"\")}')
docker_start = (p.get('docker') or {}).get('start', '')
print(f'docker_start={docker_start}')
" 2>/dev/null)
fi

echo "$project_info"

# Check for interrupted sessions
interrupted=$(python3 "$DEVFLOW_DIR/scripts/session-log.py" check-interrupted --project "$active" --limit 5 2>/dev/null)
if [ -n "$interrupted" ]; then
    echo "$interrupted"
fi

# Show active Obsidian documents (contracts, TZ)
obsidian_active=$("$DEVFLOW_DIR/scripts/obsidian-active.sh" "$active" 2>/dev/null)
if [ -n "$obsidian_active" ] && ! echo "$obsidian_active" | grep -q '"error"'; then
    echo "OBSIDIAN_CONTEXT=$obsidian_active"
fi
