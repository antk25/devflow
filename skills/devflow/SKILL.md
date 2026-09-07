---
name: devflow
description: DevFlow driver — run the research → plan → implement pipeline as autonomous phase agents with an explicit approval gate between phases. No arg — Jira standup → pick a task → route → run. With <slug> — skip standup, resume at the right phase. Session runs on opus.
user_invocable: true
model: opus
arguments:
  - name: slug
    description: "Optional: task slug (e.g. dev-541-discount-on-invoices) to skip standup and route directly"
    required: false
---

# /devflow — pipeline driver (standup → route → phase agent → gate → next)

Interactive orchestrator. Spawns the `research` / `plan` / `implement` phase agents (each with its
own frontmatter model — opus / opus / sonnet), shows you each artifact, and **waits for your
explicit approval at each gate** before the next phase. You control git throughout — the driver
never branches or commits, and neither does `implement`.

Keep this thin: the driver only routes, shows artifacts, holds gates, and relays answers. **All
phase logic lives in the agent bodies** — don't re-implement a phase here.

## Inputs
- `/devflow` — start from the Jira standup.
- `/devflow <slug>` — skip standup, route by the slug, resume at the right phase (this replaces the
  old per-phase `/research` `/plan` `/implement` entry points).

## Step 0: Project context
Read `AGENTS.md` from cwd → `project`, `vault`. Each phase agent re-reads it itself; you need
`vault` for routing.

## Step 1: Pick the task  (skip if a slug was given)
Run the standup flow (same script `/standup` uses, never MCP):
```bash
bash ~/.config/devflow/integrations/jira-digest.sh
```
Show the digest **as printed**, `⏳ ждут тебя` bucket first — those are the tasks where the last
comment isn't yours, oldest on top. Let the user pick a Jira key. Derive the slug: the matched artifact's stem, or —
for a new task — propose `<key-lowercase>-<short-kebab-summary>` (the research agent finalizes it).
If the digest errors (creds / network / 401), surface it plainly and stop; do **not** use MCP.

## Step 2: Route
Glob the vault case-insensitively (key is the slug prefix). **The plan is checked before the
changelog** — with steps, a changelog appears after the *first* step, so its mere existence no
longer means the task is closed.

- `plans/<slug>*.md` exists → read **its frontmatter only**, not the body. Parse the YAML block
  between the leading `---` fences; never grep the file for `steps:` — a plan that documents the
  format has that word in a code fence, and grep will route off a worked example:
  - `steps` present → the **frontier** is every step with `status: open` whose every `blocked_by`
    entry is `done`. Non-empty → start at **implement, step N** (lowest number on the frontier).
    Empty (all `done`) → **closed**.
  - `steps` absent → legacy plan, written before steps existed. A changelog for it → **closed**
    (that is how a task finished the old way looks; don't reopen it as step 1). No changelog → all
    steps open, no blockers: count the `### <n>.` headings in the body, offer **step 1**, and let
    the user name a different number.
- `changelog/*-<slug>*.md` exists and the plan has no open frontier → **closed**. Ask: reopen
  (→ pick a phase) or stop.
- `research/<slug>*.md`, no plan → start at **plan**.
- `tz/<slug>*.md`, no research → start at **research по готовому ТЗ**, not as a new task: the
  contract already exists, so research starts from it instead of from the Jira summary. Pass that to
  the agent, and say if the TZ fails its `/note tz` checks — a draft contract is still a draft.
- nothing matches → start at **research** (new task).

Say the step out loud when you report the route: `implement, шаг 3 из 5` — never "продолжаю план".

Then tag the session so `/tokens` attributes this task's spend exactly. Best-effort —
if it fails, note it and carry on; never block the pipeline on it:
```bash
python3 ~/.claude/skills/tokens/token-stats.py --tag <KEY>
```

## Step 3: Run the phase → gate → repeat
Loop from the routed phase until the plan's frontier is empty.

**a. Spawn the phase agent** with the Agent tool:
- `subagent_type: research | plan | implement`
- Thin prompt only: the cwd, the slug, and "read AGENTS.md and your input artifact, do your phase,
  write the artifact, return your hand-off." Nothing more — the agent body holds the logic.
- For `implement`, the prompt also carries **the step number**. Never spawn it without one — it
  refuses, by design: one run is one step, from a fresh context window.

**b. On return — `research` / `plan` (gated):**
1. Read and show the artifact (`<vault>/research/<slug>.md` or `<vault>/plans/<slug>.md`).
2. If the agent returned **Open questions / open decisions**, ask the user, then **SendMessage the
   answers to the same agent** (its context is intact) so it finalizes the doc in place. Re-show the
   changed sections.
3. **GATE:** ask for explicit approval ("одобряешь?"). Advance only on a clear yes. On "no" or edits,
   relay them via SendMessage to the same agent and re-gate.

**c. On return — `implement` (autonomous, not gated):**
- Status `done` → show the step's changelog section, then **re-read the plan's frontmatter** and
  recompute the frontier:
  - frontier non-empty → spawn a **fresh** `implement` agent on the next step. A new agent per step
    is the point; never continue in the one that just finished.
  - frontier empty → the pipeline is complete; show the changelog.
- Status `blocked` / `partial` → the step stays `open` on the frontier. Show the stop reason +
  changelog and **stop; the user decides** (fix manually, or `/devflow <slug>` back into plan to
  revise). Never push through a red state, and never skip ahead to a later step.

**d. Advance:** after a gate approval, re-route (Step 2) — the just-written artifact moves the task
to the next phase — and spawn the next agent. Continue until the frontier is empty.

## Rules
- **Gates are explicit.** Never advance research → plan → implement without a clear user "yes".
  Steps inside `implement` are not gates — they run one after another, each in a fresh agent.
- **The frontier comes from the frontmatter.** Compute it by parsing the `steps` block; don't read
  the plan body to work out what's done.
- **git is manual** end to end. No auto-branch, no auto-commit, no push — driver or agent.
- **One task at a time.** Finish or stop the current task before starting another.
- **Slug ↔ key:** the key is the slug's prefix; routing and digest both derive from it, no mapping file.
- **Degradation:** digest errors surface to the user; never fall back to Atlassian MCP.
