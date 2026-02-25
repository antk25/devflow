---
name: next
description: Wrap up current task and prepare for the next one
user_invocable: true
arguments:
  - name: summary
    description: "Optional: brief summary of what was done (auto-generated if omitted)"
    required: false
---

# /next - Task Transition Skill

Wraps up the current task context and prepares for the next one. Designed for switching between tasks within the same project without losing project context.

## Usage

```
/next                            # Wrap up current task, prompt to /clear
/next done with DEV-505 fix      # Wrap up with explicit summary
```

## Instructions

### Phase 1: Summarize Current Task

1. Read `.claude/data/sessions.json` — find any `running` session for the active project
2. Read `.claude/data/projects.json` — get active project name
3. If the session has a `phase_history` array, render a timeline table:
   ```markdown
   ### Phase Timeline
   | Phase | Duration | Result |
   |-------|----------|--------|
   | Config | 12s | success |
   | Plan | 2m 30s | success |
   | Implement | 8m 15s | success |
   | E2E | 0s | skipped (server not running) |
   | **Total** | **11m** | |
   ```
   - Duration formatting: `<60s` → `Ns`, `>=60s` → `Nm Ns`, `>=3600s` → `Nh Nm`
   - If `result` is not `success`, append reason in parentheses
   - Total is the sum of all `duration_seconds`
4. Generate a brief summary of the current conversation's work:
   - What was the task/issue?
   - What was done? (files changed, commits made)
   - Current status (completed, in progress, blocked)
   - If the user provided a summary in args, use that instead of auto-generating

### Phase 2: Save Summary

1. If a `running` session exists in `sessions.json`, update it:
   - Set `status` to `completed` (or `interrupted` if work is unfinished)
   - Update `updated_at`
   - Add summary to `phase_data`

2. **Append result to TZ in Obsidian:**
   - Read `obsidian_vault` from `.claude/data/projects.json`
   - Look for the TZ file: `<obsidian_vault>/projects/<project>/tz/<branch>-*.md`
     - Use the session's branch name (from `sessions.json` → `branches.final` or `branches.work`)
     - If multiple matches, use the first one
   - If TZ file found, append a `## Результат` section at the end:
     ```markdown

     ## Результат

     **Дата:** <YYYY-MM-DD>
     **Статус:** завершено | в процессе | заблокировано
     **Ветка:** `<branch_name>`

     <summary text>

     **Изменённые файлы:**
     - <list of changed files from git diff --name-only main..branch, or from session context>

     **Команда после деплоя:** <if any post-deploy command was discussed, include it>
     ```
   - If TZ file not found, skip silently (not all tasks have a TZ)

3. Display the wrap-up:

```markdown
## Task wrapped up

**Project:** <active_project>
**Task:** <task description or branch name>
**Status:** completed
**Summary:** <brief summary>

---

Run `/clear` to reset context, then start your next task.
Project context will be restored automatically.
```

### Phase 3: Instruct /clear

Tell the user to run `/clear`. After `/clear`:
- CLAUDE.md reloads automatically (startup greeting)
- SessionStart hook restores active project (Serena activation, memories)
- User can immediately start the next task

---

## Notes

- This skill does NOT modify any code or git state
- It's purely for context management between tasks
- If no active session exists, just show the "ready to clear" message
- The skill is lightweight — no agents spawned, no file searches
