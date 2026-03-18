# Multi-Project Reference

Details on multi-project management, skill distribution, and project setup.

## Architecture Overview

DevFlow uses a **two-tier skill distribution** model:

```
~/.claude/                              ← User-level (shared across ALL projects)
├── skills/                             ← DevFlow skills (installed via setup)
│   ├── develop/SKILL.md
│   ├── fix/SKILL.md
│   └── ... (13 skills)
├── devflow-instructions.md             ← Core instructions (auto-routing, agents, conventions)
└── CLAUDE.md                           ← @devflow-instructions.md + @RTK.md + ...

<project>/.claude/                      ← Project-level (per-project overrides)
├── skills/                             ← Project-specific skills (optional)
│   └── deploy/SKILL.md                 ← Only this project sees this skill
├── agents/                             ← Project-specific agents (generated)
│   ├── php-developer.md
│   └── tester.md
├── settings.json                       ← Hooks pointing to devflow (absolute paths)
└── data/                               ← Runtime data (sessions, etc.)
```

### Skill Priority

Claude Code resolves skills from most specific to least specific:

1. **Project-level** `.claude/skills/develop/` — highest priority (overrides user-level)
2. **User-level** `~/.claude/skills/develop/` — fallback for all projects

This means:
- **Working on devflow itself**: project skills override user-level copies → you always test the latest code
- **Working on other projects**: user-level skills are used (installed via `devflow-setup.sh`)
- **Project-specific skills**: add `<project>/.claude/skills/<name>/SKILL.md` — visible only in that project

### Agent Resolution

Agents are resolved via `scripts/resolve-agent.sh`:

1. `<project>/.claude/agents/<specific>.md` (e.g., `php-developer.md`)
2. `<project>/.claude/agents/developer.md` (generic fallback)
3. DevFlow defaults (`.claude/agents/*.md`)

## Setup

### Initial Installation

Run once after cloning devflow:

```bash
./scripts/devflow-setup.sh install
```

This:
1. Copies 13 devflow skills to `~/.claude/skills/` (marked with `.devflow-managed`)
2. Writes `~/.claude/devflow-instructions.md` (auto-routing, agent selection, conventions)
3. Adds `@devflow-instructions.md` to `~/.claude/CLAUDE.md` (if not already there)

After this, devflow skills are available in **any** Claude Code session, regardless of working directory.

### Configuring a Project

```bash
./scripts/devflow-setup.sh project <name>
# or
./start.sh setup project <name>
```

This generates in the project directory:
- `.claude/settings.json` — hooks (SessionStart, PreToolUse, SessionEnd, PreCompact) pointing to devflow scripts via absolute paths
- `.mcp.json` — MCP servers (qwen-review, chatgpt-review) pointing to devflow
- `.claude/data/` — runtime directory for sessions
- `.claude/agents/` — directory for project-specific agents
- `.gitignore` entries — excludes generated files from version control

### Updating Skills

After modifying skills in devflow:

```bash
./scripts/devflow-setup.sh update
# or
./start.sh setup update
```

Idempotent — re-copies all devflow skills to `~/.claude/skills/`. Custom (non-devflow) skills in `~/.claude/skills/` are preserved.

### Checking Status

```bash
./scripts/devflow-setup.sh status
# or
./start.sh setup status
```

Shows:
- Installed skills (devflow vs custom)
- CLAUDE.md include status
- Per-project configuration status (settings, agents, mcp)

### Uninstalling

```bash
./scripts/devflow-setup.sh uninstall
```

Removes only devflow-managed skills and instructions. Custom skills and project configs are preserved.

## Launcher Script

```bash
./start.sh              # interactive gum menu → select project → launch claude
./start.sh my-app       # switch to my-app → launch claude
./start.sh --current    # keep current project → launch claude
./start.sh setup ...    # passthrough to devflow-setup.sh
```

The launcher:
1. Shows an interactive menu (via `gum choose`) to select a project
2. Handles Docker container lifecycle (stops previous, starts new)
3. Updates `projects.json` active field
4. **For devflow**: launches claude from devflow directory (project skills take priority)
5. **For other projects**: `cd` to project directory, then launches claude (user-level skills apply)
6. Warns if project is not configured (`settings.json` missing)

### Why no in-session switching?

Switching projects inside Claude Code is impractical because:
- The old project's CLAUDE.md, memories, and patterns pollute the context
- A `/clear` is always needed after switching, which defeats the purpose
- Interactive terminal tools (`gum`) don't work in Claude Code hooks (no TTY)

**One session = one project.** To switch projects, exit Claude Code and run `./start.sh` again.

## Project Registry Commands

Inside Claude Code, `/project` manages the registry (without switching):

```
/project list                    # List registered projects
/project add <path>              # Register a new project
/project info                    # Show current project details
/project remove <name>           # Unregister a project
/project agents                  # Generate project-specific agents
```

## Context Restoration

On session start (including after `/clear`), the `SessionStart` hook reads `projects.json` and outputs `PROJECT_RESTORE` with the active project's metadata. Claude then includes the project name in the startup greeting.

## Adding Project-Specific Skills

To add a skill that only exists in one project:

```bash
mkdir -p <project>/.claude/skills/deploy
cat > <project>/.claude/skills/deploy/SKILL.md << 'EOF'
---
name: deploy
description: Deploy to staging/production
user_invocable: true
arguments:
  - name: environment
    description: Target environment (staging/production)
    required: true
---

# /deploy — Project deployment

... skill content ...
EOF
```

This skill will be visible only when working in that project. It can also **override** a devflow skill by using the same name (e.g., creating a project-specific `/develop` with extra deployment phase).

## Developing DevFlow Skills

When working in the devflow directory:

1. Edit skills in `devflow/.claude/skills/` as usual
2. Project-level skills take priority → you always test the latest code
3. Run `./start.sh setup update` to sync changes to `~/.claude/skills/`
4. Other projects pick up changes on next session start

## What Gets Generated per Project

| File | Source | Purpose |
|------|--------|---------|
| `.claude/settings.json` | Template with devflow absolute paths | Hooks + permissions |
| `.mcp.json` | Template with devflow absolute paths | MCP servers (review tools) |
| `.claude/data/` | Empty directory | Runtime data (sessions.json) |
| `.claude/agents/` | Generated by `/project agents` | Project-specific agents |
| `.gitignore` entries | Appended by setup | Excludes generated files |

## What Stays in DevFlow (Not Copied)

| Component | Location | Why |
|-----------|----------|-----|
| Hook scripts | `devflow/.claude/hooks/` | Referenced via absolute paths in settings.json |
| Shell scripts | `devflow/scripts/` | Called by hooks via absolute paths |
| Agent templates | `devflow/.claude/agents/templates/` | Used during `/project agents` generation |
| Default agents | `devflow/.claude/agents/` | Fallback in resolve-agent.sh |
| projects.json | `devflow/.claude/data/` | Central registry, read by hooks |
| MCP servers | `devflow/mcp-servers/` | Referenced via absolute paths in .mcp.json |
