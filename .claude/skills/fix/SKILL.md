---
name: fix
description: Quick bug fix - search, implement, test without planning overhead
user_invocable: true
arguments:
  - name: issue
    description: Bug description or issue to fix
    required: true
---

# /fix - Quick Bug Fix Skill

This skill provides a streamlined workflow for fixing bugs and small issues. Skips planning phase for faster iteration.

## Usage

```
/fix Login button not responding
/fix TypeError in user profile page
/fix Fix broken pagination in API
```

## What It Does

1. **Reads project config** (conventions, repositories)
2. **Searches for the issue** (finds relevant code)
3. **Analyzes the problem** (root cause)
4. **Implements the fix** (Developer agent)
5. **Runs tests** (unit + affected E2E)
6. **Commits the fix** (following project conventions)
7. **Quick summary**

**NO planning phase** - goes directly from search to implementation.

## Instructions

You are the quick-fix orchestrator. Execute the fix pipeline efficiently without planning overhead.

### Phase 0: Read Project Configuration

```bash
# 1. Get project config
PROJECT_CONFIG=$(./scripts/read-project-config.sh)

# 2. Get git context for affected repos
for repo in $(echo "$PROJECT_CONFIG" | jq -r '.repositories | values[]'); do
  ./scripts/git-context.sh "$repo"
done
```

3. **Read project documentation** (if files exist per `PROJECT_CONFIG.files`):
   - `.claude/CLAUDE.md` — conventions

4. **Query RAG** for known issues context:
   - `mcp__local-rag__query_documents(query: "<project_name> <issue_keywords> bug fix error", limit: 5)`
   - Filter results: score < 0.55 (loose). If no results or RAG unavailable, skip silently.

5. **Load lessons learned** (if `PROJECT_CONFIG.files.has_lessons_learned` is true):
   - Read `<project_path>/.claude/data/lessons-learned.md`

6. **Initialize session tracking** (lightweight):
   - Read `.claude/data/sessions.json`
   - Create session entry keyed by fix branch name:
     ```json
     {
       "skill": "fix",
       "feature": "<issue description>",
       "project": "<project_name>",
       "started_at": "<ISO8601>",
       "updated_at": "<ISO8601>",
       "status": "running",
       "current_phase": "phase_1_branch",
       "completed_phases": ["phase_0_config"],
       "phase_data": {},
       "loops": {
         "test_fix": { "attempt": 0, "max_attempts": 2, "diff_hashes": [], "failures": [] }
       },
       "branches": { "fix": "<branch_name>" },
       "repos": ["<repo_names>"]
     }
     ```
   - Write sessions.json

### Phase 1: Create Fix Branch

**For EACH affected repository:**

```bash
./scripts/create-branch.sh fix <issue-slug> <repo_path>
```

The script handles prefix, slug conversion, dirty tree warnings, and existing branch detection.

### Phase 2: Search & Analyze

Search for the issue location:

```
Task(
  description: "Search: <issue>",
  prompt: "Find the root cause of this issue:

## Issue
<issue description>

<if rag_context is not empty, append:>

## Known Issues & Prior Fixes (from Knowledge Base)
<rag_context>

## Instructions
1. Search the codebase for relevant code
2. Identify the file(s) and line(s) causing the issue
3. Analyze the root cause
4. Propose a fix approach

Return:
- Affected files with line numbers
- Root cause analysis
- Proposed fix (brief)",
  subagent_type: "Explore",
  model: "sonnet"
)
```

### Phase 3: Implement Fix

Based on search results, spawn appropriate developer agent:

