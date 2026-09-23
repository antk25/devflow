#!/usr/bin/env bash
set -euo pipefail
DEVFLOW_DIR="$(dirname "$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")")"
[ -f AGENTS.md ] || exit 0
session_id="$(python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("session_id") or "")
except Exception: print("")' 2>/dev/null || true)"
if [ -n "$session_id" ]; then
    marker="${XDG_RUNTIME_DIR:-/tmp}/devflow-restore-${session_id//[^A-Za-z0-9_-]/_}"
    if [ -f "$marker" ] && [ "$(( $(date +%s) - $(stat -c %Y "$marker") ))" -lt 10 ]; then
        exit 0
    fi
    touch "$marker"
fi
printf 'PROJECT_RESTORE\n'
"$DEVFLOW_DIR/scripts/devflow-cli.sh" context
printf 'OBSIDIAN_CONTEXT\n'
"$DEVFLOW_DIR/scripts/devflow-cli.sh" active
