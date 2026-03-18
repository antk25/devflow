#!/bin/bash
# devflow-setup.sh — Install/update DevFlow skills and configure projects
#
# Usage:
#   devflow-setup.sh install          # Install devflow skills to ~/.claude/skills/
#   devflow-setup.sh update           # Same as install (idempotent)
#   devflow-setup.sh project <name>   # Configure a registered project for devflow
#   devflow-setup.sh status           # Show current installation status
#   devflow-setup.sh uninstall        # Remove devflow skills from ~/.claude/skills/
#
# What "install" does:
#   1. Copies devflow skills to ~/.claude/skills/ (user-level, available in all projects)
#   2. Installs devflow-instructions.md to ~/.claude/
#   3. Adds @devflow-instructions.md to ~/.claude/CLAUDE.md (if not already there)
#
# What "project <name>" does:
#   1. Generates .claude/settings.json with hooks pointing to devflow (absolute paths)
#   2. Generates .mcp.json with MCP servers pointing to devflow
#   3. Creates .claude/data/ directory for runtime data
#   4. Adds devflow artifacts to .gitignore

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEVFLOW_DIR="$(dirname "$SCRIPT_DIR")"
PROJECTS_FILE="$DEVFLOW_DIR/.claude/data/projects.json"
USER_CLAUDE_DIR="$HOME/.claude"
USER_SKILLS_DIR="$USER_CLAUDE_DIR/skills"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}→${NC} $1"; }
ok()    { echo -e "${GREEN}✓${NC} $1"; }
warn()  { echo -e "${YELLOW}!${NC} $1"; }
err()   { echo -e "${RED}✗${NC} $1" >&2; }

# --- Helpers ---

get_project_path() {
    local project="$1"
    python3 -c "
import json
with open('$PROJECTS_FILE') as f:
    data = json.load(f)
p = data['projects'].get('$project', {})
print(p.get('path', ''))
" 2>/dev/null
}

list_projects() {
    python3 -c "
import json
with open('$PROJECTS_FILE') as f:
    data = json.load(f)
for name in sorted(data.get('projects', {}).keys()):
    print(name)
" 2>/dev/null
}

# --- Commands ---

