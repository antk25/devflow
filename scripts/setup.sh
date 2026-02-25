#!/bin/bash
# setup.sh — Initialize local configuration from templates
#
# Usage: ./scripts/setup.sh
#
# What it does:
#   1. Generates .mcp.json from .mcp.json.example (replaces __PROJECT_ROOT__)
#   2. Generates .claude/settings.json from .claude/settings.json.example
#   3. Creates empty .claude/data/ runtime files if they don't exist
#   4. Optionally sets obsidian_vault path in projects.json
#
# Safe to re-run — never overwrites existing files.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Setting up DevFlow..."
echo "Project root: $PROJECT_ROOT"
echo ""

# --- Helper ---
generate_from_template() {
    local template="$1"
    local target="$2"
    local description="$3"

    if [ -f "$target" ]; then
        echo "  [skip] $description — already exists"
        return 0
    fi

    if [ ! -f "$template" ]; then
        echo "  [error] $description — template not found: $template" >&2
        return 1
    fi

    sed "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" "$template" > "$target"
    echo "  [created] $description"
}

create_if_missing() {
    local template="$1"
    local target="$2"
    local description="$3"

    if [ -f "$target" ]; then
        echo "  [skip] $description — already exists"
        return 0
    fi

    if [ -f "$template" ]; then
        cp "$template" "$target"
        echo "  [created] $description (from template)"
    else
        echo "  [error] $description — template not found: $template" >&2
        return 1
    fi
}

# --- Step 1: MCP config ---
echo "1. MCP configuration"
generate_from_template \
    "$PROJECT_ROOT/.mcp.json.example" \
    "$PROJECT_ROOT/.mcp.json" \
    ".mcp.json"

# --- Step 2: Claude settings (hooks + permissions) ---
echo ""
echo "2. Claude Code settings"
generate_from_template \
    "$PROJECT_ROOT/.claude/settings.json.example" \
    "$PROJECT_ROOT/.claude/settings.json" \
    ".claude/settings.json"

# --- Step 3: Runtime data files ---
echo ""
echo "3. Runtime data files"
mkdir -p "$PROJECT_ROOT/.claude/data"

create_if_missing \
    "$PROJECT_ROOT/.claude/data/projects.json.example" \
    "$PROJECT_ROOT/.claude/data/projects.json" \
    ".claude/data/projects.json"

create_if_missing \
    "$PROJECT_ROOT/.claude/data/sessions.json.example" \
    "$PROJECT_ROOT/.claude/data/sessions.json" \
    ".claude/data/sessions.json"

create_if_missing \
    "$PROJECT_ROOT/.claude/data/queue.json.example" \
    "$PROJECT_ROOT/.claude/data/queue.json" \
    ".claude/data/queue.json"

# --- Step 4: Update projects.json with actual path ---
echo ""
echo "4. Updating project paths"
PROJECTS_FILE="$PROJECT_ROOT/.claude/data/projects.json"
if [ -f "$PROJECTS_FILE" ]; then
    python3 -c "
import json

with open('$PROJECTS_FILE') as f:
    data = json.load(f)

root = '$PROJECT_ROOT'

# Update the devflow entry with actual path
if 'devflow' in data.get('projects', {}):
    p = data['projects']['devflow']
    p['path'] = root
    p['repositories'] = {'main': root}

with open('$PROJECTS_FILE', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write('\n')

print(f'  [updated] devflow path -> {root}')
" 2>/dev/null || echo "  [skip] Could not update paths (python3 required)"
fi

# --- Step 5: Install MCP server dependencies ---
echo ""
echo "5. MCP server dependencies"
if [ -f "$PROJECT_ROOT/mcp-servers/qwen-review/package.json" ]; then
    if [ ! -d "$PROJECT_ROOT/mcp-servers/qwen-review/node_modules" ]; then
        echo "  Installing qwen-review dependencies..."
        (cd "$PROJECT_ROOT/mcp-servers/qwen-review" && npm install --silent 2>/dev/null)
        echo "  [installed] qwen-review"
    else
        echo "  [skip] qwen-review — node_modules exists"
    fi
fi

# --- Done ---
echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .claude/data/projects.json to add your projects"
echo "  2. (Optional) Set obsidian_vault path in projects.json"
echo "  3. Run: claude  (to start Claude Code in this directory)"
