#!/bin/bash
# start.sh — DevFlow launcher
# Shows interactive project selection menu, then launches Claude Code.
#
# Usage:
#   ./start.sh                        # interactive gum menu → claude
#   ./start.sh <project>              # direct project switch → claude
#   ./start.sh <project> <phase>      # phase picks the model (see below)
#   ./start.sh --current [phase]      # skip menu, use current active project
#
# <phase> maps to a session model:
#   research | plan | review  → opus    (deep reasoning)
#   implement | quick         → sonnet  (writing / edits)
# Omit <phase> to launch with your default model (interactive menu asks if gum is present).
#
# Reads/writes the project registry in .claude/data/projects.json (v3.0 schema).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECTS_FILE="$SCRIPT_DIR/.claude/data/projects.json"
GUM="${GUM:-$(command -v gum 2>/dev/null || echo "$HOME/bin/gum")}"

py() { python3 -c "$1" 2>/dev/null; }

# Map a devflow phase to the model its session should run on.
# research/plan/review = deep reasoning → opus; implement/quick = writing/edits → sonnet.
phase_to_model() {
    case "$1" in
        research|plan|review)  echo "opus" ;;
        implement|impl|quick)  echo "sonnet" ;;
        *)                     echo "" ;;
    esac
}

get_active() {
    py "
import json
print(json.load(open('$PROJECTS_FILE')).get('active') or '')
"
}

get_path() {
    py "
import json
p = json.load(open('$PROJECTS_FILE'))['projects'].get('$1', {})
print(p.get('path') or '')
"
}

set_active() {
    py "
import json
with open('$PROJECTS_FILE','r+') as f:
    d = json.load(f)
    d['active'] = '$1'
    f.seek(0); json.dump(d, f, indent=2, ensure_ascii=False); f.truncate()
"
}

read_projects() {
    py "
import json
d = json.load(open('$PROJECTS_FILE'))
active = d.get('active') or ''
for name, p in d.get('projects', {}).items():
    marker = ' *' if name == active else ''
    desc = (p.get('description') or '')[:60]
    print(f'{name}\t{desc}{marker}')
"
}

validate_project() {
    py "
import json
d = json.load(open('$PROJECTS_FILE'))
print('yes' if '$1' in d.get('projects', {}) else 'no')
"
}

# --- Preflight ---

if [ ! -f "$PROJECTS_FILE" ]; then
    echo "ERROR: projects.json not found at $PROJECTS_FILE" >&2
    exit 1
fi

# --- Parse args ---

SELECTED=""

if [ $# -ge 1 ]; then
    case "$1" in
        --current|-c)
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
                read_projects | while IFS=$'\t' read -r name desc; do
                    echo "  - $name"
                done
                exit 1
            fi
            ;;
    esac
fi

PHASE="${2:-}"

# --- Interactive menu ---

if [ -z "$SELECTED" ]; then
    if [ ! -x "$GUM" ]; then
        echo "ERROR: gum not found. Install: https://github.com/charmbracelet/gum" >&2
        echo "Or specify project directly: ./start.sh <project-name>" >&2
        exit 1
    fi

    ACTIVE=$(get_active)

    items=$(read_projects | sort -t$'\t' -k1,1 | while IFS=$'\t' read -r name desc; do
        if [ "$name" = "$ACTIVE" ]; then
            echo "► $name  $desc"
        else
            echo "  $name  $desc"
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

# --- Switch active project ---

ACTIVE=$(get_active)
if [ "$SELECTED" != "$ACTIVE" ]; then
    set_active "$SELECTED"
    echo "Switched to: $SELECTED"
else
    echo "Active project: $SELECTED"
fi

# --- Launch Claude Code ---

PROJECT_PATH=$(get_path "$SELECTED")

if [ -z "$PROJECT_PATH" ] || [ ! -d "$PROJECT_PATH" ]; then
    echo "ERROR: project path missing or invalid: $PROJECT_PATH" >&2
    exit 1
fi

if [ ! -f "$PROJECT_PATH/AGENTS.md" ]; then
    echo ""
    echo "⚠  $SELECTED has no AGENTS.md."
    echo "   Copy template: cp $SCRIPT_DIR/AGENTS.md.template $PROJECT_PATH/AGENTS.md"
    echo ""
    read -rp "Launch anyway? [y/N] " answer
    if [[ ! "$answer" =~ ^[Yy]$ ]]; then
        exit 0
    fi
fi

# --- Resolve session model from phase ---

if [ -z "$PHASE" ] && [ -x "$GUM" ]; then
    phase_pick=$("$GUM" choose --header "Phase → model:" \
        "research   → opus" \
        "plan       → opus" \
        "implement  → sonnet" \
        "quick      → sonnet" \
        "review     → opus" \
        "(default model)") || phase_pick=""
    case "$phase_pick" in
        research*)  PHASE="research" ;;
        plan*)      PHASE="plan" ;;
        implement*) PHASE="implement" ;;
        quick*)     PHASE="quick" ;;
        review*)    PHASE="review" ;;
        *)          PHASE="" ;;
    esac
fi

MODEL=$(phase_to_model "$PHASE")
if [ -n "$PHASE" ] && [ -z "$MODEL" ]; then
    echo "⚠  Unknown phase '$PHASE' — launching with default model." >&2
fi

cd "$PROJECT_PATH"
[ -n "$PHASE" ] && export DEVFLOW_PHASE="$PHASE"

if [ -n "$MODEL" ]; then
    echo "Launching Claude Code for $SELECTED on '$MODEL' (path: $PROJECT_PATH)..."
    echo ""
    exec claude --model "$MODEL"
else
    echo "Launching Claude Code for $SELECTED (path: $PROJECT_PATH)..."
    echo ""
    exec claude
fi
