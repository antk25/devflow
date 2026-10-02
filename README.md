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
| `/project init\|sync\|list\|info\|remove` | Onboard projects and manage the registry | `.claude/data/projects.json` |
| `/tokens [--by …]` | Token spend by task / project / phase / model / day, with dollar cost | table, JSON, or an HTML dashboard |
| `timesheet serve` → `/board` | Read-only task board across all registry projects: DevFlow stage and days waiting at a gate, Jira status, PRs, time and tokens per task, a 14-day token line chart with a per-task breakdown on hover, and rate limits; `devflow board [--refresh]` prints the same snapshot as JSON | `~/.claude/devflow/board/snapshot.json` |
| `/review [target]` | Review in two axes — conventions and conformance to the TZ — as parallel subagents; findings are never merged between axes | two sections, no fixes |
| `/xreview [target] [focus]` | Second opinion on a diff from Codex (OpenAI models over the ChatGPT subscription), called from Bash | review text |
| `/retro [session\|slug]` | Post-mortem of one expensive session: `jq` probes over its transcript (repeated reads, tool errors, interruptions, corrections) → proposed rule edits, applied only on an explicit yes | `notes/retro-<id>.md` |
| `/maintain [week\|month]` | Scheduled-by-hand maintenance checklist: `/review`, `/code-review`, `/simplify`, `/security-review` over the period's commits (month adds `install.sh --check`, `/doctor`, rule proofreading, devflow memory and observations triage); every item ends in a PR, a TZ draft, «к тикету», clean or skipped | `notes/maintain-<date>.md` |
| `/transcribe [files]` | Local call transcription (faster-whisper large-v3 on the GPU) into `notes/<date>-calls-transcripts/` | transcript notes |
| `/jira <key>` | Digest of a Jira issue (description, comments, attachments) read by the `reader` subagent (Sonnet, effort low) through the read-only shell scripts | issue digest |
| `/smoke [env: <name>;] [slug: <slug>;] [save;] <scenario>` | Browser check of a scenario in the `browser` subagent (Sonnet, effort low) through `devflow-browser` — isolated headless Chrome, secrets as `@env:NAME`, no MCP | verdict table ✅/❌ ≤40 lines, screenshot paths on ❌ |

The driver spawns three **phase agents** (`~/.claude/agents/`), each with its model pinned in frontmatter, each writing one artifact:

