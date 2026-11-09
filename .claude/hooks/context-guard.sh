#!/usr/bin/env bash
# UserPromptSubmit: the model can't see the status line, so the cut threshold is passed to it here.
DEVFLOW_DIR="$(dirname "$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")")"
read -r session tokens < <(python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    lines = open(d.get("transcript_path") or "", encoding="utf-8").read().splitlines()
except Exception:
    sys.exit(0)
for line in reversed(lines):
    try:
        u = json.loads(line)["message"]["usage"]
    except Exception:
        continue
    print(d.get("session_id") or "-", u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0))
    break
' 2>/dev/null) || exit 0
[ -n "${tokens:-}" ] || exit 0
args=(context-level --tokens "$tokens")
[ "$session" != - ] && args+=(--session "$session")
"$DEVFLOW_DIR/scripts/devflow-cli.sh" "${args[@]}" 2>/dev/null \
    | python3 -c 'import json,sys; t = json.load(sys.stdin).get("text"); t and print(t)' 2>/dev/null || true
