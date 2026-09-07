---
name: standup
description: Morning Jira digest — "what's new on my tasks since last time" across both instances, then help pick a task and route it to the right devflow phase. Read-only; calls jira-digest.sh, never MCP.
user_invocable: true
model: opus
arguments:
  - name: mode
    description: "Optional: 'peek' to show the digest without marking items seen"
    required: false
---

# /standup — Jira digest → pick a task → route

Thin front-end over `jira-digest.sh`. Shows what changed on your assigned Jira tasks since last time
(both instances), helps you pick one, and computes which devflow phase it's at. Does **not** spawn
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
Below it come the per-instance sections (`═══ resolventa/productsearch ═══`) listing each changed
task (`▸ KEY [status] · NEW|UPD`) with new comments (author + `(ты)` + time) and description-edit
flags.

Don't re-sort or summarise the bucket away — it is the first thing the user should read.

**Degradation:** if the script prints `warn:` lines (creds missing, API error, network), surface
them plainly and stop — do **not** fall back to Atlassian MCP. If both instances say "нового нет",
say so.

## Step 3: Pick a task
Ask which task to work on — a Jira key from the digest (e.g. `DEV-541` / `SE-2044`), or any key the
user names directly (works even when nothing is new).

## Step 4: Route by vault artifacts
Derive the slug prefix from the key (lowercase, `DEV-541` → `dev-541`). Glob the current vault,
case-insensitively, for `<KEY>-*`. Resolution order — **the plan is read before the changelog**,
because a changelog now appears after the *first* step, not at the end of the task:

1. `<vault>/plans/<slug>*.md` exists → read **its frontmatter only** — parse the YAML block between
   the leading `---` fences, never grep the body for `steps:` (a plan documenting the format has
   that word in a code fence):
   - `steps` present → the **frontier** is every step with `status: open` whose `blocked_by` entries
     are all `done`. Non-empty → next phase: **implement, шаг N** (lowest on the frontier).
     Empty → task is **closed**.
   - `steps` absent → legacy plan, written before steps existed. A changelog for it → **closed**
     (a task finished the old way; don't reopen it as step 1). No changelog → all steps open, no
     blockers: count the `### <n>.` headings in the body → **implement, шаг 1**.
2. `<vault>/changelog/*-<slug>*.md` exists and no plan says otherwise → **closed** (ask: reopen?).
3. `<vault>/research/<slug>*.md` exists, no plan → next phase: **plan**.
4. `<vault>/tz/<slug>*.md` exists, no research → next phase: **research по готовому ТЗ** — not a new
   task. Say so: the contract is written, research starts from it rather than from the Jira summary.
   Mention the TZ's verdict if it fails the `/note tz` checks — research reading a draft contract
   should know it is a draft.
5. nothing matches → next phase: **research** (new task).

The real slug is the matched filename stem (`dev-541-discount-on-invoices`). For a new task, propose
one as `<key-lowercase>-<short-kebab-summary>`; the research agent finalizes it.

If the key's project ≠ the current project, note it: those artifacts live in another project's vault —
switch with `./start.sh <project>` first.

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
