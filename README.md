# DevFlow

A minimal three-phase workflow for [Claude Code](https://docs.anthropic.com/en/docs/claude-code), backed by [Obsidian](https://obsidian.md/) for persistence.

> **research → plan → implement**, each in its own session, each leaving a written artifact in your obsidian vault.

DevFlow does **not** route, branch, commit, review, or otherwise automate. The user drives the work; the skills just structure the phases and persist the output.

---

## Skills

| Skill | What it does | Output |
|-------|-------------|--------|
| `/research <task>` | Gather context for a task — read code, ask clarifying questions, list constraints | `<vault>/research/<slug>.md` |
| `/plan <slug>` | Read a research doc, produce a step-by-step implementation plan | `<vault>/plans/<slug>.md` |
| `/implement <slug>` | Execute a plan step-by-step under user control, save changelog | `<vault>/changelog/<date>-<slug>.md` |
| `/note save\|read\|search\|list\|tz` | Manage notes in the project vault | `<vault>/notes/`, `<vault>/tz/` |
| `/project list\|add\|info\|remove` | Manage the project registry | `.claude/data/projects.json` |

Each phase runs in a fresh session. The artifact from one phase is the input to the next.

---

## Project layout

Every project gets a single `AGENTS.md` at its root. Frontmatter holds the project name and obsidian vault path; the body holds stack, run commands, and conventions:

```yaml
---
project: my-app
vault: /path/to/obsidian/vault/projects/my-app
---

# my-app

## What
Short description.

## Stack
- ...

## Run
- Install: `...`
- Test: `...`

## Conventions
- ...
```

See `AGENTS.md.template` for the full skeleton.

The obsidian vault for each project follows this structure:

```
<vault>/
├── tz/         — task descriptions / specs
├── research/   — research artifacts (Phase 1 output)
├── plans/      — implementation plans (Phase 2 output)
├── changelog/  — what was changed (Phase 3 output)
└── notes/      — free-form notes (rules, patterns, decisions)
```

---

## Install

DevFlow installs its skills as symlinks into `~/.claude/skills/`, so they are available globally.

```bash
git clone <repo> ~/projects/devflow
cd ~/projects/devflow
./install.sh             # creates symlinks
./install.sh --check     # show status without changing anything
./install.sh --remove    # remove the symlinks
```

After install, `/research`, `/plan`, `/implement`, `/note`, `/project` are available in any Claude Code session.

---

## Launching a project

```bash
./start.sh                # interactive menu (requires gum)
./start.sh <name>         # switch to a registered project
./start.sh --current      # use the currently active project
```

`start.sh` updates `active` in the registry, then `cd`s into the project and runs `claude`. The `SessionStart` hook reads the project's `AGENTS.md` and greets you with active TZ / research / plans.

---

## Adding a new project

```bash
# from any directory
/project add /path/to/project [name]

# then create AGENTS.md
cp ~/projects/devflow/AGENTS.md.template /path/to/project/AGENTS.md
$EDITOR /path/to/project/AGENTS.md
```

Configure the SessionStart hook locally (optional but recommended) by copying `.claude/settings.json.example` and replacing `__PROJECT_ROOT__` with the project's absolute path.

---

## Requirements

| Tool | Why |
|------|-----|
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 2.0+ | runtime |
| Python 3.10+ | hook scripts |
| Bash / Git | basics |
| [gum](https://github.com/charmbracelet/gum) | optional, for `./start.sh` interactive menu |

---

## Layout

```
devflow/
├── AGENTS.md                  — devflow's own AGENTS.md
├── AGENTS.md.template         — copy into other projects
├── install.sh                 — symlinks skills into ~/.claude/skills/
├── start.sh                   — project launcher
├── skills/
│   ├── research/   plan/   implement/
│   ├── note/   project/
│   └── autoresearch/          — optional, skill self-optimization tool
├── scripts/
│   └── obsidian-active.sh     — used by SessionStart hook
└── .claude/
    ├── hooks/project-restore.sh
    ├── data/projects.json     — local registry (gitignored)
    └── settings.json          — local settings (gitignored)
```

---

## Philosophy

- **Manual control over automation.** No auto-routing, no auto-commits, no auto-PRs. The user drives.
- **Persistence over agents.** The system's value is the artifact trail in obsidian, not multi-agent orchestration.
- **Model-agnostic.** `AGENTS.md` is plain markdown so the same project can be opened in any tool that respects it.
- **Small surface.** Five skills, two scripts, one hook.

---

## License

MIT