| Phase agent | Model | Output |
|-------------|-------|--------|
| `research` | from `model-policy.json` (Opus 5.5 medium; `research-high` — high) | `<vault>/research/<slug>.md` |
| `plan` | from `model-policy.json` (Opus 5.5 medium; `plan-high` — high) | `<vault>/plans/<slug>.md` |
| `implement` | from `model-policy.json` (Fable 5.1 low; Opus 5.5 low when Fable limits are out) | `<vault>/changelog/<date>-<slug>.md` |
| `crossreview` | session model (effort low) | `<vault>/notes/<slug>-cross-review.md` — after the last step: own review + Codex second opinion, every finding verified in code |

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
/project init|sync|list|info|remove  onboard projects, manage the registry
/smoke [env: <name>;] [slug: <slug>;] [save;] <scenario>  browser check in the `browser` subagent
```

Repeat a saved browser scenario without a subagent or MCP: `bash <vault>/notes/smoke-<slug>.sh` —
written by `/smoke slug: <slug>; save; …`, one `✅`/`❌` line per check, exit 0 only when all pass;
secrets stay `@env:NAME` and are substituted by `devflow-browser` at run time.
Arguments of `/smoke` are `key: value;` segments, not `--flags`: the harness drops fork-skill arguments
that start with `--`, so no documented form of the call begins with one.
Browser items of an implement step are run by the implement agent itself: the `browser` subagent in
the background, the verdict as the file `/tmp/devflow-smoke/<slug>/verdict.md`, waiting via
`devflow-smoke-wait`.

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

The driver session runs on fable 5.1; each phase agent gets its own model and effort from `~/.claude/devflow/model-policy.json` — see [Model per phase](#model-per-phase).

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

DevFlow installs its skills into `~/.claude/skills/` as symlinks, so they are available globally. The phase agents `research`, `research-high`, `plan`, `plan-high`, `implement` in `~/.claude/agents/` are **generated**: body from `agents/<phase>.md`, `model`/`effort` from `~/.claude/devflow/model-policy.json` (a `-high` twin exists only where the `high` column differs). Edit the policy → rerun `./install.sh`; `--check` prints `STALE agent <name>` until then, and `route` returns the same names in `policy_stale`. Review agents stay symlinks. The subagent-free skills (`note`, `jira`, `project`, `cut`) and the `devflow` driver are also linked into pi — `~/.pi/agent/skills/<name>` plus a one-line prompt template `~/.pi/agent/prompts/<name>.md` so that `/note list` and `/devflow <slug>` work in pi literally. pi has no subagents, so `jira` runs there in the main context (its `context: fork` / `agent: reader` frontmatter only applies in Claude Code). Skills that need Claude Code subagents (or are not verified for pi) are listed as `skip pi <name>: <reason>` by `./install.sh` and `--check`; `smoke` is one of them — in pi `implement` runs the saved `<vault>/notes/smoke-<slug>.sh` instead.

`./install.sh` also links `~/.local/bin/devflow-rate-limits`; the statusline hook-up is described under [Model per phase](#model-per-phase).

```bash
git clone <repo> ~/projects/devflow
cd ~/projects/devflow
./install.sh             # creates symlinks (skills + phase agents + ~/.local/bin/devflow)
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
`DEVFLOW_CLAUDE_DIR` and `DEVFLOW_PI_DIR` override the symlink destinations for isolated installation checks.

---

## Launching a project

```bash
./start.sh                # interactive menu (requires gum)
./start.sh <name>         # switch to a registered project
./start.sh --current      # use the currently active project
```

`start.sh` validates the registry, directory, Claude executable and project metadata before changing
`active`. On a project's first launch it creates the local identity and database. It then runs
`claude --model ${DEVFLOW_MODEL:-claude-fable-5-1}` — nothing else: the SessionStart hook and Git publication rules come
from the global `~/.claude/settings.json`, so a bare `claude` in the project directory gets the same
environment. A project without `AGENTS.md` is not launched blind: the launcher points to
`/project init <path>` and asks before continuing without context. A cancelled launch or failed
preflight leaves `active` unchanged; an immediate exec failure restores the previous selection.
The hook obtains active documents from the same router used by `/devflow` and `/standup`.

### Launching pi instead of Claude Code

```bash
devflow-pi <name>                                   # pi in the project directory, DevFlow context appended
devflow-pi <name> --model openai-codex/gpt-6-astra  # explicit model; otherwise PI_PROVIDER/PI_MODEL[:PI_REASONING_LEVEL] or pi's default
```

