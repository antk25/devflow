#!/usr/bin/env bash
set -euo pipefail
DEVFLOW_DIR="$(dirname "$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")")"
[ -f AGENTS.md ] || exit 0
read -r session_id source < <(python3 -c 'import json,sys
try: d = json.load(sys.stdin)
except Exception: d = {}
print(d.get("session_id") or "-", d.get("source") or "-")' 2>/dev/null || echo "- -")
[ "$session_id" = - ] && session_id=""
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
# /cut writes the handoff right before /clear: a fresh one means this session continues it.
if [ "$source" = clear ]; then
    handoff="$("$DEVFLOW_DIR/scripts/devflow-cli.sh" handoff latest | python3 -c 'import json,sys; print(json.load(sys.stdin).get("path") or "")' 2>/dev/null || true)"
    if [ -n "$handoff" ] && [ -n "$(find "$handoff" -mmin -30 2>/dev/null)" ]; then printf 'HANDOFF %s\n' "$handoff"; fi
fi
