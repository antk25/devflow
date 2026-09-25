---
name: standup
description: Morning Jira digest — "what's new on my tasks since last time" across every Jira account in config.env, then help pick a task and route it to the right devflow phase. Read-only; calls jira-digest.sh, never MCP.
user_invocable: true
arguments:
  - name: mode
    description: "Optional: 'peek' to show the digest without marking items seen"
    required: false
---

# /standup — Jira digest → pick a task → route

Thin front-end over `jira-digest.sh`. Shows what changed on your assigned Jira tasks since last time
(every Jira account), helps you pick one, and computes which devflow phase it's at. Does **not** spawn
phase agents — that's `/devflow`'s job. This skill ends with a recommendation.

## Step 1: Project context
Read `AGENTS.md` from cwd → `project`, `vault`. The digest is global across your Jira; the routing
in Step 4 is against **this** project's vault.

## Step 2: Run the digest
Run by absolute path (like `/jira`, never MCP):
```bash
bash ~/.config/devflow/integrations/jira-digest.sh          # default: marks shown items seen
bash ~/.config/devflow/integrations/jira-digest.sh --peek   # when invoked as `/standup peek`
```
Print the output as-is. It opens with the **`⏳ ждут тебя`** bucket — every assigned task whose
**last comment isn't yours**, oldest first, with how long it has been waiting. That bucket is a
standing list, not a diff: a task you read yesterday and never answered stays in it until you reply.
Below it come the per-account sections (`═══ <account> ═══`, one per account in `config.env`) listing each changed
task (`▸ KEY [status] · NEW|UPD`) with new comments (author + `(ты)` + time) and description-edit
flags.

Don't re-sort or summarise the bucket away — it is the first thing the user should read.

**Degradation:** if the script prints `warn:` lines (creds missing, API error, network) or an account section says
«нет доступа» with an HTTP code, surface them plainly and stop — do **not** fall back to Atlassian MCP. If every account says "нового нет",
say so.

## Step 3: Pick a task
Ask which task to work on — a Jira key from the digest (e.g. `DEV-541` / `SE-2044`), or any key the
user names directly (works even when nothing is new).
If the picked key is `SE-*`, run `~/.claude/skills/timesheet/timesheet mirror <KEY> --yes`: it finds
or creates the GS mirror for the employer's timesheet. Show its line; an error does not block routing.

## Step 4: Route with the shared CLI
Run `~/.claude/skills/devflow/devflow route <key-or-slug>` in the current project.
Use its JSON result; never infer approval or completion from files yourself.

- `research`, `plan`, `plan_outdated`: recommend that phase; research `source: tz` starts from the TZ.
- `approval_required`: recommend reviewing and approving the returned artifact, not the next phase.
- `ready`: recommend implementation with returned step ID, `n` and `total`.
- `completed`: task is complete.
- `running`, `blocked`, `review_required`: show the reason and recommend recovery through `/devflow`.
- `migration_required`, `migration_pending`, `legacy_review`: recommend migration/reconciliation.
- CLI error: show it. Ambiguous slugs require a selection; missing state requires initialization or
  restoration, never a guessed route. Standup does not initialize or mutate workflow state.

For a new task, propose `<key-lowercase>-<short-summary>`. Keep the agreed slug stable.
If the task belongs to another project, switch via `./start.sh <project>` first.

## Step 5: Recommend
End with the route, not an action:
```
Задача: <KEY> — <summary>
Маршрут: <research | research по готовому ТЗ | plan | implement, шаг N из M>  (slug: <slug>)
Дальше: /devflow <slug>
```
For `implement`, always name the step number — "продолжаю план" is not a route.
If invoked by the `/devflow` driver, return the slug + recommended phase instead of printing this.

## Rules
- **Read-only.** No code, no git, no phase agents — this skill only reads Jira and globs the vault.
- **Never use Atlassian MCP** to read Jira — only `jira-digest.sh`.
- **Slug ↔ key:** the key is the slug's prefix; no mapping file.
- **`/standup peek`** glances without consuming the seen-state; plain `/standup` marks shown items seen.
