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
| `/xreview [target] [focus]` | Second opinion on a diff from Codex (OpenAI models over the ChatGPT subscription), called from Bash | review text |
| `/jira <key>` | Read a Jira issue, its comments and attachments through the read-only shell scripts | issue text |

The driver spawns three **phase agents** (`~/.claude/agents/`), each with its model pinned in frontmatter, each writing one artifact:

| Phase agent | Model | Output |
|-------------|-------|--------|
| `research` | fable 5.1 (effort low) | `<vault>/research/<slug>.md` |
| `plan` | fable 5.1 (effort low) | `<vault>/plans/<slug>.md` |
| `implement` | fable 5.1 (effort low) | `<vault>/changelog/<date>-<slug>.md` |

The artifact from one phase is the input to the next; the driver re-routes after each gate through
one Python CLI. Markdown stores definitions; SQLite stores approvals, attempts and completion.
Approvals persist across sessions and apply to the exact document revision that was shown.

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
/tokens --by model             what the switch to fable actually costs
/tokens --task SE-2032 --by phase    where one task's budget went
/tokens --html ~/tokens.html   dashboard: daily chart + ranked tables
/tokens --tag SE-2044          pin this session to a task for exact attribution
```

Attribution is a ledger (`~/.claude/devflow/task-ledger.jsonl`, written by `/devflow` and
`--tag`) plus a fallback heuristic over Jira keys mentioned in your own messages. Everything
is read from the local transcripts in `~/.claude/projects/` — nothing leaves the machine.

**Launch:**

```
./start.sh                 interactive project menu → fable 5.1 driver
./start.sh <project>       switch project → fable 5.1 driver
./start.sh --current       current project → fable 5.1 driver
```

The driver session runs on fable 5.1, and each phase agent pins the same model with `effort: low` in its frontmatter. Already in a session? `/model` switches it manually.

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

The installer creates `.venv` (reusing system packages when available), installs PyYAML if missing,
and initializes `.claude/data/projects.json` with this checkout when no registry exists. Existing
registries are preserved and validated. Foreign files or symlinks cause an error before installation.
`--check` never writes and exits nonzero for missing/conflicting items. `--remove` removes only our
links; it preserves the registry, environment and workflow state.

After install, skills and agents are available in any Claude Code session. The shared CLI is
`~/.claude/skills/devflow/devflow`, or `./scripts/devflow-cli.sh` from this checkout.
`DEVFLOW_CLAUDE_DIR` overrides the symlink destination for isolated installation checks.

---

## Launching a project

```bash
./start.sh                # interactive menu (requires gum)
./start.sh <name>         # switch to a registered project
./start.sh --current      # use the currently active project
```

`start.sh` validates the registry, directory, Claude executable and project metadata before changing
`active`. On a project's first launch it creates the local identity and database. It then runs
`claude --model claude-fable-5-1` with additional settings pointing to DevFlow's SessionStart hook and Git
publication restrictions. No hook is copied into the target project. A cancelled launch or failed
preflight leaves `active` unchanged; an immediate exec failure restores the previous selection.
The hook obtains active documents from the same router used by `/devflow` and `/standup`.

### Model per phase

Все три фазы идут на **Claude Fable 5.1** с `effort: low` — на новых моделях низкий effort закрывает рутину не хуже, чем прежний high на прошлом поколении, а токенов тратит меньше. Модель закреплена **в frontmatter каждого фазового агента** и держится весь его прогон — без переключений внутри сессии:

| Phase agent | Model | Effort |
|-------------|-------|--------|
| `research`, `plan` | **claude-fable-5-1** | low |
| `implement` | **claude-fable-5-1** | low |

Драйвер `/devflow` идёт на той же модели (`./start.sh` запускает `claude --model claude-fable-5-1`), и `/standup`, `/review` и оба ревью-агента тоже. `/code-review` встроенный и frontmatter'а не имеет — он наследует модель сессии.

---

## Adding a new project

```bash
# from any directory
/project add /path/to/project [name]

