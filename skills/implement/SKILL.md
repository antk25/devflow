---
name: implement
description: Phase 3 of devflow — execute a plan step-by-step under user control, then save a changelog entry to obsidian. Use after /plan, in a fresh session.
user_invocable: true
arguments:
  - name: slug
    description: Slug of the plan document (e.g. "dev-541-discount-on-invoices")
    required: true
---

# /implement — Phase 3: Step-by-step implementation

Read the plan for `<slug>` and walk through it under user control. At the end, write a short changelog entry to obsidian for review/handoff.

## Step 1: Read project context

1. Read `AGENTS.md` from cwd. Extract `project` and `vault` from frontmatter.
2. Read `<vault>/plans/<slug>.md`. If missing, stop and tell the user to run `/plan <slug>` first.
3. Read the linked research doc if it's still useful for context.

## Step 2: Confirm starting state

Before touching code:

- Show the user the list of steps from the plan.
- Confirm which step to start at (usually step 1, but the user may resume mid-flow).
- Check git state: working tree clean? On the right branch? If not, ask the user how to proceed — **do not** create branches or commit automatically.

## Step 3: Execute steps under user control

For each step:

1. **Restate the step** — name, goal, files, acceptance.
2. **Implement** — make the code changes for this step only.
3. **Verify** — run the acceptance check (test, command, manual review). Fix issues before moving on.
4. **Stop and confirm** — pause. Wait for the user to approve before starting the next step.
5. **Capture learnings** — if during work a non-obvious pattern, rule, or gotcha emerged that should persist, ask the user: "Save to `notes/`?" If yes, write to `<vault>/notes/<short-title>.md`.

The user controls the cadence. They may:
- Skip steps.
- Modify the plan mid-flow (in that case, update `<vault>/plans/<slug>.md` to reflect reality before continuing).
- Stop early.
- Commit between steps (manually, via `git`).

## Step 4: Write the changelog entry

When the user signals "done" (all intended steps finished, or stopping point reached), write `<vault>/changelog/<YYYY-MM-DD>-<slug>.md`:

```markdown
# <Task title> — Changelog

**Date:** YYYY-MM-DD
**Plan:** [[plans/<slug>]]
**Status:** <done | partial | blocked>
**Branch:** <branch name>

## Summary
<2-3 lines: what was actually accomplished>

## Added
- <user-visible additions>

## Changed
- <user-visible changes>

## Removed
- <removals>

## Files
- `path/one` — <what changed there>
- `path/two` — ...

## Tests
- <what was added/changed in tests>

## Open / follow-up
- [ ] <unfinished step>
- [ ] <known issue>
- [ ] <thing flagged for discussion>

## Notes for review
<anything a reviewer should pay attention to: trade-offs, surprises, deviations from plan>
```

If the work is partial or blocked, be explicit about what's incomplete and why. The changelog is what the user will share with colleagues or read when the task comes back for rework.

## Step 5: Confirm

```
✓ Changelog saved: <vault>/changelog/<YYYY-MM-DD>-<slug>.md

Branch: <branch>
Status: <done|partial|blocked>
```

Remind the user: `git push` and PR creation are manual.

## Rules

- **The user drives.** Pause between steps. Don't batch-implement.
- **No automatic git operations** beyond reading state. No auto-branch, no auto-commit.
- **Don't edit the tests when implementation fails.** Fix the implementation. (project convention)
- **Update the plan doc** if the work deviates from it — keep plan and reality in sync.
- **All notes in Russian** (project convention). Filenames stay latin.
- If a step turns out to be much bigger than planned, stop and suggest going back to `/plan` to revise.
