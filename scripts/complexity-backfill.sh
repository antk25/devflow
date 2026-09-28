#!/usr/bin/env bash
# Shadow-label past tasks for Jev calibration: one `devflow complexity <slug> --gate backfill` per tz/<slug>.md with a plan.
# Usage: complexity-backfill.sh <project-cwd>   → appends JSONL {slug, choice, noul, facts} to $DEVFLOW_COMPLEXITY_BACKFILL
set -uo pipefail
cwd="${1:?usage: complexity-backfill.sh <project-cwd>}"
out="${DEVFLOW_COMPLEXITY_BACKFILL:-${DEVFLOW_CLAUDE_DIR:-$HOME/.claude}/devflow/complexity-backfill.jsonl}"
devflow="${DEVFLOW_BIN:-devflow}"
vault="$("$devflow" --cwd "$cwd" context | jq -r .vault)" || exit 1
mkdir -p "$(dirname "$out")"
for tz in "$vault"/tz/*.md; do
    [ -e "$tz" ] || continue
    slug="$(basename "$tz" .md)"
    if ! ls "$vault"/plans/"$slug".md >/dev/null 2>&1; then
        echo "skip $slug: нет плана"; continue
    fi
    result="$("$devflow" --cwd "$cwd" complexity "$slug" --gate backfill)" || { echo "fail $slug"; continue; }
    printf '%s\n' "$result" | jq -c '{slug, choice: .jev.choice, noul: .jev.noul, facts, error: .jev.error}' >> "$out"
    echo "ok $slug: $(printf '%s' "$result" | jq -r '.jev.choice // ("— " + (.jev.error // ""))')"
done
echo "→ $out"
