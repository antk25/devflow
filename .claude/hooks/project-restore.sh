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
# A fresh, unambiguous handoff can also come from pi, not only from /clear.
if [[ "$source" = clear || "$source" = startup || "$source" = resume || "$source" = compact ]]; then
    latest=(handoff latest --fresh-minutes 30)
    if [ -n "$session_id" ]; then
        task="$("$DEVFLOW_DIR/scripts/devflow-cli.sh" handoff slug --session "$session_id" 2>/dev/null \
            | python3 -c 'import json,sys; print(json.load(sys.stdin).get("slug") or "")' 2>/dev/null || true)"
        [ -n "$task" ] && latest+=(--task "$task")
    fi
    if handoff_json="$("$DEVFLOW_DIR/scripts/devflow-cli.sh" "${latest[@]}" 2>&1)"; then
        handoff="$(printf '%s' "$handoff_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("path") or "")')"
        if [ -n "$handoff" ] && [ -n "$(find "$handoff" -mmin -30 2>/dev/null)" ]; then
            printf 'HANDOFF %s\n' "$handoff"
            printf 'После чтения передачи выполните devflow route <полный slug>; recovery только по явному решению, без автоматических approve/finish/resume.\n'
        fi
    else
        printf 'HANDOFF: выберите полный slug явно; %s\n' "$handoff_json"
    fi
fi
