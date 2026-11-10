---
name: devflow
pi: true
description: "Конвейер DevFlow research → plan → implement фазовыми агентами с гейтом одобрения между фазами. Без аргумента — standup → выбор задачи → маршрут; со слагом — продолжить с нужной фазы. Вызывать, когда пользователь говорит «возьми задачу», «начнём SE-…», «продолжи задачу <slug>», «что дальше по задаче», «запусти research/план/реализацию»; start or resume a task."
user-invocable: true
argument-hint: "[slug]"
---

# /devflow — pipeline driver (standup → route → phase agent → gate → next)

Interactive orchestrator. Runs the `research` / `plan` / `implement` phases as separate autonomous
agents (model and effort per phase from `model-policy.json`), shows you each artifact, and **waits for your explicit
approval at each gate** before the next phase. Git follows the global rule: the assistant creates
branches, commits, runs `git pull`, pushes the current feature branch and opens a PR into the base
branch; pushes to the base/production branch and merges are the user's; `implement` commits each step.

Keep this thin: the driver only routes, shows artifacts, holds gates, and relays answers. **All
phase logic lives in the agent bodies** (`agents/<phase>.md`) — don't re-implement a phase here.

## Launch layer
The driver is agent-neutral: every phase (research, plan, implement) is launched through one CLI
command, never through the `Agent` tool. Only the harness differs by host:

| | Claude Code | pi |
|---|---|---|
| Launch a phase | `devflow phase run <slug> <phase> --host <launch.harness> [--step <id>] [--note <text>]` — `launch.harness` from `df route` (`claude` → separate `claude -p` process with the agent's model and effort, `codex` → `codex exec`) | `devflow phase run <slug> <phase> [--step <id>] [--note <text>]` — the CLI runs the phase body in a separate `pi` process on `launch.pi.model` |
| Relay a remark at the gate | repeat the same `phase run … --note "<remark>"` (a new run, not a resume) | same |
| `start` before implement | `phase run … implement` calls `start` itself and returns `run_id` | same |
| Result | JSON: `status`, `artifact`, `tokens`, `cost`, `route`, `run_id`, `exit_code`, `report`, `warning` — show `report` and the artifact, act on `route`; `status: failed` is a harness or artifact failure, the `devflow` return code only reports devflow's own refusal | same |

The `/devflow` session itself (orchestrator) runs on Opus 5.5 high from `./start.sh`; fallback
orchestrator — gpt-sol high (D1 of DF-31).

If `route` returns a non-empty `policy_stale`, print one line — «запусти `./install.sh` в devflow:
агенты <имена> устарели» — and launch anyway (old frontmatter is not a refusal).

pi rules: never call `claude` in any form (`claude`, `claude -p`, `claude --bg`, `claude --agent`,
`claude-bridge`) — without the `Agent` tool a phase is launched only through `phase run`. The first
action on `/devflow <slug>` is `df route <slug>` — not `ls`, `find`, `--help` or reading the CLI
source. Without `AskUserQuestion`, ask the gate question as plain text and wait for the reply.

bb thread (`BB_THREAD_ID` set): ask the gate only through `AskUserQuestion`, never as plain text —
otherwise `waiting-on-you` does not see it; the user answers the gate in the bb interface.

## Inputs
- `/devflow` — start from the Jira standup.
- `/devflow <slug>` — skip standup, route by the slug, resume at the right phase (this replaces the
  old per-phase `/research` `/plan` `/implement` entry points).

## Step 0: Project context
Read `AGENTS.md` from cwd. The shared CLI is `devflow` (called `df` below
for brevity; invoke the full path, not an assumed shell alias). Commands return JSON.
Run `df context`. A new project needs `df init` once; the launcher does this automatically.
A missing database for an existing identity is an error: restore it, never silently reset progress.

## Step 1: Pick the task (skip if a slug was given)
Run `bash ~/.config/devflow/integrations/jira-digest.sh`. Show its output unchanged, waiting bucket
first. On errors stop; never fall back to MCP. Let the user select a key. `df route <key>` resolves
existing slugs; if ambiguous, ask for one of the listed slugs. For a new task agree a full slug
`<key-lowercase>-<short-summary>` and keep it stable across phases.
If the selected key is `SE-*`, run `~/.claude/skills/timesheet/timesheet mirror <KEY> --yes` once: it
finds or creates the employer's GS mirror (internal task, invisible to the client). An error there is
shown and does not block the task. This belongs to Step 1 only: `/devflow <slug>` skips it, since the
mirror was made when the task was first picked.

## Step 2: Route using the shared CLI
Run `df route <slug>`. Never derive completion or approval from file existence yourself.

| Returned state | Action |
|---|---|
| `research` | Spawn research; pass the returned TZ path if present |
| `plan` / `plan_outdated` | Spawn plan with the current `research_revision` |
| `approval_required` | Show the named artifact and hold its phase gate |
| `ready` | Name step `n` of `total`, start that step as below |
| `completed` | Show changelog; run the final crossreview protocol below |
| `running` | Show the run ID; inspect whether its agent is still working (both hosts: see Recovery). Never start a duplicate |
| `blocked` | Show reason; stop. Resume only after the user decides how to proceed. Reason `вопрос: …` (D3 fork): ask it, append the user's answer to `<vault>/notes/decisions-<slug>.md`, then `df resume` and relaunch the step |
| `review_required` | Done steps changed: show differences and ask whether to restore their definitions or reopen them |
| `migration_required` / `migration_pending` | Follow the migration flow below |
| `legacy_review` / CLI error | Show the diagnostic; resolve the ambiguity before proceeding |

Tag token attribution best-effort with `python3 ~/.claude/skills/tokens/token-stats.py --tag <KEY>`.
Failure to tag does not block work.

## Step 3: Run phase, gate, repeat
Launch `research` or `plan` through the launch layer, passing cwd, stable slug and the current input
revision. Agent bodies hold the phase logic.

After research/plan returns, run `df route <slug>`, read and show the artifact, and retain the returned
`revision`. Relay questions/edits through the launch layer (`phase run --note`). Show
each updated version. **Only after explicit user approval in this session**, run:
```
df approve <slug> <research|plan> --revision <hash-that-was-shown>
```
At the research gate, before `df approve`, ask the complexity by the research criterion — unclear TZ
and/or many changes that risk breaking behaviour → `high`, otherwise `medium` / `low` — and record it:
`df complexity <slug> --set <high|medium|low> --gate research`. Only then approve.
If the CLI rejects a stale revision, show the changed artifact and ask again. This command records
the user's decision; its availability is never permission for the agent to approve its own work.
Then route again and launch through the launch layer. Existing files with no recorded approval go
through the same gate.
At the plan gate, show the plan agent's Jev остаток (требование, источник, `noul`) ordered
неразобранные → Отложено → учтено; a `skipped` check is one line.

For `ready`, run `df phase run <slug> implement` with the host's harness (it calls `start` itself
and launches a fresh process for one step). Never launch implementation before start
succeeds. Each run covers one step. On return, route again: continue only on `ready`; stop on
`blocked`, `running`, errors or `completed`. The implement agent records its result with `df finish`.
A prose claim of success (or a `phase run` exit 0 with `warning`) without a recorded result does not
close a step. If the implement reply contains a `Browser:` block, show it to the user verbatim, then `route`.

On `completed`, launch **one** `crossreview` with cwd, slug and the base branch from `AGENTS.md`:

| Роль | Claude Code | pi |
|---|---|---|
| crossreview | `Agent(subagent_type="crossreview")`, прежние Opus 5.5 medium | `devflow agent run crossreview --message-file <input.md> --timeout 900` |
| second-opinion | `Agent(subagent_type="second-opinion")`, прежние Fable 5.1 high | `devflow agent run second-opinion --message-file <independent.md>` |
| Повторный crossreview | новый Agent crossreview | новый `agent run crossreview --message-file <resume.md> --timeout 900` |