cmd_install() {
    echo ""
    echo "DevFlow Setup — Installing user-level skills"
    echo "============================================="
    echo ""

    # 1. Copy skills
    info "Installing skills to $USER_SKILLS_DIR/"
    mkdir -p "$USER_SKILLS_DIR"

    local count=0
    for skill_dir in "$DEVFLOW_DIR/.claude/skills"/*/; do
        [ -d "$skill_dir" ] || continue
        local name=$(basename "$skill_dir")

        # Skip if project has a local override (don't overwrite)
        if [ -d "$USER_SKILLS_DIR/$name" ] && [ -f "$USER_SKILLS_DIR/$name/.project-override" ]; then
            warn "Skipping $name (has .project-override marker)"
            continue
        fi

        rm -r "$USER_SKILLS_DIR/$name" 2>/dev/null || true
        cp -r "$skill_dir" "$USER_SKILLS_DIR/$name"
        # Mark as devflow-managed
        echo "devflow" > "$USER_SKILLS_DIR/$name/.devflow-managed"
        count=$((count + 1))
    done
    ok "Installed $count skills"

    # 2. Install devflow instructions
    info "Installing devflow-instructions.md"
    generate_instructions > "$USER_CLAUDE_DIR/devflow-instructions.md"
    ok "Written to $USER_CLAUDE_DIR/devflow-instructions.md"

    # 3. Add @include to CLAUDE.md
    local claude_md="$USER_CLAUDE_DIR/CLAUDE.md"
    if [ -f "$claude_md" ]; then
        if ! grep -q "@devflow-instructions.md" "$claude_md"; then
            info "Adding @devflow-instructions.md to CLAUDE.md"
            # Prepend before existing content
            local tmp=$(mktemp)
            echo "@devflow-instructions.md" > "$tmp"
            cat "$claude_md" >> "$tmp"
            mv "$tmp" "$claude_md"
            ok "Added @include"
        else
            ok "CLAUDE.md already includes devflow-instructions.md"
        fi
    else
        echo "@devflow-instructions.md" > "$claude_md"
        ok "Created CLAUDE.md with @include"
    fi

    echo ""
    ok "Done! Skills will be available in the next claude session."
    echo ""
    echo "  Next steps:"
    echo "    devflow-setup.sh project <name>  — configure a project"
    echo "    devflow-setup.sh status          — check installation"
    echo ""
}

cmd_project() {
    local project="${1:?Usage: devflow-setup.sh project <name>}"

    local project_path=$(get_project_path "$project")
    if [ -z "$project_path" ]; then
        err "Project '$project' not found in projects.json"
        echo ""
        echo "Available projects:"
        list_projects | sed 's/^/  - /'
        exit 1
    fi

    if [ ! -d "$project_path" ]; then
        err "Project path does not exist: $project_path"
        exit 1
    fi

    echo ""
    echo "DevFlow Setup — Configuring project: $project"
    echo "=============================================="
    echo "Path: $project_path"
    echo ""

    local claude_dir="$project_path/.claude"
    mkdir -p "$claude_dir"

    # 1. Generate settings.json (hooks + permissions)
    if [ -f "$claude_dir/settings.json" ]; then
        warn "settings.json already exists — backing up to settings.json.bak"
        cp "$claude_dir/settings.json" "$claude_dir/settings.json.bak"
    fi

    info "Generating settings.json (hooks → devflow)"
    generate_settings > "$claude_dir/settings.json"
    ok "Written settings.json"

    # 2. Generate .mcp.json
    local mcp_file="$project_path/.mcp.json"
    if [ -f "$mcp_file" ]; then
        warn ".mcp.json already exists — skipping (remove to regenerate)"
    else
        info "Generating .mcp.json (MCP servers → devflow)"
        generate_mcp > "$mcp_file"
        ok "Written .mcp.json"
    fi

    # 3. Create data directory
    mkdir -p "$claude_dir/data"
    ok "Created .claude/data/"

    # 4. Create agents directory
    mkdir -p "$claude_dir/agents"
    ok "Created .claude/agents/"

    # 5. Update .gitignore
    update_gitignore "$project_path"

    echo ""
    ok "Project '$project' configured!"
    echo ""
    echo "  Next steps:"
    echo "    Generate project agents: cd $project_path && claude '/project agents'"
    echo "    Start working:           ./start.sh $project"
    echo ""
}

cmd_status() {
    echo ""
    echo "DevFlow Installation Status"
    echo "==========================="
    echo ""

    # Skills
    echo "Skills ($USER_SKILLS_DIR/):"
    if [ -d "$USER_SKILLS_DIR" ]; then
        local devflow_count=0
        local custom_count=0
        for skill_dir in "$USER_SKILLS_DIR"/*/; do
            [ -d "$skill_dir" ] || continue
            local name=$(basename "$skill_dir")
            if [ -f "$skill_dir/.devflow-managed" ]; then
                echo -e "  ${GREEN}✓${NC} $name (devflow)"
                devflow_count=$((devflow_count + 1))
            else
                echo -e "  ${BLUE}●${NC} $name (custom)"
                custom_count=$((custom_count + 1))
            fi
        done
        [ $devflow_count -eq 0 ] && [ $custom_count -eq 0 ] && echo "  (empty)"
        echo "  Total: $devflow_count devflow, $custom_count custom"
    else
        echo "  (not installed)"
    fi
    echo ""

    # CLAUDE.md
    echo "CLAUDE.md ($USER_CLAUDE_DIR/CLAUDE.md):"
    if [ -f "$USER_CLAUDE_DIR/CLAUDE.md" ]; then
        if grep -q "@devflow-instructions.md" "$USER_CLAUDE_DIR/CLAUDE.md"; then
            ok "Has @devflow-instructions.md include"
        else
            warn "Missing @devflow-instructions.md include"
        fi
    else
        warn "File does not exist"
    fi
    echo ""

    # Instructions file
    echo "Instructions ($USER_CLAUDE_DIR/devflow-instructions.md):"
    if [ -f "$USER_CLAUDE_DIR/devflow-instructions.md" ]; then
        local size=$(wc -c < "$USER_CLAUDE_DIR/devflow-instructions.md")
        ok "Exists (${size} bytes)"
    else
        warn "Not installed"
    fi
    echo ""

    # Projects
    echo "Configured projects:"
    for proj in $(list_projects); do
        local ppath=$(get_project_path "$proj")
        local has_settings="✗"
        local has_agents="✗"
        local has_mcp="✗"

        [ -f "$ppath/.claude/settings.json" ] && has_settings="✓"
        [ -d "$ppath/.claude/agents" ] && [ "$(ls -A "$ppath/.claude/agents" 2>/dev/null)" ] && has_agents="✓"
        [ -f "$ppath/.mcp.json" ] && has_mcp="✓"

        echo "  $proj: settings=$has_settings agents=$has_agents mcp=$has_mcp"
    done
    echo ""
}