# then create AGENTS.md
cp ~/projects/devflow/AGENTS.md.template /path/to/project/AGENTS.md
$EDITOR /path/to/project/AGENTS.md
```

The launcher supplies the hook settings automatically. For sessions started directly with `claude`,
merge `.claude/settings.json.example` into the project's existing settings and replace
`__DEVFLOW_ROOT__` with the **DevFlow checkout** path, not the target project's path. Quote the
command's script path if it contains spaces. Initialize workflow state once from the project root
with `~/.claude/skills/devflow/devflow init` before using the workflow directly.

---

## Requirements

| Tool | Why |
|------|-----|
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 2.0+ | runtime |
| Python 3.10+ with venv / pip and SQLite support | workflow CLI, launcher and hooks |
| PyYAML 6.x | YAML parsing; installed by `install.sh` when missing |
| Bash / Git / Linux or WSL utilities (`readlink`, `ln`) | launch and installation |
| [gum](https://github.com/charmbracelet/gum) | optional, for `./start.sh` interactive menu |

---

## Layout

```
devflow/
├── AGENTS.md                  — devflow's own AGENTS.md
├── AGENTS.md.template         — copy into other projects
├── install.sh                 — symlinks skills → ~/.claude/skills/, agents → ~/.claude/agents/
├── start.sh                   — project launcher (fable 5.1 driver)
├── agents/
│   └── research.md  plan.md  implement.md   — phase agents (model pinned in frontmatter)
├── skills/
│   ├── devflow/   standup/    — pipeline driver + Jira digest front-end
│   ├── note/   project/
│   ├── tokens/                — /tokens + token-stats.py (spend analyzer)
│   └── autoresearch/          — optional, skill self-optimization tool
├── scripts/
│   ├── devflow/               — document validation, SQLite state, routing and registry
│   ├── devflow-cli.sh         — shared JSON CLI
│   ├── launch.py              — project selection and launch
│   └── obsidian-active.sh     — delegates to the shared CLI
└── .claude/
    ├── hooks/project-restore.sh
    ├── data/projects.json     — local registry (gitignored)
    └── settings.json          — local settings (gitignored)
```

The Jira digest engine itself (`jira-digest.sh`) lives outside the repo in
`~/.config/devflow/integrations/`, alongside the other tracker scripts. These integrations and their
credentials must be provisioned separately; installation does not make Jira available. Missing
integrations stop standup with a diagnostic; `/devflow <slug>` can start without the digest.

---

## Workflow state and document format

Each project has a stable UUID in `.devflow/project.json` (local, not committed). Execution state is
stored at `~/.local/share/devflow/projects/<uuid>/state.sqlite3`; `DEVFLOW_STATE_DIR` overrides that
parent directory. Project name/path changes do not change identity if this file is retained.
Use a separate identity for an independent copy; never run two independent copies with one ID.

Definitions remain in the vault. A schema-1 plan has YAML like:

```yaml
schema: 1
research_revision: <sha256 returned by route after research approval>
steps:
  - {id: add-contract, n: 1, blocked_by: []}
  - {id: connect-handler, n: 2, blocked_by: [add-contract]}
```

The body has `## Steps`, with matching `### add-contract: Contract` and
`### connect-handler: Handler` sections. IDs are permanent; `n` controls ordering only.
No execution statuses belong in the plan. Keep completed definitions; use new steps for follow-ups.
The parser rejects duplicate YAML keys, unknown dependencies, cycles and mismatched headings.

The CLI emits JSON; errors go to stderr with a nonzero exit. From the project root:

```bash
~/.claude/skills/devflow/devflow route <slug>
~/.claude/skills/devflow/devflow validate <slug>
~/.claude/skills/devflow/devflow history <slug>
```

`route` distinguishes research, plan, approval-required, outdated-plan, ready, running, blocked,
review-required and completed states. It also reports legacy migration/reconciliation cases.
A plan is complete only when every defined step is done at its current definition revision and
its research/plan approvals are valid. Invalid plans are errors, not completed tasks.

