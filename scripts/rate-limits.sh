#!/usr/bin/env bash
# Statusline filter: stdin JSON from Claude Code → ~/.claude/devflow/rate-limits.json when `.rate_limits` is present.
# Wire it in ~/.claude/statusline.sh: echo "$input" | devflow-rate-limits
set -uo pipefail
out="${DEVFLOW_RATE_LIMITS:-${DEVFLOW_CLAUDE_DIR:-$HOME/.claude}/devflow/rate-limits.json}"
json="$(jq -c --arg at "$(date +%s)" '.rate_limits as $r | select($r != null)
    | {five_hour: $r.five_hour, seven_day: $r.seven_day, model: ($r.model // .model.id // .model.display_name), at: ($at | tonumber)}' 2>/dev/null)" || exit 0
[ -n "$json" ] || exit 0
mkdir -p "$(dirname "$out")"
printf '%s\n' "$json" > "$out.tmp" && mv -f -- "$out.tmp" "$out"
