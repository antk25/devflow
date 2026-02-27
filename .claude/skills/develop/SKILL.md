---
name: develop
description: Autonomous feature development - plan, implement, test, review with automatic git workflow
user_invocable: true
arguments:
  - name: feature
    description: Feature description to develop
    required: true
---

# /develop - Autonomous Development Skill

This skill provides fully autonomous feature development. It handles the entire workflow from planning to implementation to testing to review, with automatic git branching and commits.

## Usage

```
/develop Add user authentication with JWT
/develop Create new payment integration
/develop Implement dashboard analytics
```

## Auto-Detection (Smart Routing)

The `/develop` command intelligently routes to specialized workflows based on keywords:

### Routes to `/fix` (Quick Bug Fix)
Keywords: fix, bug, broken, error, TypeError, undefined, null, not working, doesn't work, fails, исправ, баг, сломан, ошибка

```
/develop Fix login button     → automatically uses /fix workflow
/develop Bug in pagination    → automatically uses /fix workflow
```

### Routes to `/refactor` (Code Refactoring)
Keywords: refactor, clean up, cleanup, restructure, reorganize, extract, рефактор, рефакторинг, очистить, реструктур

```
/develop Refactor auth service → automatically uses /refactor workflow
/develop Clean up utils        → automatically uses /refactor workflow
```

### Stays as `/develop` (Full Feature)
No matching keywords → uses full development pipeline

```
/develop Add user authentication → full pipeline
/develop Create payment system   → full pipeline
```

## Workflow Selection Instructions

**BEFORE starting any work, check the feature description for keywords:**

```python
FIX_KEYWORDS = [
    "fix", "bug", "broken", "error", "typeerror", "undefined",
    "null", "not working", "doesn't work", "fails", "failing",
    "исправ", "баг", "сломан", "ошибка", "не работает"
]

REFACTOR_KEYWORDS = [
    "refactor", "clean up", "cleanup", "restructure", "reorganize",
    "extract", "rename", "move", "inline", "simplify",
    "рефактор", "рефакторинг", "очистить", "реструктур", "выделить"
]

# Tasks requiring Deep Trace analysis before implementation
BUSINESS_LOGIC_KEYWORDS = [
    "analytics", "calculation", "depends on", "event", "status",
    "lifecycle", "sync", "import", "export", "trigger", "handler",
    "listener", "when", "after", "before", "on change", "filter",
    "aggregate", "count", "sum", "report", "очистка", "удаление",
    "пересчет", "синхронизация", "событие", "статус", "аналитик"
]
```

**If FIX_KEYWORDS match:**
→ Follow /fix workflow (search → implement → test → commit)

**If REFACTOR_KEYWORDS match:**
→ Follow /refactor workflow (analyze → refactor → validate → test → commit)

**If BUSINESS_LOGIC_KEYWORDS match:**
→ Continue with /develop workflow, **but require Phase 1.5: Deep Trace**

**Otherwise:**
→ Continue with full /develop workflow (Phase 1.5 optional)

## What It Does

Config → Work Branch → (Trace) → Plan → Contract → (Tests) → Implement → Validate → E2E → Commit → Review → (Fix) → Summary

Key agents: PM, Tracer, Architect, JS/PHP Developer, Architecture Guardian, Tester, Code Reviewer.
You control only the final `git push`.

## Branch Strategy

```
feature/xxx-work  ← All iterations, fixes, refactoring (messy history OK)
       ↓
feature/xxx       ← Clean atomic commits (created by /finalize)
```

- **Work branch** (`-work`): created at start, all implementation here, WIP commits OK, kept as backup
- **Final branch**: created from main by `/finalize`, atomic commits, ready for PR

## Instructions

You are the autonomous development orchestrator. Execute the full pipeline without asking for confirmations.

### Resume Check

Before Phase 0, check if this is a resumed session:

1. Read `.claude/data/sessions.json`
2. If `--resume` flag is present in the feature description OR the feature description closely matches an existing session's `feature` field:
   - Search `sessions` for a matching entry (by branch name or feature text)
   - If found with status `running` or `interrupted`:
     - Load the session's `phase_data` to restore context
     - Set `current_phase` from the session
     - Skip all phases listed in `completed_phases`
     - Print: `"Resuming session <branch> from <current_phase>..."`
     - Jump directly to the `current_phase` and continue the pipeline
   - If not found: proceed as new session
3. If new session: will be created in Phase 0 (step 8)

---

## Phase Execution

For each phase below, **read the phase file before executing**:

```
# Before executing Phase N:
Read file: .claude/skills/develop/phases/phase-N-name.md
```

