#!/bin/bash
# Project Context Auto-Restore (SessionStart hook)
#
# Reads the current project's AGENTS.md and emits PROJECT_RESTORE +
# OBSIDIAN_CONTEXT for Claude to greet the user with active project info.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

AGENTS_FILE="$(pwd)/AGENTS.md"

if [ ! -f "$AGENTS_FILE" ]; then
    exit 0
fi

python3 - "$AGENTS_FILE" <<'PY' 2>/dev/null
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding='utf-8')
if not text.startswith('---'):
    sys.exit(0)
parts = text.split('---', 2)
if len(parts) < 3:
    sys.exit(0)

fm = {}
for line in parts[1].strip().splitlines():
    if ':' in line:
        k, _, v = line.partition(':')
        fm[k.strip()] = v.strip()

name = fm.get('project', '')
if not name:
    sys.exit(0)

print('PROJECT_RESTORE')
print(f'name={name}')
print(f'path={Path.cwd()}')
PY

# Show active Obsidian documents (tz, research, plans)
obsidian_active=$("$DEVFLOW_DIR/scripts/obsidian-active.sh" 2>/dev/null)
if [ -n "$obsidian_active" ] && ! echo "$obsidian_active" | grep -q '"error"'; then
    echo "OBSIDIAN_CONTEXT=$obsidian_active"
fi
