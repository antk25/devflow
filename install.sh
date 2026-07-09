#!/usr/bin/env bash
# devflow installer — symlinks devflow skills into ~/.claude/skills/
#
# Usage:
#   ./install.sh           # install/update symlinks
#   ./install.sh --check   # show what would change without doing it
#   ./install.sh --remove  # remove devflow skills from ~/.claude/skills/

set -euo pipefail

DEVFLOW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_SKILLS_DIR="$HOME/.claude/skills"

# Skills shipped by devflow (directory names under skills/)
SKILLS=(research plan implement quick note project)

# Optional skills (installed if present)
OPTIONAL_SKILLS=(autoresearch)

mode="install"
case "${1:-}" in
    --check)  mode="check" ;;
    --remove) mode="remove" ;;
    "")       mode="install" ;;
    *) echo "Usage: $0 [--check|--remove]"; exit 1 ;;
esac

mkdir -p "$CLAUDE_SKILLS_DIR"

link_skill() {
    local name=$1
    local src="$DEVFLOW_DIR/skills/$name"
    local dst="$CLAUDE_SKILLS_DIR/$name"

    if [ ! -d "$src" ]; then
        echo "  skip   $name (no source: $src)"
        return
    fi

    case "$mode" in
        check)
            if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
                echo "  ok     $name → $src"
            elif [ -e "$dst" ]; then
                echo "  CONFL  $name (exists, not our symlink): $dst"
            else
                echo "  MISS   $name (would link → $src)"
            fi
            ;;
        install)
            if [ -e "$dst" ] && [ ! -L "$dst" ]; then
                echo "  CONFL  $name (exists as real file/dir, not replacing): $dst" >&2
                return 1
            fi
            ln -sfn "$src" "$dst"
            echo "  link   $name → $src"
            ;;
        remove)
            if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
                rm "$dst"
                echo "  unlink $name"
            else
                echo "  skip   $name (not our symlink)"
            fi
            ;;
    esac
}

echo "devflow: $mode @ $CLAUDE_SKILLS_DIR"
echo ""

for s in "${SKILLS[@]}"; do
    link_skill "$s"
done

echo ""
for s in "${OPTIONAL_SKILLS[@]}"; do
    [ -d "$DEVFLOW_DIR/skills/$s" ] && link_skill "$s"
done

echo ""
case "$mode" in
    install) echo "✓ Done. Skills: ${SKILLS[*]}" ;;
    check)   echo "(check mode — no changes made)" ;;
    remove)  echo "✓ Removed devflow skills from $CLAUDE_SKILLS_DIR" ;;
esac
