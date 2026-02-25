#!/bin/bash
# Project Context Auto-Restore
# Runs at SessionStart to output active project info for Claude to restore context.
# Claude reads this output and activates Serena, loads memories, etc.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
PROJECTS_FILE="$ORCHESTRATOR_DIR/.claude/data/projects.json"

if [ ! -f "$PROJECTS_FILE" ]; then
    exit 0
fi

# Extract active project name
active=$(python3 -c "
import json, sys
with open('$PROJECTS_FILE') as f:
    data = json.load(f)
print(data.get('active', '') or '')
" 2>/dev/null)

if [ -z "$active" ]; then
    exit 0
fi

# Extract project details
project_info=$(python3 -c "
import json
with open('$PROJECTS_FILE') as f:
    data = json.load(f)
p = data['projects'].get('$active', {})
print(f\"PROJECT_RESTORE\")
print(f\"name=$active\")
print(f\"type={p.get('type','')}\")
serena = p.get('serena_project') or ''
print(f\"serena={serena}\")
print(f\"path={p.get('path','')}\")
docker_start = (p.get('docker') or {}).get('start', '')
print(f\"docker_start={docker_start}\")
" 2>/dev/null)

echo "$project_info"
