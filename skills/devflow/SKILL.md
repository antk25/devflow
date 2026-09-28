---
name: devflow
description: DevFlow driver — run the research → plan → implement pipeline as autonomous phase agents with an explicit approval gate between phases. No arg — Jira standup → pick a task → route → run. With <slug> — skip standup, resume at the right phase. Session runs on the session model (fable 5.1 via start.sh).
user_invocable: true
arguments:
  - name: slug
    description: "Optional: task slug (e.g. dev-541-discount-on-invoices) to skip standup and route directly"
    required: false
---

# /devflow — pipeline driver (standup → route → phase agent → gate → next)

Interactive orchestrator. Runs the `research` / `plan` / `implement` phases as separate autonomous
agents (on the session model, effort low), shows you each artifact, and **waits for your explicit
approval at each gate** before the next phase. Git follows the global rule: the assistant creates
branches, commits, runs `git pull`, pushes the current feature branch and opens a PR into the base
branch; pushes to the base/production branch and merges are the user's; `implement` commits each step.

Keep this thin: the driver only routes, shows artifacts, holds gates, and relays answers. **All
phase logic lives in the agent bodies** (`agents/<phase>.md`) — don't re-implement a phase here.

## Launch layer
The driver is agent-neutral; only how a phase is launched differs. Detect the host by the presence
of the `Agent` tool, then use one column for the whole session:

| | Claude Code (`Agent` tool present) | pi (no `Agent` tool) |
|---|---|---|
| Launch a phase | `Agent(subagent_type=launch.claude.agent, model=launch.claude.model)` from `df route` (`<phase>` or `<phase>-high` by complexity), with cwd, slug, revision (and run data for implement) | `devflow phase run <slug> <phase> [--step <id>] [--note <text>]` — the CLI runs the phase body in a separate `pi` process on `launch.pi.model` |
| Relay a remark at the gate | `SendMessage` to the same agent | repeat `devflow phase run <slug> <phase> --note "<remark>"` |
| `start` before implement | the driver runs `df start`, passes `run_id` to the agent | `phase run … implement` calls `start` itself and returns `run_id` |
| Result | the agent's hand-off | JSON: `exit_code`, `report`, `route`, `run_id`, `warning` — show `report`, act on `route` |

If `route` returns a non-empty `policy_stale`, print one line — «запусти `./install.sh` в devflow:
агенты <имена> устарели» — and launch anyway (old frontmatter is not a refusal).

pi rules: never call `claude` in any form (`claude`, `claude -p`, `claude --bg`, `claude --agent`,
`claude-bridge`) — without the `Agent` tool a phase is launched only through `phase run`. The first
action on `/devflow <slug>` is `df route <slug>` — not `ls`, `find`, `--help` or reading the CLI
source. Without `AskUserQuestion`, ask the gate question as plain text and wait for the reply.

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
If the key is `SE-*`, run `~/.claude/skills/timesheet/timesheet mirror <KEY> --yes` once: it finds
or creates the employer's GS mirror (internal task, invisible to the client). An error there is
shown and does not block the task.

## Step 2: Route using the shared CLI
Run `df route <slug>`. Never derive completion or approval from file existence yourself.

| Returned state | Action |
|---|---|
| `research` | Spawn research; pass the returned TZ path if present |
| `plan` / `plan_outdated` | Spawn plan with the current `research_revision` |
| `approval_required` | Show the named artifact and hold its phase gate |
| `ready` | Name step `n` of `total`, start that step as below |
| `completed` | Show changelog; stop |
| `running` | Show the run ID; inspect whether its agent is still working (both hosts: see Recovery). Never start a duplicate |
| `blocked` | Show reason; stop. Resume only after the user decides how to proceed |
| `review_required` | Done steps changed: show differences and ask whether to restore their definitions or reopen them |
| `migration_required` / `migration_pending` | Follow the migration flow below |
| `legacy_review` / CLI error | Show the diagnostic; resolve the ambiguity before proceeding |

Tag token attribution best-effort with `python3 ~/.claude/skills/tokens/token-stats.py --tag <KEY>`.
Failure to tag does not block work.

## Step 3: Run phase, gate, repeat
Launch `research` or `plan` through the launch layer, passing cwd, stable slug and the current input
revision. Agent bodies hold the phase logic.

After research/plan returns, run `df route <slug>`, read and show the artifact, and retain the returned
`revision`. Relay questions/edits through the launch layer (SendMessage / `phase run --note`). Show
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

For `ready`, in Claude Code run `df start <slug> --step <id> --revision <plan-hash>` and pass its
`run_id`, step ID, number, revision and cwd to a **fresh** implement agent; in pi run
`df phase run <slug> implement` (it calls `start` itself). Never launch implementation before start
succeeds. Each run covers one step. On return, route again: continue only on `ready`; stop on
`blocked`, `running`, errors or `completed`. The implement agent records its result with `df finish`.
A prose claim of success (or a `phase run` exit 0 with `warning`) without a recorded result does not
close a step.

On `completed`, in Claude Code spawn **one** `crossreview` agent with cwd, slug and the base branch from `AGENTS.md`.
It reviews the whole branch itself, gets a second opinion from Codex, verifies every finding in the
code and writes `<vault>/notes/<slug>-cross-review.md`; it never edits the repository. Show its
summary and hold: the user decides whether to fix in session, `df reopen` a step, or close the
finding. Run it once per task, not per step — Codex reads the branch against the base as a whole.
In pi there is no `crossreview` launch yet: show the changelog and stop.

## Recovery and replanning
- `running` means the step broke off (limit, closed session) or is still in flight. In both hosts
  inspect first: `git status`, diff, the step's section in `changelog/<date>-<slug>.md`, tests. Then,
  by the user's decision: `df finish <run-id> --status done|partial --changelog <path>` with the
  evidence already there, `df resume`, or `df interrupt <run-id> --reason <reason>`. Never relaunch
  the same step (`Agent implement` / `phase run … implement`) — state is recovered, not replayed.
- After the user resolves a blocked/partial attempt: `df resume <slug> --reason <decision>`;
  re-route before spawning anything. A partial attempt's changes must be inspected before retry.
- Use `df history <slug>` and `df artifact <slug> <phase> --revision <hash>` to compare saved versions.
- Replanning is an explicit user-selected phase; spawn plan, then route and hold the new gate.
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
- Without the `Agent` tool: phases only via `devflow phase run`; `claude` is never called.
