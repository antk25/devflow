---
name: quick
description: Lightweight single-session entry — quick recon, inline plan, controlled edits, one compact changelog. For small tasks that don't warrant the full research→plan→implement pipeline.
model: sonnet
user_invocable: true
arguments:
  - name: task
    description: Task description or short title (e.g. "fix typo in error message" or "DEV-541 discount tweak")
    required: true
---

# /quick — Lightweight single-session entry

Collapse research → plan → implement into one session, for tasks too small to justify three separate sessions and three docs. The user decides when to reach for `/quick` instead of `/research`; this skill's job is to catch runaway scope, not to gatekeep entry.

## Step 1: Read project context

1. Read `AGENTS.md` from cwd. Extract `project` and `vault` from frontmatter.
2. If missing, stop and ask the user to create one from `AGENTS.md.template`.

## Step 2: Determine the slug

Same rule as `/research`:
- If the task description is slug-like (alphanumeric + dashes, no spaces), use it as-is.
- Otherwise, propose a slug (kebab-case, ≤40 chars) derived from the task. Confirm with the user before writing anything.

## Step 3: Fast recon + pushback

Do a light version of `/research` Step 3: grep for the relevant symbols, read the files that would be touched. No research doc gets written.

**Assess scope.** If the task looks like it needs the full pipeline — many files, an architectural decision, real risk, or unclear requirements — say so explicitly: "This looks like it needs the full pipeline — run `/research` instead." Then ask: "Continue with quick anyway? [y/N]". If the user declines, stop here without writing any code.

## Step 4: Inline plan

Post a numbered plan **in the chat**, ≤5 lines. No plan file gets written. Wait for the user's explicit confirmation before touching any code.

## Step 5: Implement under user control

Same discipline as `/implement` Step 3, one inline-plan step at a time:

1. Restate the step.
2. Implement — make the change for this step only.
3. Verify — run the acceptance check (test, command, manual review). Fix issues before moving on.
4. Stop and confirm — pause, wait for approval before the next step.

No automatic git operations. The user may skip steps, stop early, or commit manually between steps.

## Step 6: Out-of-scope observations

If the work surfaced tech debt, a bug, a missing test, or an optimization outside the task's scope, save it via `/note save` (category `notes`, filename `<slug>-observations.md`). Skip this step entirely if there's nothing to report — never write an empty block.

## Step 7: Compact changelog

Write `<vault>/changelog/<YYYY-MM-DD>-<slug>.md`:

```markdown
# <Task title> — Quick Changelog

**Date:** YYYY-MM-DD
**Mode:** quick
**Status:** <done | partial | blocked>
**Branch:** <branch name>

## План (свёрнуто)
1. <inline plan step 1>
2. <inline plan step 2>

## Что сделано
- <what actually happened, by file, briefly>

## Files
- `path` — <what changed>

## Наблюдения вне scope
- [[notes/<slug>-observations]] — <one line> (section only if observations exist)

## Notes for review
<optional: surprises, deviations>
```

## Step 8: Confirm

```
✓ Changelog saved: <vault>/changelog/<YYYY-MM-DD>-<slug>.md

Branch: <branch>
Status: <done|partial|blocked>
```

Remind the user: `git push` and PR creation are manual.

## Rules

- **The user decides when to invoke `/quick`.** This skill's only gatekeeping is the Step 3 pushback — it doesn't second-guess the user's choice beyond that.
- **The user drives.** Pause between steps. Don't batch-implement.
- **No automatic git operations** beyond reading state.
- **Don't edit tests when implementation fails.** Fix the implementation.
- **All notes in Russian** (project convention). Filenames stay latin.
- **Model is fixed for the session.** If the task turns out to need real reasoning mid-flow, tell the user to switch with `/model opus` — `/quick` won't do it for you.
- If a step turns out much bigger than planned, stop and suggest `/research` + `/plan` instead.
