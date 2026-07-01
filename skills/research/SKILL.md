---
name: research
description: Phase 1 of devflow — gather context for a task and save a research document to obsidian. Use when starting a new task. Output is read by /plan in a fresh session.
model: opus
user_invocable: true
arguments:
  - name: task
    description: Task description or short title (e.g. "DEV-541 discount on invoices" or just "discounts")
    required: true
---

# /research — Phase 1: Context gathering

Investigate the task, gather context from the codebase, identify constraints, then save a research document to the project's obsidian vault. **Do not write code.** The output feeds `/plan` in a fresh session.

## Step 1: Read project context

1. Read `AGENTS.md` from the current working directory.
2. Parse the YAML frontmatter — extract `project` and `vault`.
3. If `AGENTS.md` is missing, stop and ask the user to create one from `AGENTS.md.template`.

## Step 2: Determine the slug

The slug is the filename stem for the research doc.

- If the user passed something slug-like (alphanumeric + dashes, no spaces), use it as-is.
- Otherwise, propose a slug derived from the task (kebab-case, ≤40 chars). Confirm with the user before writing.

Example: `"DEV-541 discount on invoices"` → suggest `dev-541-discount-on-invoices`.

## Step 3: Investigate

Work with the user to gather context. The depth depends on the task. Typical activities:

- **Read the TZ** if there is one: check `<vault>/tz/` for an existing spec under the same slug.
- **Find relevant code** — grep for symbols, read the files that will be touched.
- **Identify constraints** — existing conventions (from `AGENTS.md`), patterns in similar features, dependencies.
- **Ask clarifying questions** when requirements are ambiguous. Don't guess.
- **Note open questions** that should be answered before planning.

Keep notes mentally — you will write them to disk in step 4.

## Step 4: Save the research document

Write to `<vault>/research/<slug>.md` with this structure:

```markdown
# <Task title>

**Date:** YYYY-MM-DD
**Status:** research
**TZ:** <link to vault/tz/<slug>.md if exists, else "—">

## Problem
<2-4 lines: what needs to happen and why>

## Context
### Relevant files
- `path/to/file.ext` — <one-line role>
- ...

### How it works today
<short prose: existing flow, key entities, where the change lands>

### Constraints
- <conventions from AGENTS.md that apply>
- <existing patterns to follow / avoid>
- <external dependencies, API contracts, data shapes>

## Findings
<key insights from the investigation — non-obvious things the planner needs to know>

## Suggested direction
<high-level approach, NOT a step-by-step plan. 3-6 bullets max. The plan phase will detail it.>

## Open questions
- [ ] <question requiring user/stakeholder input>
- ...

## References
- <commits, PRs, docs, obsidian links>
```

If the file already exists, ask whether to overwrite, append, or pick a new slug.

## Step 5: Confirm

After writing, output:

```
✓ Research saved: <vault>/research/<slug>.md

Next: in a new session, run
  /plan <slug>
```

## Rules

- **No code changes.** This phase is read-only on the codebase.
- **All notes in Russian** (project convention from CLAUDE.md). Filenames stay latin.
- **Ask, don't assume.** If a requirement is ambiguous, ask the user.
- **Be terse.** The research doc is for a future session — it should be skim-able, not exhaustive.
- If the task is trivial (one-line fix, typo), say so and suggest skipping straight to implementation without a doc.
