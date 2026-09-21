#!/usr/bin/env bash
# Install DevFlow's Claude skills; all conflicts are checked before writing.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
DEVFLOW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${DEVFLOW_CLAUDE_DIR:-$HOME/.claude}"
SKILLS=(note project devflow standup tokens page review jira xreview)
[ ! -d "$DEVFLOW_DIR/skills/autoresearch" ] || SKILLS+=(autoresearch)
AGENTS=(research plan implement review-standards review-conformance)
RETIRED_SKILLS=(research plan implement quick)
mode=install
case "${1:-}" in
    --check) mode=check ;;
    --remove) mode=remove ;;
    '') ;;
    *) echo "Usage: $0 [--check|--remove]" >&2; exit 1 ;;
esac
[ "$#" -le 1 ] || { echo 'Too many arguments' >&2; exit 1; }

sources=() destinations=()
for name in "${SKILLS[@]}"; do
    sources+=("$DEVFLOW_DIR/skills/$name")
    destinations+=("$CLAUDE_DIR/skills/$name")
done
for name in "${AGENTS[@]}"; do
    sources+=("$DEVFLOW_DIR/agents/$name.md")
    destinations+=("$CLAUDE_DIR/agents/$name.md")
done

issues=0
for i in "${!sources[@]}"; do
    src="${sources[$i]}" dst="${destinations[$i]}"
    if [ "$mode" = remove ]; then
        if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
            rm -- "$dst"
            echo "unlink $dst"
        fi
    elif [ ! -e "$src" ]; then
        echo "MISS source: $src" >&2; issues=1
    elif [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
        echo "ok $dst"
    elif [ -e "$dst" ] || [ -L "$dst" ]; then
        echo "CONFLICT (not replacing): $dst" >&2; issues=1
    elif [ "$mode" = check ]; then
        echo "MISS $dst"; issues=1
    fi
done

if [ "$mode" = check ]; then
    PYTHON="$DEVFLOW_DIR/.venv/bin/python"
    if [ ! -x "$PYTHON" ]; then
        echo 'MISS Python environment; run ./install.sh'; issues=1
    elif ! "$PYTHON" -c 'import sys, yaml; assert sys.version_info >= (3, 10)' 2>/dev/null; then
        echo 'MISS Python 3.10+ / PyYAML'; issues=1
    fi
    if [ ! -f "$DEVFLOW_DIR/.claude/data/projects.json" ]; then
        echo 'MISS project registry'; issues=1
    elif [ -x "$PYTHON" ]; then
        if ! "$PYTHON" -c 'import sys; sys.path.insert(0, sys.argv[1]); from devflow.registry import load; load(sys.argv[2])' \
            "$DEVFLOW_DIR/scripts" "$DEVFLOW_DIR/.claude/data/projects.json"; then
            issues=1
        fi
    fi
    for name in "${RETIRED_SKILLS[@]}"; do
        dst="$CLAUDE_DIR/skills/$name"
        if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$DEVFLOW_DIR/skills/$name" ]; then
            echo "RETIRE $dst"; issues=1
        fi
    done
    echo '(check mode — no changes made)'
    exit "$issues"
fi
[ "$issues" -eq 0 ] || exit 1

if [ "$mode" = install ]; then
    python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
    if [ ! -x "$DEVFLOW_DIR/.venv/bin/python" ]; then
        python3 -m venv --system-site-packages "$DEVFLOW_DIR/.venv"
    fi
    PYTHON="$DEVFLOW_DIR/.venv/bin/python"
    if ! "$PYTHON" -c 'import yaml' 2>/dev/null; then
        "$PYTHON" -m pip install -r "$DEVFLOW_DIR/requirements.txt"
    fi
    "$PYTHON" -c 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1] + "/scripts"); from devflow.registry import initialize; initialize(Path(sys.argv[1]))' "$DEVFLOW_DIR"
    mkdir -p "$CLAUDE_DIR/skills" "$CLAUDE_DIR/agents"
    for i in "${!sources[@]}"; do
        src="${sources[$i]}" dst="${destinations[$i]}"
        if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
            continue
        fi
        # No force: if a destination appeared after preflight, stop without replacing it.
        ln -sT -- "$src" "$dst"
        echo "link $dst"
    done
fi
for name in "${RETIRED_SKILLS[@]}"; do
    dst="$CLAUDE_DIR/skills/$name"
    if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$DEVFLOW_DIR/skills/$name" ]; then
        rm -- "$dst"
        echo "retire $dst"
    fi
done
echo "DevFlow $mode complete. Project state and registry are preserved on removal."
