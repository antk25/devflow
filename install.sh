#!/usr/bin/env bash
# devflow installer — symlinks devflow skills into ~/.claude/skills/ and phase agents
# into ~/.claude/agents/.
#
# Usage:
#   ./install.sh           # install/update symlinks (and retire stale ones)
#   ./install.sh --check   # show what would change without doing it
#   ./install.sh --remove  # remove devflow skills and agents from ~/.claude/

set -euo pipefail

DEVFLOW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Skills shipped by devflow (directory names under skills/)
SKILLS=(note project devflow standup tokens page review)

# Optional skills (installed if present)
OPTIONAL_SKILLS=(autoresearch)

# Phase agents (file names under agents/, without .md)
AGENTS=(research plan implement review-standards review-conformance)

# Skills retired by the phase-agents redesign — unlink our stale symlinks if present
RETIRED_SKILLS=(research plan implement quick)

mode="install"
case "${1:-}" in
    --check)  mode="check" ;;
    --remove) mode="remove" ;;
    "")       mode="install" ;;
    *) echo "Usage: $0 [--check|--remove]"; exit 1 ;;
esac

mkdir -p "$HOME/.claude/skills" "$HOME/.claude/agents"

# link_item <kind> <name>   kind: skills (dir) | agents (file .md)
link_item() {
    local kind=$1 name=$2
    local suffix=""; [ "$kind" = "agents" ] && suffix=".md"
    local src="$DEVFLOW_DIR/$kind/$name$suffix"
    local dst="$HOME/.claude/$kind/$name$suffix"

    if [ ! -e "$src" ]; then
        echo "  skip   $kind/$name (no source: $src)"
        return
    fi

    case "$mode" in
        check)
            if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
                echo "  ok     $kind/$name → $src"
            elif [ -e "$dst" ]; then
                echo "  CONFL  $kind/$name (exists, not our symlink): $dst"
            else
                echo "  MISS   $kind/$name (would link → $src)"
            fi
            ;;
        install)
            if [ -e "$dst" ] && [ ! -L "$dst" ]; then
                echo "  CONFL  $kind/$name (exists as real file/dir, not replacing): $dst" >&2
                return 1
            fi
            ln -sfn "$src" "$dst"
            echo "  link   $kind/$name → $src"
            ;;
        remove)
            if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
                rm "$dst"
                echo "  unlink $kind/$name"
            else
                echo "  skip   $kind/$name (not our symlink)"
            fi
            ;;
    esac
}

# retire_skill <name> — drop a stale ~/.claude/skills/<name> symlink that points into
# this devflow repo (left behind when a skill was removed). Only touches our own symlinks.
retire_skill() {
    local name=$1
    local dst="$HOME/.claude/skills/$name"
    [ -L "$dst" ] || return 0
    [ "$(readlink "$dst")" = "$DEVFLOW_DIR/skills/$name" ] || return 0
    if [ "$mode" = "check" ]; then
        echo "  RETIRE $name (stale devflow symlink → would remove)"
    else
        rm "$dst"
        echo "  retire $name (stale devflow symlink removed)"
    fi
}

echo "devflow: $mode"
echo ""

echo "skills:"
for s in "${SKILLS[@]}"; do
    link_item skills "$s"
done
for s in "${OPTIONAL_SKILLS[@]}"; do
    [ -d "$DEVFLOW_DIR/skills/$s" ] && link_item skills "$s"
done

echo ""
echo "agents:"
for a in "${AGENTS[@]}"; do
    link_item agents "$a"
done

echo ""
echo "retired:"
for s in "${RETIRED_SKILLS[@]}"; do
    retire_skill "$s"
done

echo ""
case "$mode" in
    install) echo "✓ Done. Skills: ${SKILLS[*]}  ·  Agents: ${AGENTS[*]}" ;;
    check)   echo "(check mode — no changes made)" ;;
    remove)  echo "✓ Removed devflow skills and agents from ~/.claude/" ;;
esac