cmd_uninstall() {
    echo ""
    echo "DevFlow Uninstall"
    echo "================="
    echo ""

    # Remove devflow-managed skills only
    if [ -d "$USER_SKILLS_DIR" ]; then
        local count=0
        for skill_dir in "$USER_SKILLS_DIR"/*/; do
            [ -d "$skill_dir" ] || continue
            if [ -f "$skill_dir/.devflow-managed" ]; then
                local name=$(basename "$skill_dir")
                rm -r "$skill_dir"
                info "Removed skill: $name"
                count=$((count + 1))
            fi
        done
        ok "Removed $count devflow skills (custom skills preserved)"
    fi

    # Remove instructions
    if [ -f "$USER_CLAUDE_DIR/devflow-instructions.md" ]; then
        rm "$USER_CLAUDE_DIR/devflow-instructions.md"
        ok "Removed devflow-instructions.md"
    fi

    # Remove @include from CLAUDE.md (but keep the file)
    if [ -f "$USER_CLAUDE_DIR/CLAUDE.md" ]; then
        if grep -q "@devflow-instructions.md" "$USER_CLAUDE_DIR/CLAUDE.md"; then
            grep -v "@devflow-instructions.md" "$USER_CLAUDE_DIR/CLAUDE.md" > "$USER_CLAUDE_DIR/CLAUDE.md.tmp"
            mv "$USER_CLAUDE_DIR/CLAUDE.md.tmp" "$USER_CLAUDE_DIR/CLAUDE.md"
            ok "Removed @include from CLAUDE.md"
        fi
    fi

    echo ""
    ok "Uninstalled. Project configs (.claude/settings.json) are NOT removed."
    echo ""
}

# --- Generators ---

generate_instructions() {
    cat << 'INSTRUCTIONS'
# DevFlow — Development Orchestration

## Auto-Routing (Smart Task Dispatch)

When the user sends a task description **without a slash command**, analyze the intent and invoke the appropriate skill automatically. Do NOT ask which command to use — route it yourself.

### Routing Matrix (priority order, first match wins)

| Priority | Route | Signals |
|----------|-------|---------|
| 1 | `/fix` | Bug, error, broken, crash, regression, "не работает", "ошибка" |
| 2 | `/investigate` | WHY something happens, unclear cause, "почему", "разобраться" |
| 3 | `/explore` | Vague idea, compare approaches, "как лучше", "варианты" |
| 4 | `/refactor` | Improve without behavior change, "вынести", "упростить" |
| 5 | `/review` | Review code/PR, "ревью", "проверь код" |
| 6 | `/audit` | Documentation accuracy, "аудит", "документация устарела" |
| 7 | `/develop` | New feature, "добавить", "реализовать", "сделать" |

### Rules
- Questions about code → answer directly, don't route
- Explicit slash command → use that command, don't re-route
- Ambiguous → ask user with 2 options

## Project Auto-Restore (SessionStart Hook)

When you see `PROJECT_RESTORE` in hook output:
1. Read fields: `name`, `type`, `path`
2. Show in greeting: `**Active project:** <name>`
3. If `INTERRUPTED_SESSION` → show resume prompt
4. If `OBSIDIAN_CONTEXT` → show active contracts/TZ count

## Available Commands

`/develop` · `/fix` · `/refactor` · `/explore` · `/investigate` · `/review`
`/finalize` · `/audit` · `/note` · `/resume` · `/recall` · `/next` · `/project`

## Agent Selection

When using Task tool to spawn agents, use these identifiers:
- `Project Manager` — requirements and planning
- `Architect` — architecture design
- `JS Developer` — JavaScript/TypeScript
- `PHP Developer` — PHP/Laravel/Symfony
- `Tester` — QA/testing
- `Debugger` — root cause analysis
- `Code Reviewer` — security, performance, quality (runs on opus)
- `Architecture Guardian` — pattern validation

## Project-Specific Agents

Projects can define agents in `<project>/.claude/agents/`. Resolution order:
1. `<project>/.claude/agents/<specific>.md` (e.g., php-developer.md)
2. `<project>/.claude/agents/developer.md` (generic)
3. DevFlow default agents

## Conventions

- **Test Isolation**: Only Tester agent can write tests. Developer agents fix implementation, never tests.
- **Git**: Auto branches/commits per workflow. Never pushes (manual only). `git push` and `gh` blocked.
- **Type Propagation**: When changing types, trace through ALL layers (callers, consumers, HTTP boundary).
INSTRUCTIONS
}

generate_settings() {
    cat << EOF
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$DEVFLOW_DIR/.claude/hooks/rag-reindex-check.sh",
            "timeout": 30,
            "statusMessage": "Checking RAG knowledge base for updates..."
          },
          {
            "type": "command",
            "command": "$DEVFLOW_DIR/.claude/hooks/project-restore.sh",
            "timeout": 10,
            "statusMessage": "Restoring project context..."
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "$DEVFLOW_DIR/.claude/hooks/auto-approve.sh"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$DEVFLOW_DIR/.claude/hooks/session-end-summarize.sh",
            "timeout": 120,
            "async": true
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$DEVFLOW_DIR/.claude/hooks/precompact-snapshot.sh",
            "timeout": 30,
            "async": true
          }
        ]
      }
    ]
  },
  "permissions": {
    "allow": [
      "Read(*)",
      "Write(*)",
      "Edit(*)",
      "Glob(*)",
      "Grep(*)",
      "Task(*)",
      "Bash(*)",
      "mcp__playwright__*",
      "mcp__context7__*",
      "mcp__chrome-devtools__*",
      "mcp__local-rag__*",
      "mcp__qwen-review__*"
    ],
    "deny": [
      "Bash(git push:*)",
      "Bash(git push *)",
      "Bash(*git push*)",
      "Bash(gh:*)",
      "Bash(gh *)",
      "Bash(*gh *)",
      "Bash(ssh:*)",
      "Bash(ssh *)",
      "Bash(scp:*)",
      "Bash(scp *)",
      "Bash(rsync:*)",
      "Bash(rsync *)",
      "Bash(rm -rf /*)",
      "Bash(rm -rf /)"
    ]
  }
}
EOF
}

generate_mcp() {
    cat << EOF
{
  "mcpServers": {
    "qwen-review": {
      "command": "node",
      "args": ["$DEVFLOW_DIR/mcp-servers/qwen-review/index.js"]
    },
    "chatgpt-review": {
      "command": "node",
      "args": ["$DEVFLOW_DIR/mcp-servers/chatgpt-review/index.js"]
    }
  }
}
EOF
}

update_gitignore() {
    local project_path="$1"
    local gitignore="$project_path/.gitignore"

    local marker="# DevFlow (auto-generated)"
    if [ -f "$gitignore" ] && grep -q "$marker" "$gitignore"; then
        ok ".gitignore already has devflow entries"
        return
    fi

    info "Adding devflow entries to .gitignore"
    cat >> "$gitignore" << 'GITIGNORE'

# DevFlow (auto-generated)
.claude/data/
.claude/settings.json
.mcp.json
GITIGNORE
    ok "Updated .gitignore"
}

# --- Main ---

case "${1:-}" in
    install|update)
        cmd_install
        ;;
    project)
        cmd_project "${2:-}"
        ;;
    status)
        cmd_status
        ;;
    uninstall)
        cmd_uninstall
        ;;
    *)
        echo "DevFlow Setup"
        echo ""
        echo "Usage:"
        echo "  $(basename "$0") install          Install/update devflow skills globally"
        echo "  $(basename "$0") update           Same as install (idempotent)"
        echo "  $(basename "$0") project <name>   Configure a registered project"
        echo "  $(basename "$0") status           Show installation status"
        echo "  $(basename "$0") uninstall        Remove devflow skills"
        echo ""
        echo "Registered projects:"
        list_projects 2>/dev/null | sed 's/^/  - /' || echo "  (none)"
        echo ""
        exit 1
        ;;
esac