`devflow-pi` (`bin/devflow-pi`, linked into `~/.local/bin` by `install.sh`) runs the same launcher as
`start.sh` with `--agent pi`: registry, directory and `AGENTS.md` checks are shared. pi has no
SessionStart hook, so the launcher writes what the hook would print — `PROJECT_RESTORE`,
`OBSIDIAN_CONTEXT`, the latest `/cut` hand-off of the active task (`devflow handoff latest --task <key>`)
and a short block of pi rules (state moves only through `devflow`, never call `claude`, `approve` only
on the user's word, on `running` inspect before `finish`/`resume`/`interrupt`) — to a temp file and
starts `pi --append-system-prompt <file>`. Nothing is written into the project: no state database is
created, a project without `AGENTS.md` gets a warning and a bare pi. If the model would resolve to
`claude-bridge`, a warning goes to stderr before launch.

`/devflow <slug>` in pi is the same driver skill as in Claude Code; only the launch layer differs.
Where Claude Code spawns a phase through the `Agent` tool, pi runs
`devflow phase run <slug> <research|plan|implement> [--step <id>] [--note <text>]`: the CLI starts a
separate `pi -p` process on `launch.pi.model` from the policy with the phase body (`agents/<phase>.md`) appended to
the system prompt, and returns JSON (`exit_code`, `report`, `route`, `run_id`, `warning`). Gate
remarks go back as a repeated `phase run --note`. For `implement` the CLI calls `devflow start`
itself before the process; if the step ends without `devflow finish`, `route` stays `running` and the
result carries a `warning` — the driver then inspects (`git status`, changelog) and recovers through
`finish`/`resume`/`interrupt`, never by relaunching the step. `claude` is never called from pi.

### Model per phase

Модель и effort фазового агента не зашиты в агентах и драйвере — это правило в
`~/.claude/devflow/model-policy.json` (эталон — `model-policy.example.json` в корне; `./install.sh`
копирует его, если файла нет). Правило — хост × фаза × сложность задачи; стартовое:

| Фаза | Сложная задача (`high`) | Средняя / простая |
|------|-------------------------|-------------------|
| `research`, `plan` | Opus 5.5 high | Opus 5.5 medium |
| `implement` | Fable 5.1 low; кончились лимиты Fable — Opus 5.5 low (`fallback`) | то же |
| в pi | `gpt-6-astra` high | `gpt-6-astra` medium; `implement` — low |

Вышла новая модель — меняется одна строка в JSON, затем `./install.sh`: агенты `research`,
`research-high`, `plan`, `plan-high`, `implement` в `~/.claude/agents/` генерируются из тела
`agents/<phase>.md` и колонок policy (см. [Install](#install)); до перезапуска `--check` печатает
`STALE`, а `route` — `policy_stale`. Драйвер, `/standup`, `/review`, ревью-агенты и встроенный
`/code-review` модель не пинят и идут на модели сессии (`./start.sh` — `claude --model
${DEVFLOW_MODEL:-claude-fable-5-1}`).

**Сложность.** На гейте research драйвер спрашивает сложность по критерию исследования и пишет
`devflow complexity <slug> --set <high|medium|low> --gate research`; рядом ложится теневая оценка
Jev (`source=jev`, `applied=false`) для калибровки. `devflow route` по выбору отдаёт `launch`:
для Claude Code — имя агента (`plan` или `plan-high`) и алиас модели при fallback, для pi —
`provider/id:level` (`launch.pi.model`; приоритет `--model` > policy > `PI_*` > дефолт pi).

**Лимиты Fable.** Поток: `statusline → rate-limits.json → route`. Claude Code передаёт
`rate_limits` только в статусную строку, поэтому в свой `~/.claude/statusline.sh` сразу после
`input=$(cat)` добавляется одна строка:

```bash
echo "$input" | devflow-rate-limits
```

`devflow-rate-limits` (`scripts/rate-limits.sh`, ссылка от `./install.sh`) атомарно пишет
`~/.claude/devflow/rate-limits.json` = `{five_hour, seven_day, model, at}`. `route` читает файл по
`limits` из policy (`threshold: 95`, `max_age_min: 10`): окно с `used_percentage ≥ threshold`, ещё
не сброшенное, переводит `implement` на колонку `fallback`, и `launch.claude.model` несёт алиас
(`opus`; для id без префикса `claude-*` — сам id) для `Agent`. Если в `fallback` другой effort,
`install.sh` генерирует ещё `implement-fallback`, и `route` выбирает его; при равном effort
лишнего агента нет. Файл старше `max_age_min` — сигнала нет (`limits: null`). Пока строки в
statusline нет, `--check` печатает `MISS statusline call devflow-rate-limits`.

### Доразметка сложности прошлых задач

Для калибровки Jev нужна таблица «ответ Jev × решение пользователя × факт». Факты собирает
`devflow complexity <slug>` — в ответе рядом с `user`/`jev` есть `facts`: число шагов плана, число
прогонов и их статусы, число ревизий research/plan. `devflow complexity <slug> --gate backfill` без
`--set` пишет только теневое событие Jev (`applied=false`), выбор пользователя не трогает.

`scripts/complexity-backfill.sh <project-cwd>` проходит по `tz/*.md` проекта: задачи с планом
получают такой теневой прогон, строки `{slug, choice, noul, facts, error}` копятся в
`~/.claude/devflow/complexity-backfill.jsonl` (переопределяется `DEVFLOW_COMPLEXITY_BACKFILL`),
задачи без плана пропускаются с пометкой. Нужен `OPENROUTER_API_KEY` и `jev: true` в `AGENTS.md`;
свой вердикт по каждой задаче пользователь потом ставит `devflow complexity <slug> --set … --gate backfill`.

---

## Adding a new project

A DevFlow project is an **umbrella directory** that holds one or more repositories
(`<project>/backend`, `<project>/frontend`). `AGENTS.md`, `.devflow/` and personal settings live in
the umbrella and are never committed into the repositories.

```bash
# inside any Claude Code session
/project init /path/to/project [name]     # `add` is an alias
```

The skill runs a read-only `Explore` subagent over the directory (README, stack files, CI, git
history), renders a draft `AGENTS.md` from `AGENTS.md.template` — every fact with its source file,
unknown ones marked explicitly — shows it, and only after confirmation calls the CLI:

```bash
~/.claude/skills/devflow/devflow project init <path> [--name N] [--agents-draft F] [--dry-run]
~/.claude/skills/devflow/devflow project sync --all --dry-run     # what is missing anywhere
~/.claude/skills/devflow/devflow project sync <name>|--all        # create only what is missing
```

`init` creates, in order: vault directories → `AGENTS.md` (kept as is if present) → local identity
`.devflow/project.json` → database → registry entry. Every item is reported as `created | skipped |
attention`; re-running is idempotent. `sync` brings already registered projects up to the same
layout but never generates `AGENTS.md` or edits the registry — those cases come back as
`attention`. Both reports also carry an informational `browser` item: the `### ` environments of the
`## Browser` section in `AGENTS.md` (what `/smoke` accepts as `env:`), or a hint that the section is
missing — the template ships a `local` placeholder; neither command ever edits an existing
`AGENTS.md`. `/project sync` in a session always shows the `--dry-run` table first.

The SessionStart hook and the publication permissions live in the **global**
`~/.claude/settings.json`: merge `settings.global.example.json` into it by hand and replace
`__DEVFLOW_ROOT__` with the **DevFlow checkout** path, not the target project's path. Quote the
command's script path if it contains spaces. `./install.sh --check` reports what is still missing
(`MISS global hook|allow|deny|setting`) and which old blanket denies (`Bash(gh:*)`, `Bash(git push:*)`)
would override the new rules (`STALE global deny`); it never writes the file. The hook prints the
project context once per session (a marker under `$XDG_RUNTIME_DIR`, 10 s window), so `compact`
and `resume` restore it again; after `clear` it also prints `HANDOFF <path>` when the latest `/cut`
hand-off is under 30 minutes old. The UserPromptSubmit hook `context-guard.sh` tells the model the
context size it can't see in the status line: `CONTEXT_WARN` from 120K, `CONTEXT_CUT` from 180K, so
it offers `/cut` at a step boundary; `autoCompactWindow: 500000` keeps auto-compaction as a last
resort only. A new environment setting goes to the global layer first; it becomes
per-project only when added to both `project init` and `project sync`.

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
│   └── research.md  plan.md  implement.md  crossreview.md   — phase agents (model pinned in frontmatter)
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
    ├── hooks/context-guard.sh
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
An Acceptance item `browser: env: <name>; Дано …; Когда …; Тогда …` is a browser check: in a step it is
run by the implement agent itself (env reachable before deploy, usually `local`); in
`## Acceptance (overall)` it is a check after deploy that the driver lists on `completed`.
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
