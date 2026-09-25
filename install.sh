#!/usr/bin/env bash
# Install DevFlow's Claude skills; all conflicts are checked before writing.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
DEVFLOW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${DEVFLOW_CLAUDE_DIR:-$HOME/.claude}"
BIN_DIR="${DEVFLOW_BIN_DIR:-$HOME/.local/bin}"
INTEGRATIONS_DIR="${DEVFLOW_INTEGRATIONS_DIR:-$HOME/.config/devflow/integrations}"
SKILLS=(note project devflow standup tokens page review jira jira-create xreview)
[ ! -d "$DEVFLOW_DIR/skills/autoresearch" ] || SKILLS+=(autoresearch)
AGENTS=(research plan implement review-standards review-conformance crossreview)
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
sources+=("$DEVFLOW_DIR/scripts/devflow-cli.sh")
destinations+=("$BIN_DIR/devflow")
sources+=("$DEVFLOW_DIR/bin/lcurl")
destinations+=("$BIN_DIR/lcurl")
for src in "$DEVFLOW_DIR"/integrations/jira-*.sh; do
    sources+=("$src")
    destinations+=("$INTEGRATIONS_DIR/$(basename "$src")")
done
sources+=("$DEVFLOW_DIR/integrations/config.env.template")
destinations+=("$INTEGRATIONS_DIR/config.env.template")

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
    if [ -x "$PYTHON" ]; then
        if ! "$PYTHON" -c 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1] + "/scripts"); from devflow.project import registry_path; from devflow.registry import load; p = registry_path(Path(sys.argv[1])); p.exists() or sys.exit("MISS project registry"); load(p)' \
            "$DEVFLOW_DIR"; then
            issues=1
        fi
    fi
    for name in "${RETIRED_SKILLS[@]}"; do
        dst="$CLAUDE_DIR/skills/$name"
        if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$DEVFLOW_DIR/skills/$name" ]; then
            echo "RETIRE $dst"; issues=1
        fi
    done
    if [ -x "$PYTHON" ]; then
        drift="$("$PYTHON" -c 'import sys; sys.path.insert(0, sys.argv[1])
from devflow.project import guard_probe, settings_drift
for c in guard_probe(sys.argv[2]): print("BROKEN global hook PreToolUse", c)
d = settings_drift(sys.argv[2], sys.argv[3])
for c in d["hooks"]: print("MISS global hook", c)
for p in d["allow"]: print("MISS global allow", p)
for p in d["ask"]: print("MISS global ask", p)
for p in d["deny"]: print("MISS global deny", p)
for p in d["extra_deny"]: print("STALE global deny", p)' \
            "$DEVFLOW_DIR/scripts" "$CLAUDE_DIR/settings.json" "$DEVFLOW_DIR/settings.global.example.json")" || issues=1
        if [ -n "$drift" ]; then
            echo "$drift"; issues=1
            echo "(merge settings.global.example.json into $CLAUDE_DIR/settings.json by hand; __DEVFLOW_ROOT__ = $DEVFLOW_DIR)"
        fi
    fi
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
    mkdir -p "$CLAUDE_DIR/skills" "$CLAUDE_DIR/agents" "$BIN_DIR" "$INTEGRATIONS_DIR"
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
