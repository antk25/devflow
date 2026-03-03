# Multi-Project & Queue Reference

Details on multi-project management, Serena integration, and batch task queue.

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
- The old project's CLAUDE.md, Serena memories, and patterns pollute the context
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

On session start (including after `/clear`), the `SessionStart` hook reads `projects.json` and outputs `PROJECT_RESTORE` with the active project's metadata. Claude then:
1. Activates the Serena project (if registered)
2. Includes the project name in the startup greeting

### Setting Up Projects

Register your projects with the orchestrator:

```bash
/project add /home/user/projects/my-frontend
/project add /home/user/projects/acme
```

### Serena Integration

Projects registered in Serena (via `.serena/config.yaml`) get additional benefits:
- **Symbolic navigation** - find symbols, references, and definitions
- **Persistent memories** - context survives across sessions
- **Smart code search** - language-aware pattern matching

The `SessionStart` hook automatically activates the corresponding Serena project when available.

---

## Batch Task Queue

The `/queue` skill lets you plan a batch of tasks for the **current project** and execute them sequentially. Each queued item invokes an existing skill (`/develop`, `/fix`, `/refactor`, etc.).

### Quick Start

```bash
# Add tasks for the current project
/queue add develop Add dark mode support
/queue add fix Login form validation
/queue add refactor Auth service cleanup
/queue add develop Add export feature

# Review what's queued
/queue list

# Execute all pending tasks
/queue run

# Check results
/queue status
```

### Commands

| Command | Description |
|---------|-------------|
| `/queue add <skill> <desc>` | Add task for current project |
| `/queue list [--all]` | Show queue (pending or all) |
| `/queue run [id]` | Execute pending tasks (optionally from specific ID) |
| `/queue run --background` | Execute in detached tmux session |
| `/queue stop` | Stop active background run |
| `/queue status` | Show last run results + background progress |
| `/queue report` | Show morning report from last run |
| `/queue report --save` | Save report to Obsidian vault |
| `/queue remove <id> [id2...]` | Remove items by ID |
| `/queue clear [--all]` | Clear pending (or all) items |

### Execution Behavior

- Tasks run **sequentially** in ID order
- All tasks run in the **current active project**
- **Failed items don't block** — execution continues to the next task
- **Interrupted runs** — items left as `running` reset to `pending` on next `run`
- Each item invokes the skill via the `Skill` tool, so all existing skill behaviors apply
- **Per-task notifications** — `notify-send` after each task (critical urgency for failures)
- **Morning report** — auto-generated after every queue run with summary, results, and branches for review

### Background Mode

Run the queue overnight in a detached tmux session:

```bash
/queue run --background          # launch in tmux
tmux attach -t devflow-queue     # watch live progress
/queue status                    # check from another session
/queue stop                      # cancel if needed
```

The background session runs a full `/queue run` inside a dedicated Claude Code process. On completion, a morning report is auto-saved to the Obsidian vault at `projects/<project>/reports/`. Check results the next morning with `/queue report`.

### Data

Queue data is stored in `.claude/data/queue.json`. Items track status (`pending` → `running` → `completed`/`failed`/`skipped`), timestamps, branches, and errors. Background run state is tracked in `background_run`, and the last report location in `last_report`.
