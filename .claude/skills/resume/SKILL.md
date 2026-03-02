---
name: resume
description: Resume an interrupted development session from where it left off
user_invocable: true
arguments:
  - name: target
    description: Branch name, or "list" to show all interrupted sessions
    required: false
---

# /resume - Resume Interrupted Session

Finds and resumes interrupted `/develop`, `/fix`, or `/refactor` sessions. Restores full context (plan, contract, trace) and continues the pipeline from the exact phase where it stopped.

## Usage

```
/resume                     # Resume the most recent interrupted session for active project
/resume <branch>            # Resume a specific session by work branch name
/resume list                # Show all interrupted/running sessions
```

## Instructions

You are the session resume handler. Follow these steps precisely.

### Step 0: Read Configuration

Read project config from the DevFlow root directory:

```bash
DEVFLOW_DIR="/home/smg25/projects/devflow"
PROJECT_CONFIG=$("$DEVFLOW_DIR/scripts/read-project-config.sh")
```

Extract `project_name` from the active project in `projects.json`.

---

### Step 1: Parse Arguments

- If argument is `list` → go to **List Mode**
- If argument is a branch name → go to **Find by Branch**
- If no argument → go to **Find Latest**

---

### List Mode

1. Read `.claude/data/sessions.json`
2. Filter sessions where:
   - `project` matches active project
   - `status` is `running` or `interrupted`
3. Sort by `updated_at` descending
4. Display:

```markdown
## Interrupted Sessions — <project>

| # | Branch | Skill | Feature | Phase | Updated |
|---|--------|-------|---------|-------|---------|
| 1 | feature/DEV-520-work | /develop | Async recalculation | Phase 3 (4/7) | 2026-02-27 12:45 |
| 2 | fix/login-500 | /fix | Fix login 500 error | Phase 2 | 2026-02-26 15:30 |

Resume with: `/resume <branch>`
```

5. If no interrupted sessions found:
```
No interrupted sessions for <project>.
```

6. **Stop here** — do not proceed further.

---

### Find by Branch

1. Read `.claude/data/sessions.json`
2. Search for a session where `branches.work` matches the argument (exact match first, then prefix match)
3. If not found, also try matching the session key directly
4. If multiple matches found → show list and ask user to choose
5. If still not found:
```
Session not found for branch "<argument>".
Use /resume list to see available sessions.
```
6. If found → go to **Validate & Resume**

---

### Find Latest

1. Read `.claude/data/sessions.json`
2. Filter sessions where:
   - `project` matches active project
   - `status` is `running` or `interrupted`
3. Sort by `updated_at` descending
4. If none found:
```
No interrupted sessions for <project>.
```
5. If exactly one → go to **Validate & Resume**
6. If multiple → show list (like List Mode) and ask user to choose with `AskUserQuestion`

---

### Validate & Resume

**Step 2: Validate State**

1. Check if the work branch exists in git:
   ```bash
   git -C <repo_path> branch --list "<work_branch>"
   ```
   - If not found → Error: `Branch <work_branch> not found. Session cannot be restored. Clean up the session entry?`

2. Check for uncommitted changes on current branch:
   ```bash
   git -C <repo_path> status --porcelain
   ```
   - If dirty → Warning: `Current branch has uncommitted changes. Stash or commit before resuming.`

3. Check if worktree exists (if `worktree_paths` is set in session):
   ```bash
   test -d "<worktree_path>"
   ```
   - If worktree missing → it will be recreated in the pipeline

**Step 3: Display Session Info**

Show the session state to the user:

```markdown
## Resuming: <feature>

| Field | Value |
|-------|-------|
| Skill | /<skill> |
| Branch | <work_branch> |
| Started | <started_at> |
| Interrupted | Phase <N> (<phase_name>) |

### Completed Phases
<for each phase in completed_phases:>
- ✅ <phase_name> (<duration from phase_history>)
  <if phase_data exists: show key info>

### Current Phase
- ⏸️ <current_phase>
  <if phase_data exists for current phase: show progress>

### Remaining Phases
<for each phase NOT in completed_phases and not current:>
- ⬚ <phase_name>

### Context Available
<list what phase_data contains:>
- Plan: <plan_summary preview> (if exists)
- Contract: <contract_path> (if exists)
- Trace: <trace_summary preview> (if exists)
- Implementation: <tasks_completed> (if exists)

### Loop State
<for each loop type:>
- <loop_name>: <attempt>/<max_attempts>
```

**Step 4: Confirm and Resume**

Since DevFlow operates in autonomous mode, proceed immediately (no confirmation needed).

1. Update session status:
   ```python
   session['status'] = 'running'
   session['updated_at'] = now
   ```

2. Switch to the work branch:
   - If `worktree_paths` is set in the session → `cd` to the worktree directory (branch is already checked out there)
   - Otherwise → `git -C <repo_path> checkout <work_branch>`

3. Determine which skill to invoke based on `session.skill`:
   - `develop` → invoke `/develop`
   - `fix` → invoke `/fix`
   - `refactor` → invoke `/refactor`

4. Build the resume invocation. Pass the original feature description with `--resume` flag:
   ```
   Skill(skill: "<session.skill>", args: "--resume <work_branch>\n\n<session.feature>")
   ```

**IMPORTANT:** The target skill (e.g., `/develop`) already has Resume Check logic built in. It will:
- Find the session by branch name in sessions.json
- Load `phase_data` to restore context (plan, contract, trace)
- Skip all `completed_phases`
- Continue from `current_phase`

---

## Error Handling

| Situation | Behavior |
|-----------|----------|
| Branch deleted | Error with suggestion to clean session entry |
| Contract file missing | Warning: "Contract not found, Phase 2.5 will be re-run" — let the pipeline handle it |
| Worktree missing | Pipeline will recreate it in Phase 1 |
| Uncommitted changes | Warn user, suggest stash |
| Session from different project | Skip (filter by active project) |
| Status is "completed" | Skip (not resumable) |
| Status is "failed" | Show info with error details, offer to retry from scratch or skip |
| Status is "review_ready" | Show info but note: "This session completed development. Use /finalize to create clean branch." |

## Skill-Specific Resume Support

| Skill | Resume Support | Notes |
|-------|---------------|-------|
| `/develop` | Full | Resume Check in SKILL.md, skips completed phases, restores context |
| `/fix` | Limited | Re-runs from scratch but with original bug context preserved from sessions.json |
| `/refactor` | Limited | Re-runs from scratch but with original task context preserved |

For `/fix` and `/refactor`, the `--resume` flag provides context (what was being fixed, what was already tried) but the pipeline runs from Phase 0. This is acceptable because these skills are fast (5-15 min) and don't have expensive planning/contract phases.

## Notes

- The `/resume` skill is a **dispatcher** — it finds the session, validates state, shows info, and delegates to the original skill
- All actual resume logic (phase skipping, context loading) lives in each skill's Resume Check
- Sessions with `status: running` that are stale (no update for >1 hour) are treated as likely interrupted
- `mark-interrupted` uses a 5-minute staleness window to avoid marking sessions actively running in other terminals