```
Task(
  description: "Fix: <issue>",
  prompt: "Fix this issue in repository: <repo_path>

## Issue
<issue description>

## Root Cause
<from Phase 2>

## Affected Files
<from Phase 2>

  <if lessons_context is not empty, append:>

  ## Lessons Learned (DO NOT repeat these mistakes)
  <lessons_context>

  <endif>

## TEST ISOLATION RULES (MANDATORY)
Do NOT create, edit, delete, or read any test files (files matching: *Test.php, *.test.ts, *.spec.ts, **/tests/**, **/test/**).
Fix only implementation code. If tests fail, fix the implementation — not the tests.

## Instructions
- Apply the minimal fix to resolve the issue
- Don't refactor unrelated code
- Ensure the fix doesn't break existing functionality
- Use absolute paths starting with <repo_path>",
  subagent_type: "<JS Developer|PHP Developer>"
)
```

### Phase 4: Run Tests

Run relevant tests using the test runner script:

```bash
./scripts/run-tests.sh <repo_name> unit <TestFilter>
```

The script handles framework detection (phpunit/jest/maven/playwright), applies filters correctly, and outputs troubleshooting hints on failure.

If tests fail, use loop detection:

```bash
HASH=$(echo "<failing_test_output>" | md5sum | cut -d' ' -f1)
DECISION=$(./scripts/check-loop.sh <branch> test_fix "$HASH")
```

- **CONTINUE** → re-spawn developer with: `"Previous fix didn't resolve: <test_output>. Try a different approach."`, re-run tests
- **LOOP_DETECTED** or **GIVE_UP** → add warning to summary, continue to commit phase (partial fix may still be valuable)

### Phase 5: Quick E2E Verification

If project has E2E config:

```bash
./scripts/e2e-check.sh backend /api/affected-endpoint
./scripts/e2e-check.sh frontend
```

The script checks server availability first and outputs start instructions if not running.
If exit code is 2 (server not running), note as "⏭️ Skipped" in summary.

### Phase 6: Commit Fix & Test Reaction

**Step 1: Commit**

```bash
cd /path/to/repo
git add <affected-files>
git commit -m "fix: <brief description>

<issue description>
Fixes: <root cause>

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

**Step 2: Test Reaction (verification)**

Run a quick verification that the fix didn't break other tests:

```bash
./scripts/test-reaction.sh <repo_name>
```

- If `TEST_REACTION: PASSED` → continue to Phase 7
- If `TEST_REACTION: FAILED` → spawn developer agent to fix (1 attempt max, since Phase 4 already ran tests). On second failure, warn and continue.

### Phase 7: Quick Summary

**Mark session complete:** Read sessions.json, set session `status: "completed"`, `updated_at` to now, write back. If fix failed, set `status: "failed"`.

**Desktop notification:**
```bash
# On success:
./scripts/notify.sh "Bug Fixed" "<issue-slug> — ready for push"
# On failure:
./scripts/notify.sh "Fix Failed" "<issue-slug> — see summary" critical
```

```markdown
## ✅ Bug Fixed: [Issue]

### Root Cause
[Brief explanation]

### Fix Applied
| File | Change |
|------|--------|
| `path/file.ts:42` | [What was fixed] |

### Tests
- Unit: ✅ Passed (X tests)
- E2E: ✅ Passed (or ⏭️ Skipped)

### Commits
- `abc1234` - fix: login button click handler

### Next Steps
```bash
# Review the fix
git diff main

# Push when ready
git push -u origin fix/login-button-not-responding
```
```

## When NOT to Use /fix

Use `/develop` instead if:
- The issue requires significant new code (>50 lines)
- Multiple components need changes
- New files need to be created
- The fix requires architectural decisions

## Auto-Detection

The `/develop` command will automatically route to `/fix` if the description contains:
- "fix", "bug", "broken", "исправ", "баг", "сломан"
- "error", "TypeError", "undefined", "null"
- "not working", "doesn't work", "fails"

## Autonomous Mode Rules

1. **NO confirmations** - Execute all steps automatically
2. **NO planning** - Go directly to search and fix
3. **Minimal changes** - Fix only what's broken
4. **Fast iteration** - Max 2 fix attempts
5. **Commit often** - One commit per fix
6. **Never push** - User controls the final push