Approval and execution commands (normally called by the driver):

```bash
# Only after the user approved this exact displayed revision:
~/.claude/skills/devflow/devflow approve <slug> research --revision <hash>
~/.claude/skills/devflow/devflow approve <slug> plan --revision <hash>
~/.claude/skills/devflow/devflow start <slug> --step <id> --revision <plan-hash>
~/.claude/skills/devflow/devflow finish <run-id> --status done --changelog <path>
```

Approvals store snapshots of the document text. Changing research requires its approval again and
updating the plan's `research_revision`; changing a plan requires a new plan approval. Execution
updates SQLite, so finishing a step does not change the approved plan hash. `approve` records a
human decision; it is not an authentication mechanism and agents must never self-approve.

One implementation run may be active per project. Its changelog section begins with
`<!-- devflow-run: <run-id> -->` and includes `**Status:** done`, `partial` or `blocked`.
Write and verify that section before `finish`; partial/blocked also require `--reason`.
Repeating finish with the same run section is safe, including after later sections are appended.
SQLite and Markdown do not share a transaction: an interruption after writing the changelog leaves
`running`, and recovery reuses the same run ID and evidence rather than repeating the work blindly.

Recovery commands require inspecting the work and the user's decision:

```bash
~/.claude/skills/devflow/devflow interrupt <run-id> --reason <why>
~/.claude/skills/devflow/devflow resume <slug> --reason <decision>
~/.claude/skills/devflow/devflow reopen <slug> --step <id> --revision <hash> --reason <decision>
~/.claude/skills/devflow/devflow artifact <slug> plan --revision <saved-hash>
```

`reopen` also reopens dependent steps and invalidates plan approvals. It does not undo code changes.
A stale `running` attempt is never automatically retried; first determine whether its agent still
runs and inspect its code/changelog. Stop it explicitly if no result can be recovered.

### Existing plans

`migrate <slug>` is read-only and returns the converted document, original revision and done IDs.
After reviewing that preview, `migrate <slug> --apply <old-revision>` creates a
`<plan>.pre-devflow.bak`, assigns stable IDs, removes execution flags and imports historical done
marks into SQLite. It does not infer approvals. Plans without per-step statuses require manual
reconciliation; the existence of a changelog is not proof that every step was finished.

An interrupted migration leaves a manifest in `.devflow/migrations/`. Routing stops until migration
is resumed with the same preview revision. Conflicting document edits require reconciliation.

### Backup and moving a project

```bash
~/.claude/skills/devflow/devflow backup /path/to/new-backup.sqlite3
```

This uses SQLite's backup API and refuses to overwrite a destination. Back up the vault and
`.devflow/project.json` too; preserve pending migration manifests if any. For a consistent complete
project backup, finish or stop active agents first. To move the project, retain its identity,
restore the database under `<state-root>/<uuid>/state.sqlite3`, update the registry path and the
vault path in AGENTS.md. Create or mount the vault directory before launch; a missing vault
is an error, not an empty task list. The state directory is local; multi-machine shared execution is unsupported.

If identity exists but its database is missing, startup stops. Restore the database; only use
`init --fresh-state` when deliberately accepting loss of execution/approval history. The CLI never
reconstructs approval from the presence of a document. Copying only Markdown does not move workflow
state. Database schema version 1 is checked on opening; unknown versions are rejected.

---

## Philosophy

- **Gated control over full automation.** The driver routes and runs the phases, but stops at a gate for your approval on research and plan, and never touches git. You drive the decisions that matter.
- **Persistence first.** The system's value is the artifact trail in obsidian — research, plan, changelog — not the orchestration around it.
- **Model-agnostic artifacts.** `AGENTS.md` and the vault docs are plain markdown, readable in any tool.
- **Shared mechanics.** Skills handle reasoning and interaction; the Python CLI owns state transitions and routing.

---

## License

MIT
