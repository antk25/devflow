#!/bin/bash
# start.sh — Dev Orchestrator launcher
# Shows interactive project selection menu, then launches Claude Code.
#
# Usage:
#   ./start.sh              # interactive gum menu → claude
#   ./start.sh <project>    # direct project switch → claude
#   ./start.sh --current    # skip menu, use current active project
#
# The selected project becomes active in projects.json.
# SessionStart hook in Claude Code reads it and restores context.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECTS_FILE="$SCRIPT_DIR/.claude/data/projects.json"
GUM="${GUM:-$(command -v gum 2>/dev/null || echo "$HOME/bin/gum")}"

# --- Helpers ---

get_active() {
    python3 -c "
import json
with open('$PROJECTS_FILE') as f:
    data = json.load(f)
print(data.get('active', '') or '')
" 2>/dev/null
}

get_project_field() {
    local project="$1" field="$2"
    python3 -c "
import json
with open('$PROJECTS_FILE') as f:
    data = json.load(f)
p = data['projects'].get('$project', {})
keys = '$field'.split('.')
val = p
for k in keys:
    if isinstance(val, dict):
        val = val.get(k, '')
    else:
        val = ''
        break
print(val or '')
" 2>/dev/null
}

set_active() {
    local project="$1"
    python3 -c "
import json
with open('$PROJECTS_FILE', 'r+') as f:
    data = json.load(f)
    data['active'] = '$project'
    f.seek(0)
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.truncate()
" 2>/dev/null
}

read_projects() {
    python3 -c "
import json
with open('$PROJECTS_FILE') as f:
    data = json.load(f)
active = data.get('active', '') or ''
for name, p in data.get('projects', {}).items():
    marker = ' *' if name == active else ''
    ptype = p.get('type', 'unknown')
    desc = p.get('description', '')[:60]
    print(f'{name}\t{ptype}\t{desc}{marker}')
" 2>/dev/null
}

validate_project() {
    local project="$1"
    python3 -c "
import json
with open('$PROJECTS_FILE') as f:
    data = json.load(f)
print('yes' if '$project' in data.get('projects', {}) else 'no')
" 2>/dev/null
}

# --- Preflight ---

if [ ! -f "$PROJECTS_FILE" ]; then
    echo "ERROR: projects.json not found at $PROJECTS_FILE" >&2
    exit 1
fi

# --- Parse args ---

SELECTED=""
SKIP_MENU=false

if [ $# -ge 1 ]; then
    case "$1" in
        --current|-c)
            SKIP_MENU=true
            SELECTED=$(get_active)
            if [ -z "$SELECTED" ]; then
                echo "No active project set. Run without --current to select one." >&2
                exit 1
            fi
            ;;
        *)
            SELECTED="$1"
            if [ "$(validate_project "$SELECTED")" != "yes" ]; then
                echo "ERROR: Project '$SELECTED' not found in registry" >&2
                echo ""
                echo "Available projects:"
                read_projects | while IFS=$'\t' read -r name ptype desc; do
                    echo "  - $name ($ptype)"
                done
                exit 1
            fi
            ;;
    esac
fi

# --- Interactive menu ---

if [ -z "$SELECTED" ]; then
    if [ ! -x "$GUM" ]; then
        echo "ERROR: gum not found. Install: https://github.com/charmbracelet/gum" >&2
        echo "Or specify project directly: ./start.sh <project-name>" >&2
        exit 1
    fi

    ACTIVE=$(get_active)

    # Build formatted list: active first, then alphabetical
    items=$(read_projects | sort -t$'\t' -k1,1 | while IFS=$'\t' read -r name ptype desc; do
        if [ "$name" = "$ACTIVE" ]; then
            echo "► $name  ($ptype)  $desc"
        else
            echo "  $name  ($ptype)  $desc"
        fi
    done)

    active_line=$(echo "$items" | grep "^►" || true)
    other_lines=$(echo "$items" | grep -v "^►" || true)
    sorted_items=""
    [ -n "$active_line" ] && sorted_items="$active_line"
    if [ -n "$other_lines" ]; then
        [ -n "$sorted_items" ] && sorted_items="$sorted_items"$'\n'"$other_lines" || sorted_items="$other_lines"
    fi

    chosen=$("$GUM" choose --header "Select project:" --cursor "→ " <<< "$sorted_items") || {
        echo "Cancelled."
        exit 0
    }

    SELECTED=$(echo "$chosen" | sed 's/^[► ] *//' | awk '{print $1}')
fi

# --- Switch project ---

ACTIVE=$(get_active)

if [ "$SELECTED" != "$ACTIVE" ]; then
    # Docker stop previous
    if [ -n "$ACTIVE" ]; then
        docker_stop=$(get_project_field "$ACTIVE" "docker.stop")
        if [ -n "$docker_stop" ]; then
            echo "Stopping $ACTIVE containers..."
            eval "$docker_stop" >/dev/null 2>&1 &
        fi
    fi

    # Update active
    set_active "$SELECTED"

    # Docker start new
    docker_start=$(get_project_field "$SELECTED" "docker.start")
    if [ -n "$docker_start" ]; then
        echo "Starting $SELECTED containers..."
        eval "$docker_start" >/dev/null 2>&1 &
    fi

    echo "Switched to: $SELECTED"
else
    echo "Active project: $SELECTED"
fi

# --- Launch Claude Code ---

PROJECT_PATH=$(get_project_field "$SELECTED" "path")
echo "Launching Claude Code in $PROJECT_PATH..."
echo ""

cd "$PROJECT_PATH"
exec claude