Pi: каждый вход — отдельный файл, stdin закрыт; JSON `host/model/model_source/executor`,
`exit_code/report/stderr/warning` описывает процесс, не предметный успех. Ошибка/timeout/сигнал,
пустой ответ или отсутствие итогового вердикта — показать незавершённость, не «чисто».
Модель: `--model` → глобальный `pi.roles.<role>` (`model`, `effort`) → текущая PI-модель/default;
second-opinion имеет независимый ключ, наследование явно видно. Не менять PHASES или модели Claude.
It reviews the whole branch itself, gets a second opinion from Codex, verifies every finding in the
code and writes `<vault>/notes/<slug>-cross-review.md`; it never edits the repository. Show its
summary and hold: the user decides whether to fix in session, `df reopen` a step, or close the
finding. Run it once per task, not per step — Codex reads the branch against the base as a whole.
If it replies `SECOND_OPINION_NEEDED <slug> base=<base> reason=…` (Codex unavailable), spawn a
`second-opinion` agent with cwd, slug and base, then a fresh `crossreview` with the same inputs plus
`second-opinion:` and its findings list verbatim. Its own review is already saved as a draft note, so
the second launch only verifies both lists and writes the note.
В обоих хостах второе мнение получает только cwd/slug/base и base/HEAD/diff hash из черновика,
никогда собственные находки первого обзора. Дословный ответ передаётся только новому crossreview.
При `REVIEW_STALE` начни независимый цикл заново: устаревшие списки не переиспользовать.
Не вызывай `start/finish/approve`: ревью всей ветки не создаёт implement-run.
On `completed` in both hosts also list the `browser:` items of the plan's `## Acceptance (overall)`
as checks after deploy, each as a ready line `/smoke env: staging; slug: <slug>; save; <Дано …;
Когда …; Тогда …>` — the user types it in the main session once the deploy is done; the driver
never runs them.

## Recovery and replanning
- `running` means the step broke off (limit, closed session) or is still in flight. In both hosts
  inspect first: `git status`, diff, the step's section in `changelog/<date>-<slug>.md`, tests. Then,
  by the user's decision: `df finish <run-id> --status done|partial --changelog <path>` with the
  evidence already there, `df resume`, or `df interrupt <run-id> --reason <reason>`. Never relaunch
  the same step (`phase run … implement`) — state is recovered, not replayed.
- After the user resolves a blocked/partial attempt: `df resume <slug> --reason <decision>`;
  re-route before spawning anything. A partial attempt's changes must be inspected before retry.
- Use `df history <slug>` and `df artifact <slug> <phase> --revision <hash>` to compare saved versions.
- Replanning is an explicit user-selected phase; spawn plan, then route and hold the new gate.
  In pi, from `ready` use `devflow phase run <slug> plan --replan --note "<user decision>"`;
  this does not start a run or approve the revised plan.
- To redo a done step, after the user's decision run
  `df reopen <slug> --step <id> --revision <current-plan-hash> --reason <decision>`.
  This also reopens dependent steps and requires plan approval again. Never reopen silently.

## Legacy migration
Run `df migrate <slug>` for a read-only preview. Show the proposed document and imported done IDs.
Only after the user agrees, run `df migrate <slug> --apply <old_revision>` from that preview.
The command backs up the old plan and can resume an interrupted migration using the same revision.
Historical done marks are preserved; approvals are not inferred. Route and approve research/plan.
Plans without step statuses or with ambiguous history require manual reconciliation first.

## Rules
- Explicit research/plan gates, including across sessions. No automatic approvals or state resets.
- Only the CLI changes execution state. Markdown contains definitions, not completion flags.
- Git: the assistant creates branches, commits, runs `git pull`, pushes the current feature branch and opens a PR into the base branch; pushes to the base/production branch and merges are the user's.
- One task at a time. A blocked step is not permission to skip to another one.
- No direct SQL, no replacement state files, no independent routing algorithm in the prompt.
- Phases only via `devflow phase run`, in both hosts; in pi `claude` is never called.
