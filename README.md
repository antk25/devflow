# DevFlow

A minimal three-phase workflow for [Claude Code](https://docs.anthropic.com/en/docs/claude-code), backed by [Obsidian](https://obsidian.md/) for persistence.

> **research → plan → implement**, run as autonomous phase agents under the `/devflow` driver, each leaving a written artifact in your obsidian vault, with an approval gate between phases.

DevFlow does **not** branch, commit, or push. The driver routes by artifacts and holds the gates; you drive the decisions and control git.

---

## Skills

| Command | What it does | Output |
|---------|-------------|--------|
| `/devflow` | Driver: Jira standup → pick a task → route → run phase agents with an approval gate between phases | pipeline artifacts below |
| `/devflow <slug>` | Skip standup, resume the pipeline at the phase the artifacts imply | — |
| `/standup [peek]` | Jira digest ("what's new on my tasks") across both instances, then recommend a route | — |
| `/note save\|read\|search\|list\|tz` | Manage notes in the project vault | `<vault>/notes/`, `<vault>/tz/` |
| `/project list\|add\|info\|remove` | Manage the project registry | `.claude/data/projects.json` |
| `/tokens [--by …]` | Token spend by task / project / phase / model / day, with dollar cost | table, JSON, or an HTML dashboard |
| `/review [target]` | Review in two axes — conventions and conformance to the TZ — as parallel subagents; findings are never merged between axes | two sections, no fixes |

The driver spawns three **phase agents** (`~/.claude/agents/`), each with its model pinned in frontmatter, each writing one artifact:

| Phase agent | Model | Output |
|-------------|-------|--------|
| `research` | opus | `<vault>/research/<slug>.md` |
| `plan` | opus | `<vault>/plans/<slug>.md` |
| `implement` | sonnet | `<vault>/changelog/<date>-<slug>.md` |

The artifact from one phase is the input to the next; the driver re-routes after each gate.

---

## Cheat sheet

**Start work** — the driver picks up where the artifacts leave off:

```
/devflow              standup → pick a task → route → run (with gates)
/devflow <slug>       skip standup, resume at the right phase
```

**Just glance** — Jira digest without entering the loop:

```
/standup              what's new on my tasks (marks them seen)
/standup peek         same, without marking seen
```

**Anytime:**

```
/note save <title>             save a pattern/rule to vault/notes/
/note search <query>           grep the whole vault
/note read <title>             read a note (fuzzy match)
/note list [folder]            list notes, optionally by folder
/note tz <slug>                read a TZ and check it against the contract shape
/note tz new <slug>            scaffold a TZ from the template
/project list|add|info|remove  manage the project registry
```

**Review** — two axes, separately, never merged into one list:

```
/review                        current branch vs the base from AGENTS.md
/review --uncommitted          the working tree
/review <slug|sha|range>       a task's branch, a commit, a range
```

**Token spend:**

```
/tokens                        cost per task (default view)
/tokens --by phase             research vs plan vs implement vs main session
/tokens --by model             does sonnet-on-implement actually pay off
/tokens --task SE-2032 --by phase    where one task's budget went
/tokens --html ~/tokens.html   dashboard: daily chart + ranked tables
/tokens --tag SE-2044          pin this session to a task for exact attribution
```

Attribution is a ledger (`~/.claude/devflow/task-ledger.jsonl`, written by `/devflow` and
`--tag`) plus a fallback heuristic over Jira keys mentioned in your own messages. Everything
is read from the local transcripts in `~/.claude/projects/` — nothing leaves the machine.

**Launch:**

```
./start.sh                 interactive project menu → opus driver
./start.sh <project>       switch project → opus driver
./start.sh --current       current project → opus driver
```

The driver session runs on opus; each phase agent picks its own model (research/plan opus, implement sonnet) from its frontmatter. Already in a session? `/model` switches it manually.

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

DevFlow installs its skills into `~/.claude/skills/` and its phase agents into `~/.claude/agents/` as symlinks, so they are available globally.

```bash
git clone <repo> ~/projects/devflow
cd ~/projects/devflow
./install.sh             # creates symlinks (skills + phase agents)
./install.sh --check     # show status without changing anything
./install.sh --remove    # remove the symlinks
```

After install, `/devflow`, `/standup`, `/note`, `/project` (and the research / plan / implement phase agents) are available in any Claude Code session.

---

## Launching a project

```bash
./start.sh                # interactive menu (requires gum)
./start.sh <name>         # switch to a registered project
./start.sh --current      # use the currently active project
```

`start.sh` updates `active` in the registry, then `cd`s into the project and runs `claude --model opus` (the driver session). The `SessionStart` hook reads the project's `AGENTS.md` and greets you with active TZ / research / plans.

### Model per phase

Reasoning is worth Opus; mechanical edits are cheaper on Sonnet. The model is pinned **per phase agent** in its frontmatter and holds for that agent's whole run — no per-session juggling:

| Phase agent | Model |
|-------------|-------|
| `research`, `plan` | **opus** |
| `implement` | **sonnet** |

The `/devflow` driver session itself runs on opus (`./start.sh` launches `claude --model opus`); it spawns each phase agent, and the agent's frontmatter model takes over for that phase. `/code-review` and ad-hoc reasoning also default to opus — switch to sonnet with `/model` for a mostly-mechanical ad-hoc session.

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
├── install.sh                 — symlinks skills → ~/.claude/skills/, agents → ~/.claude/agents/
├── start.sh                   — project launcher (opus driver)
├── agents/
│   └── research.md  plan.md  implement.md   — phase agents (model pinned in frontmatter)
├── skills/
│   ├── devflow/   standup/    — pipeline driver + Jira digest front-end
│   ├── note/   project/
│   ├── tokens/                — /tokens + token-stats.py (spend analyzer)
│   └── autoresearch/          — optional, skill self-optimization tool
├── scripts/
│   └── obsidian-active.sh     — used by SessionStart hook
└── .claude/
    ├── hooks/project-restore.sh
    ├── data/projects.json     — local registry (gitignored)
    └── settings.json          — local settings (gitignored)
```

The Jira digest engine itself (`jira-digest.sh`) lives outside the repo in `~/.config/devflow/integrations/`, alongside the other tracker scripts.

---

## Philosophy

- **Gated control over full automation.** The driver routes and runs the phases, but stops at a gate for your approval on research and plan, and never touches git. You drive the decisions that matter.
- **Persistence first.** The system's value is the artifact trail in obsidian — research, plan, changelog — not the orchestration around it.
- **Model-agnostic artifacts.** `AGENTS.md` and the vault docs are plain markdown, readable in any tool.
- **Small surface.** Four skills, three phase agents, one Jira digest script, one hook.

---

## License

MIT
