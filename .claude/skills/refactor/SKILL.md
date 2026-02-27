---
name: refactor
description: Code refactoring - analyze, refactor, validate, test
user_invocable: true
arguments:
  - name: scope
    description: What to refactor (file, directory, component, or description)
    required: true
---

# /refactor - Code Refactoring Skill

This skill provides a structured workflow for refactoring code. Focuses on improving code quality without changing behavior.

## Usage

```
/refactor src/services/auth.ts           # Refactor specific file
/refactor src/components/                # Refactor directory
/refactor Payment service                # Refactor by description
/refactor --extract UserService from AuthService  # Specific refactoring
```

## What It Does

1. **Reads project config** (patterns, conventions)
2. **Analyzes current code** (structure, issues, dependencies)
3. **Plans refactoring** (what to change, in what order)
4. **Implements refactoring** (step by step)
5. **Validates architecture** (patterns compliance)
6. **Runs tests** (ensure no behavior change)
7. **Commits changes** (following project conventions)
8. **Summary with improvements**

## Instructions

You are the refactoring orchestrator. Execute the refactoring pipeline with focus on code quality.

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
   - `.claude/patterns.md` — architecture patterns

4. **Query RAG** for project patterns (run both queries in parallel):
   - Query 1: `mcp__local-rag__query_documents(query: "<project_name> architecture patterns conventions", limit: 10)`
   - Query 2: `mcp__local-rag__query_documents(query: "<project_name> <scope_keywords> architecture pattern", limit: 8)`
   - Filter results: score < 0.35 (strict). If no results or RAG unavailable, skip silently.

5. **Load lessons learned** (if `PROJECT_CONFIG.files.has_lessons_learned` is true)

6. **Initialize session tracking:**
   - Check for `--resume` flag: if present, find matching session, restore `phase_data`, skip completed phases
   - If new session, create entry keyed by refactor branch name:
     ```json
     {
       "skill": "refactor",
       "feature": "<scope description>",
       "project": "<project_name>",
       "started_at": "<ISO8601>",
       "updated_at": "<ISO8601>",
       "status": "running",
       "current_phase": "phase_1_branch",
       "completed_phases": ["phase_0_config"],
       "phase_data": {},
       "loops": {
         "step_test_fix": { "attempt": 0, "max_attempts": 2, "diff_hashes": [], "failures": [] }
       },
       "branches": { "refactor": "<branch_name>" },
       "repos": ["<repo_names>"]
     }
     ```
   - Write sessions.json

### Phase 1: Create Refactor Branch

```bash
./scripts/create-branch.sh refactor <scope-slug> <repo_path>
```

The script handles prefix, slug conversion, dirty tree warnings, and existing branch detection.

### Phase 2: Analyze Current Code

Spawn analysis task:

```
Task(
  description: "Analyze: <scope>",
  prompt: "Analyze the following code for refactoring opportunities:

## Scope
<scope description or file paths>

## Project Patterns
<patterns from Phase 0>

<if rag_context is not empty, append:>

## Documented Project Patterns (from Knowledge Base)
<rag_context>

## Instructions
1. Map the current structure (files, classes, functions)
2. Identify code smells and issues:
   - Duplication
   - Long methods/functions
   - Large classes
   - Complex conditionals
   - Poor naming
   - Tight coupling
   - Missing abstractions
3. Check pattern compliance (including documented patterns from Knowledge Base)
4. Map dependencies (what uses this code)

Return:
- Current structure overview
- Issues found (prioritized)
- Suggested refactorings
- Dependency map (what will be affected)",
  subagent_type: "Explore",
  model: "sonnet"
)
```

### Phase 3: Plan Refactoring Steps

Based on analysis, create ordered refactoring steps:

```markdown
### Refactoring Plan

1. **Extract method** - Move validation logic from `processPayment` to `validatePayment`
2. **Rename** - `data` → `paymentDetails` for clarity
3. **Extract class** - Move payment processing to dedicated `PaymentProcessor`
4. **Remove duplication** - Consolidate error handling into `handlePaymentError`
```

**Important:** Order steps to minimize risk:
- Rename before extract (preserves references)
- Extract methods before extract classes
- Small changes before large

### Phase 4: Implement Refactoring (Step by Step)

For each refactoring step:

```
Task(
  description: "Refactor step X: <description>",
  prompt: "Perform this refactoring in repository: <repo_path>

## Step
<step description>

## Current Code
<relevant code>

## Instructions
  <if lessons_context is not empty, append:>

  ## Lessons Learned (DO NOT repeat these mistakes)
  <lessons_context>

  <endif>

## TEST ISOLATION RULES (MANDATORY)
Do NOT modify any test files (files matching: *Test.php, *.test.ts, *.spec.ts, **/tests/**, **/test/**).
If tests fail after your refactoring, undo your changes — do NOT change tests.

- Apply ONLY this refactoring step
- Preserve behavior exactly
- Update all references
- Use absolute paths starting with <repo_path>
- Do NOT fix bugs or add features (refactoring only)

## Improvement Observations (optional)
While refactoring, if you notice issues in surrounding code OUTSIDE the scope of this step, note them at the END of your response as a JSON block:
```json:improvement_observations
[{\"category\": \"tech_debt|potential_bug|performance|security|style\", \"title\": \"Brief description\", \"files\": [\"path/to/file.ext\"], \"description\": \"Details\", \"priority\": \"high|medium|low\", \"estimate\": \"30 min|1-2 hours|2-4 hours\"}]
```
Only report genuinely notable issues. If nothing stands out, omit this block entirely.",
  subagent_type: "<JS Developer|PHP Developer>"
)
```

**After each step**, parse the developer's response for the `json:improvement_observations` block. If present, append items to the `refactor_observations` list (accumulates across all steps).

After EACH step:
1. Run affected tests:
   ```bash
   ./scripts/run-tests.sh <repo_name> unit <AffectedTestFilter>
   ```
2. If tests fail, use loop detection:
   ```bash
   HASH=$(echo "<failing_test_output>" | md5sum | cut -d' ' -f1)
   DECISION=$(./scripts/check-loop.sh <branch> step_test_fix "$HASH")
   ```
   - **CONTINUE** → re-spawn developer with different approach, re-run tests
   - **LOOP_DETECTED** or **GIVE_UP** → revert this step, add warning, continue to next step
3. If tests pass → commit the step

**Per-step checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_4_refactor steps_completed='N/M'
```

This enables resume: on `--resume`, skip already-completed steps and continue from the next one.

### Phase 5: Architecture Validation

After all steps:

```
Task(
  description: "Validate refactoring",
  prompt: "Review the refactored code for architecture compliance:

Repository: <repo_path>
Changed files: [list]

Project patterns: [patterns from Phase 0]

Verify:
1. Patterns are followed
2. No new code smells introduced
3. Dependencies are cleaner
4. Code is more maintainable

Return: pass/warn/fail with specific issues.",
  subagent_type: "Architecture Guardian"
)
```

**If FAIL:** Spawn developer to fix (max 2 attempts). If same fix is attempted twice (detected via sessions.json loop tracking), give up and add warning to summary.

### Phase 6: Run Full Test Suite

```bash
./scripts/run-tests.sh <repo_name> unit
```

If tests fail:
1. Identify what broke from the script's output and hints
2. Check for loop: `./scripts/check-loop.sh <branch> step_test_fix "$HASH"`
3. If same failure as before → revert problematic refactoring step, add warning
4. If new failure → fix or revert, re-run tests
5. Max 2 iterations total — if still failing, report in summary and continue

### Phase 7: Commit Changes

Commit strategy - one commit per logical change OR one squashed commit:

**Option A: Step-by-step commits (recommended for large refactoring)**
```bash
# Already committed after each step in Phase 4
```

**Option B: Single squashed commit (for small refactoring)**
```bash
cd /path/to/repo
git add .
git commit -m "refactor(<scope>): <summary>

Changes:
- Extracted <X> from <Y>
- Renamed <A> to <B>
- Removed duplication in <C>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

### Phase 8: Summary with Improvements

**Mark session complete:** Read sessions.json, set session `status: "completed"`, `updated_at` to now, write back. If refactoring had unresolved issues, set `status: "completed"` but note warnings in `phase_data`.

```markdown
## ✅ Refactoring Complete: [Scope]

### Before → After

| Metric | Before | After |
|--------|--------|-------|
| Files | 3 | 5 |
| Lines of code | 450 | 380 |
| Cyclomatic complexity | 12 | 7 |
| Code duplication | 3 blocks | 0 |

### Changes Made

#### Extracted
- `PaymentValidator` from `PaymentService` (120 lines)
- `handlePaymentError()` from inline handlers

#### Renamed
- `data` → `paymentDetails`
- `process()` → `processPayment()`

#### Removed
- Duplicate validation in 3 places
- Unused `legacyProcess()` method

### Architecture Compliance
✅ All patterns validated

### Tests
✅ All 42 tests passing

### Commits
| Hash | Message |
|------|---------|
| `abc123` | refactor(payment): extract PaymentValidator |
| `def456` | refactor(payment): consolidate error handling |
| `ghi789` | refactor(payment): improve naming |

### Observations
<if refactor_observations list has items>
While refactoring, the following issues were noticed in surrounding code:
- **<title>** (<category>, <priority>) — <description> (`<file>`)
- ...
<else>
(omit this section entirely if no observations were collected across all steps)
<endif>

### Next Steps
```bash
# Review changes
git diff main

# Push when ready
git push -u origin refactor/payment-service
```
```

## Refactoring Types

The skill handles various refactoring patterns:

| Type | Command Example |
|------|-----------------|
| Extract method | `/refactor --extract validateUser from registerUser` |
| Extract class | `/refactor --extract UserValidator from UserService` |
| Rename | `/refactor --rename oldName to newName in src/` |
| Move | `/refactor --move utils/auth.ts to services/auth/` |
| Inline | `/refactor --inline calculateTotal into processOrder` |
| General | `/refactor src/services/payment.ts` |

## Auto-Detection

The `/develop` command will automatically route to `/refactor` if the description contains:
- "refactor", "рефактор", "рефакторинг"
- "clean up", "cleanup", "очистить"
- "restructure", "reorganize", "реструктур"
- "extract", "извлечь", "выделить"

## Autonomous Mode Rules

1. **NO confirmations** - Execute all steps automatically
2. **Behavior preservation** - Tests must pass after each step
3. **Small steps** - One refactoring at a time
4. **Commit often** - Commit after each successful step
5. **Validate patterns** - Check architecture after all changes
6. **Never push** - User controls the final push
7. **Revert on failure** - If tests break, revert that step
