---
name: plan
description: Phase 2 of devflow — read a research document and produce a step-by-step implementation plan in obsidian. Use after /research, in a fresh session. Output is read by /implement.
user_invocable: true
arguments:
  - name: slug
    description: Slug of the research document (e.g. "dev-541-discount-on-invoices")
    required: true
---

# /plan — Phase 2: Implementation plan

Read the research document for `<slug>`, optionally re-check the relevant code, then write a step-by-step plan to obsidian. **Do not write production code.** The output feeds `/implement`.

## Step 1: Read project context

1. Read `AGENTS.md` from the current working directory.
2. Parse frontmatter — extract `project` and `vault`.
3. If `AGENTS.md` is missing, stop.

## Step 2: Read the research document

1. Read `<vault>/research/<slug>.md`. If missing, stop and tell the user to run `/research <task>` first.
2. If there are unanswered "Open questions" in the doc — ask the user to answer them before continuing. Update the research doc with the answers.

## Step 3: Sanity-check the codebase

Quickly verify that the assumptions in the research doc still hold:
- Files mentioned still exist at the same paths.
- No major changes since the research doc was written that invalidate it.

If you find drift, update the research doc with corrections before planning.

## Step 4: Build the plan

Decompose the work into **atomic steps**. Rules for steps:

- Each step is independently reviewable (a single commit's worth of change).
- Each step has a clear "done" criterion.
- Steps are ordered so the project stays buildable between them where possible.
- Tests live in the same step as the code they cover (project convention).
- Prefer **vertical slices** when feature spans backend+frontend — each slice should produce something demonstrable.

For each step, capture:
- **Goal** — one line.
- **Files** — paths to touch (best-effort).
- **Notes** — gotchas, dependencies on other steps, conventions to follow.
- **Acceptance** — how you verify the step is done.

## Step 5: Save the plan document

Write to `<vault>/plans/<slug>.md` with this structure:

```markdown
# <Task title> — Plan

**Date:** YYYY-MM-DD
**Research:** [[research/<slug>]]
**Status:** plan

## Goal
<2-3 lines, restated from research>

## Approach
<short prose explaining the chosen direction and why — picks one path from research's "Suggested direction">

## Steps

### 1. <Step name>
- **Goal:** <one line>
- **Files:**
  - `path/one`
  - `path/two`
- **Notes:** <gotchas, dependencies>
- **Acceptance:** <how to verify>

### 2. <Step name>
...

## Test strategy
<which tests run at which step, what's covered, what's manual>

## Acceptance (overall)
- [ ] <user-visible criterion>
- [ ] <another>

## Risks / unknowns
- <thing that might bite>
```

If the file exists, ask: overwrite, append revision, or new slug.

## Step 6: Confirm

```
✓ Plan saved: <vault>/plans/<slug>.md

Next: in a new session, run
  /implement <slug>
```

## Rules

- **No code changes.** Only the plan document.
- **All notes in Russian** (project convention). Filenames stay latin.
- **Be specific.** Vague steps ("refactor the service") are useless to the implementer. Say what changes and where.
- **Be honest about unknowns.** If a step needs investigation during implementation, mark it. Don't fake certainty.
- If the research is too thin to plan from, push back and ask the user to deepen `/research` first.
