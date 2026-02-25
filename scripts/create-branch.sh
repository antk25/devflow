#!/bin/bash
# create-branch.sh — Creates a branch with proper naming conventions
#
# Usage: ./scripts/create-branch.sh <type> <name> <repo_path> [--work] [--worktree]
#   type       — branch type: feature, fix, refactor
#   name       — branch name/slug (e.g., "user-authentication" or "DEV-488")
#   repo_path  — absolute path to git repository
#   --work     — append "-work" suffix (for /develop two-branch strategy)
#   --worktree — create a git worktree instead of switching branches
#                Worktree is created at <repo_path>/.claude/worktrees/<branch-slug>
#
# Reads branch_prefix from project config if available.
#
# Output:
#   Line 1: Created branch name (always)
#   Line 2: WORKTREE_PATH=<path> (only when --worktree is used)
#
# Exit codes:
#   0 = success (branch created)
#   1 = invalid arguments
#   2 = not a git repository
#   3 = branch already exists

set -euo pipefail

TYPE="${1:-}"
NAME="${2:-}"
REPO_PATH="${3:-}"
WORK_SUFFIX=""
USE_WORKTREE=false

# Check for flags in any position
for arg in "$@"; do
    if [ "$arg" = "--work" ]; then
        WORK_SUFFIX="-work"
    fi
    if [ "$arg" = "--worktree" ]; then
        USE_WORKTREE=true
    fi
done

if [ -z "$TYPE" ] || [ -z "$NAME" ] || [ -z "$REPO_PATH" ]; then
    echo "ERROR: All arguments are required" >&2
    echo "HINT: Usage: ./scripts/create-branch.sh <type> <name> <repo_path> [--work] [--worktree]" >&2
    echo "HINT: Types: feature, fix, refactor" >&2
    echo "HINT: Example: ./scripts/create-branch.sh feature user-auth /path/to/repo --work --worktree" >&2
    exit 1
fi

if [ ! -d "$REPO_PATH/.git" ]; then
    echo "ERROR: Not a git repository: $REPO_PATH" >&2
    echo "HINT: Check the path — it should point to the root of a git repo" >&2
    exit 2
fi

# Check for dirty working tree (only relevant when not using worktree)
if [ "$USE_WORKTREE" = false ]; then
    DIRTY=$(git -C "$REPO_PATH" status --porcelain 2>/dev/null | head -1)
    if [ -n "$DIRTY" ]; then
        echo "WARNING: Working tree has uncommitted changes" >&2
        echo "HINT: Consider committing or stashing before creating a new branch" >&2
    fi
fi

# Determine branch prefix from type
case "$TYPE" in
    feature) PREFIX="feature/" ;;
    fix)     PREFIX="fix/" ;;
    refactor) PREFIX="refactor/" ;;
    *)
        echo "ERROR: Unknown branch type: $TYPE" >&2
        echo "HINT: Valid types: feature, fix, refactor" >&2
        exit 1
        ;;
esac

# Build branch name
# If name already contains the prefix pattern (e.g., DEV-488), use as-is with suffix
if echo "$NAME" | grep -qE '^[A-Z]+-[0-9]+'; then
    BRANCH="${NAME}${WORK_SUFFIX}"
else
    BRANCH="${PREFIX}${NAME}${WORK_SUFFIX}"
fi

# Check if branch already exists
if git -C "$REPO_PATH" rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
    echo "ERROR: Branch already exists: $BRANCH" >&2
    echo "HINT: To switch to it: git -C $REPO_PATH checkout $BRANCH" >&2
    echo "HINT: To delete and recreate: git -C $REPO_PATH branch -D $BRANCH" >&2
    exit 3
fi

if [ "$USE_WORKTREE" = true ]; then
    # Create worktree — main workspace stays on current branch
    WORKTREE_SLUG=$(echo "$BRANCH" | tr '/' '-')
    WORKTREE_DIR="$REPO_PATH/.claude/worktrees/$WORKTREE_SLUG"

    mkdir -p "$(dirname "$WORKTREE_DIR")"
    git -C "$REPO_PATH" worktree add "$WORKTREE_DIR" -b "$BRANCH" --quiet

    echo "$BRANCH"
    echo "WORKTREE_PATH=$WORKTREE_DIR"
    echo "---" >&2
    echo "CREATED: $BRANCH (worktree in $(basename "$REPO_PATH"))" >&2
    echo "WORKTREE: $WORKTREE_DIR" >&2
    echo "BASE: $(git -C "$WORKTREE_DIR" log --oneline -1)" >&2
else
    # Standard branch creation — switches current working tree
    # Ensure we're on main/master before branching
    MAIN_BRANCH=$(git -C "$REPO_PATH" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo "")
    if [ -z "$MAIN_BRANCH" ]; then
        # Fallback: check for main or master
        if git -C "$REPO_PATH" rev-parse --verify main >/dev/null 2>&1; then
            MAIN_BRANCH="main"
        elif git -C "$REPO_PATH" rev-parse --verify master >/dev/null 2>&1; then
            MAIN_BRANCH="master"
        fi
    fi

    CURRENT=$(git -C "$REPO_PATH" branch --show-current 2>/dev/null || echo "")
    if [ -n "$MAIN_BRANCH" ] && [ "$CURRENT" != "$MAIN_BRANCH" ]; then
        echo "NOTE: Currently on '$CURRENT', creating branch from '$MAIN_BRANCH'" >&2
        git -C "$REPO_PATH" checkout "$MAIN_BRANCH" --quiet 2>/dev/null || true
    fi

    # Create and switch to new branch
    git -C "$REPO_PATH" checkout -b "$BRANCH" --quiet

    echo "$BRANCH"
    echo "---" >&2
    echo "CREATED: $BRANCH (in $(basename "$REPO_PATH"))" >&2
    echo "BASE: $(git -C "$REPO_PATH" log --oneline -1)" >&2
fi
