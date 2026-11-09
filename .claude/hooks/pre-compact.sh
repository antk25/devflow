#!/usr/bin/env bash
# PreCompact: compaction is a session cut — write the task hand-off and tell the summary what to keep.
host=claude
[ "${1:-}" = --host ] && host="${2:-claude}"
DEVFLOW_DIR="$(dirname "$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")")"
IFS=$'\t' read -r session trigger cwd_dir tokens < <(python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
tok = "-"
try:
    for line in reversed(open(d.get("transcript_path") or "", encoding="utf-8").read().splitlines()):
        try:
            u = json.loads(line)["message"]["usage"]
        except Exception:
            continue
        tok = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        break
except Exception:
    pass
trigger = d.get("trigger") if d.get("trigger") in ("auto", "manual") else "auto"
print(d.get("session_id") or "-", trigger, d.get("cwd") or ".", tok, sep="\t")
' 2>/dev/null) || exit 0
[ -n "${session:-}" ] && [ "$session" != - ] || exit 0
[ -f "$cwd_dir/AGENTS.md" ] || exit 0
args=(--cwd "$cwd_dir" handoff auto --session "$session" --trigger "$trigger" --host "$host")
[ "$tokens" != - ] && args+=(--context-tokens "$tokens")
"$DEVFLOW_DIR/scripts/devflow-cli.sh" "${args[@]}" 2>/dev/null \
    | python3 -c 'import json,sys
text = json.load(sys.stdin)["instructions"]
# Codex accepts only JSON from PreCompact and has no field for the summary; the user sees systemMessage.
print(json.dumps({"systemMessage": text}, ensure_ascii=False) if sys.argv[1] == "codex" else text)' "$host" 2>/dev/null || true
exit 0