| Phase | File | When |
|-------|------|------|
| 0 | (inline below) | Always |
| 1 | `phases/phase-1-branch.md` | Always |
| 1.5 | `phases/phase-1.5-trace.md` | Business logic tasks |
| 2 | `phases/phase-2-plan.md` | Always |
| 2.5 | `phases/phase-2.5-contract.md` | Multi-layer features |
| 2.7 | `phases/phase-2.7-test-first.md` | If contract generated |
| 3 | `phases/phase-3-implement.md` | Always |
| 3.5 | `phases/phase-3.5-test-isolation.md` | Always |
| 4 | `phases/phase-4-validate.md` | Always |
| 5 | `phases/phase-5-e2e.md` | Always |
| 6 | `phases/phase-6-commit.md` | Always |
| 6.5 | `phases/phase-6.5-test-reaction.md` | Always |
| 7 | `phases/phase-7-review.md` | Always |
| 8 | `phases/phase-8-fix.md` | If critical issues |
| 9 | `phases/phase-9-summary.md` | Always |

**CRITICAL:** Read the phase file BEFORE executing each phase. Do NOT rely on memory — the phase file contains exact instructions, prompts, and formats.

---

### Phase 0: Read Project Configuration

**CRITICAL:** Before any work, read project configuration using scripts:

```bash
# 1. Get project config (repos, testing, conventions, branch prefix)
PROJECT_CONFIG=$(./scripts/read-project-config.sh)

# 2. Get git context for each repository
for repo in $(echo "$PROJECT_CONFIG" | jq -r '.repositories | values[]'); do
  ./scripts/git-context.sh "$repo"
done
```

3. **Read project documentation** (if files exist per `PROJECT_CONFIG.files`):
   - `.claude/CLAUDE.md` — conventions
   - `.claude/patterns.md` — architecture patterns (if > 100 lines, log warning: "patterns.md exceeds 100 lines — consider trimming to examples only")
   - `CONTRIBUTING.md` — contribution guidelines

4. **Query RAG knowledge base** for project context (run both queries in parallel):
   - Query 1: `mcp__local-rag__query_documents(query: "<project_name> architecture patterns conventions code style", limit: 10)`
   - Query 2: `mcp__local-rag__query_documents(query: "<project_name> <feature_keywords> implementation", limit: 8)`
   - Filter results: only include chunks with **score < 0.45** (relevant)
   - Format filtered results as `rag_context` block (max ~2000 chars total)
   - If no results pass the score filter or RAG unavailable, skip silently

5. **Load lessons learned** (if `PROJECT_CONFIG.files.has_lessons_learned` is true):
   - Read `<project_path>/.claude/data/lessons-learned.md`
   - Store contents as `lessons_context`

6. **Initialize session tracking** (if not resuming):
   - Read `.claude/data/sessions.json`
   - Create a new session entry keyed by the work branch name:
     ```json
     {
       "skill": "develop",
       "feature": "<feature description>",
       "project": "<project_name>",
       "started_at": "<ISO8601 timestamp>",
       "updated_at": "<ISO8601 timestamp>",
       "status": "running",
       "current_phase": "phase_1_branch",
       "completed_phases": ["phase_0_config"],
       "phase_data": {},
       "loops": {
         "arch_validation": { "attempt": 0, "max_attempts": 3, "diff_hashes": [], "failures": [] },
         "review_fix": { "attempt": 0, "max_attempts": 2, "diff_hashes": [], "failures": [] },
         "test_fix": { "attempt": 0, "max_attempts": 2, "diff_hashes": [], "failures": [] }
       },
       "branches": { "work": "<work_branch_name>", "final": "<final_branch_name>" },
       "repos": ["<repo_names>"],
       "worktree_paths": { "<repo_name>": "<worktree_path>" }
     }
     ```
   - Write updated sessions.json back to disk

## Error Handling

**Session failure:** Set `status: "failed"` in sessions.json, store error in `phase_data.<phase>.error`, present to user with `"To resume: /develop --resume <feature>"`.

**Interrupted session:** Resume Check finds `status: running` and picks up from `current_phase`.

**Git not found:** Always use explicit repo path from project config: `cd /path/to/actual/repo && git ...`

**E2E tests fail:** Attempt fix with developer agent, re-test once. If still failing, report to user and continue with review.

**Implementation fails after 3 attempts:** Commit partial progress, document blockers, report to user.

## Autonomous Mode Rules

1. **NO confirmations** - Execute all steps automatically
2. **NO questions** - Make reasonable decisions
3. **Explicit paths** - Always use absolute paths to repos
4. **E2E testing** - Always attempt E2E verification
5. **Work branch commits** - Commit freely during development (messy OK)
6. **Stop on work branch** - Do NOT finalize; user reviews and runs `/finalize` when ready
7. **Fix automatically** - Architecture, test, and review issues
8. **Keep backup** - Never delete work branch
9. **Report at end** - Single comprehensive summary
10. **Never push** - User controls the final push

## Agent Spawning

Agents inherit permissions from settings.json. The auto-approve hook enables autonomous operation.

**CRITICAL:** Always pass the absolute repository path to agents, and instruct them to use absolute paths for all file operations and git commands.
