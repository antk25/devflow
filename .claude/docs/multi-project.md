# Multi-Project Reference

Details on multi-project management.

## Multi-Project Support

The orchestrator manages multiple projects via a central registry (`projects.json`). Project selection happens **before** launching Claude Code, using the `./start.sh` launcher script.

### Launcher Script

```bash
./start.sh              # interactive gum menu → select project → launch claude
./start.sh my-app       # switch to my-app → launch claude
./start.sh --current    # keep current project → launch claude
```

The launcher:
1. Shows an interactive menu (via `gum choose`) to select a project
2. Handles Docker container lifecycle (stops previous, starts new)
3. Updates `projects.json` active field
4. Launches `claude` in the project directory

### Why no in-session switching?

Switching projects inside Claude Code is impractical because:
- The old project's CLAUDE.md, memories, and patterns pollute the context
- A `/clear` is always needed after switching, which defeats the purpose
- Interactive terminal tools (`gum`) don't work in Claude Code hooks (no TTY)

**One session = one project.** To switch projects, exit Claude Code and run `./start.sh` again.

### Project Registry Commands

Inside Claude Code, `/project` manages the registry (without switching):

```
/project list                    # List registered projects
/project add <path>              # Register a new project
/project info                    # Show current project details
/project remove <name>           # Unregister a project
```

### Context Restoration

On session start (including after `/clear`), the `SessionStart` hook reads `projects.json` and outputs `PROJECT_RESTORE` with the active project's metadata. Claude then includes the project name in the startup greeting.

### Setting Up Projects

Register your projects with the orchestrator:

```bash
/project add /home/user/projects/my-frontend
/project add /home/user/projects/acme
```

