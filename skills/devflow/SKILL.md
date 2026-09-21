---
name: devflow
description: DevFlow driver — run the research → plan → implement pipeline as autonomous phase agents with an explicit approval gate between phases. No arg — Jira standup → pick a task → route → run. With <slug> — skip standup, resume at the right phase. Session runs on fable 5.1.
user_invocable: true
model: claude-fable-5-1
arguments:
  - name: slug
    description: "Optional: task slug (e.g. dev-541-discount-on-invoices) to skip standup and route directly"
    required: false
---

# /devflow — pipeline driver (standup → route → phase agent → gate → next)

Interactive orchestrator. Spawns the `research` / `plan` / `implement` phase agents (each with its
own frontmatter model — claude-fable-5-1, effort low), shows you each artifact, and **waits for your
explicit approval at each gate** before the next phase. You control git throughout — the driver
never branches or commits, and neither does `implement`.

Keep this thin: the driver only routes, shows artifacts, holds gates, and relays answers. **All
phase logic lives in the agent bodies** — don't re-implement a phase here.

## Inputs
- `/devflow` — start from the Jira standup.
- `/devflow <slug>` — skip standup, route by the slug, resume at the right phase (this replaces the
  old per-phase `/research` `/plan` `/implement` entry points).

## Step 0: Project context
Read `AGENTS.md` from cwd. The shared CLI is `~/.claude/skills/devflow/devflow` (called `df` below
for brevity; invoke the full path, not an assumed shell alias). Commands return JSON.
Run `df context`. A new project needs `df init` once; the launcher does this automatically.
A missing database for an existing identity is an error: restore it, never silently reset progress.

## Step 1: Pick the task (skip if a slug was given)
Run `bash ~/.config/devflow/integrations/jira-digest.sh`. Show its output unchanged, waiting bucket
first. On errors stop; never fall back to MCP. Let the user select a key. `df route <key>` resolves
existing slugs; if ambiguous, ask for one of the listed slugs. For a new task agree a full slug
`<key-lowercase>-<short-summary>` and keep it stable across phases.

## Step 2: Route using the shared CLI
Run `df route <slug>`. Never derive completion or approval from file existence yourself.

| Returned state | Action |
|---|---|
| `research` | Spawn research; pass the returned TZ path if present |
| `plan` / `plan_outdated` | Spawn plan with the current `research_revision` |
| `approval_required` | Show the named artifact and hold its phase gate |
| `ready` | Name step `n` of `total`, start that step as below |
| `completed` | Show changelog; stop |
| `running` | Show the run ID; inspect whether its agent is still working. Never start a duplicate |
| `blocked` | Show reason; stop. Resume only after the user decides how to proceed |
| `review_required` | Done steps changed: show differences and ask whether to restore their definitions or reopen them |
| `migration_required` / `migration_pending` | Follow the migration flow below |
| `legacy_review` / CLI error | Show the diagnostic; resolve the ambiguity before proceeding |

Tag token attribution best-effort with `python3 ~/.claude/skills/tokens/token-stats.py --tag <KEY>`.
Failure to tag does not block work.

## Step 3: Run phase, gate, repeat
Spawn `research` or `plan` via Agent (`subagent_type` matches the phase), passing cwd, stable slug,
and the current input revision. Agent bodies hold the phase logic.

After research/plan returns, run `df route <slug>`, read and show the artifact, and retain the returned
`revision`. Relay questions/edits to the same agent via SendMessage. Show each updated version.
**Only after explicit user approval**, run:
```
df approve <slug> <research|plan> --revision <hash-that-was-shown>
```
If the CLI rejects a stale revision, show the changed artifact and ask again. This command records
the user's decision; its availability is never permission for the agent to approve its own work.
Then route again. Existing files with no recorded approval go through the same gate.

For `ready`, run `df start <slug> --step <id> --revision <plan-hash>`. Pass its `run_id`, step ID,
number, revision and cwd to a **fresh** implement agent. Never spawn implementation before start
succeeds. Each run covers one step. On return, route again: continue only on `ready`; stop on
`blocked`, `running`, errors or `completed`. The implement agent records its result with `df finish`.
A prose claim of success without a recorded result does not close a step.

## Recovery and replanning
- For an abandoned `running` attempt, inspect code/changelog first. If the result is recoverable,
  finish the same run with its existing evidence. Otherwise, after the user chooses to stop it,
  use `df interrupt <run-id> --reason <reason>`.
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
- Git is manual: no auto-branch, commit, pull, push or PR, for driver or phase agents.
- One task at a time. A blocked step is not permission to skip to another one.
- No direct SQL, no replacement state files, no independent routing algorithm in the prompt.
