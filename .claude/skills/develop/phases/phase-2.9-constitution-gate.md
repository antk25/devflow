# Phase 2.9: Pre-Implementation Constitution Gate

**Skip if:** `<project_path>/.claude/constitution.md` does not exist.

This phase validates the plan against the project's constitution BEFORE any code is written.
It catches architectural violations early — when fixing them costs nothing.

## Step 1: Load Constitution

```bash
CONSTITUTION_PATH="<project_path>/.claude/constitution.md"
```

Read the file. Extract all Articles (sections starting with `### Article`).

## Step 2: Validate Plan Against Constitution

Spawn Architecture Guardian in **plan review mode**:

```
Task(
  description: "Constitution gate: validate plan",
  prompt: "<if project_guardian_context is not empty, prepend:>

  ## Project-Specific Validation Rules (PRIORITY)
  <project_guardian_context>

  ---

  <endif>

  ## Mode: PRE-IMPLEMENTATION GATE

  You are reviewing a PLAN, not code. Your job is to catch constitutional violations
  BEFORE implementation starts.

  ## Project Constitution
  <constitution content>

  ## Plan to Validate
  <merged plan from Phase 2>

  ## Pre-Implementation Checklist
  <checklist items from constitution>

  For each planned task/file/class, check:
  1. Does it violate any Article?
  2. Does it introduce unnecessary abstractions? (Simplicity Gate)
  3. Are contracts defined before implementation tasks? (Integration-First Gate)
  4. Is every new file/class justified by a concrete requirement? (YAGNI Gate)

  Return:

  ## Constitution Gate Result

  ### Status: ✅ PASS | ❌ BLOCKED

  ### Article Compliance

  | Article | Status | Notes |
  |---------|--------|-------|
  | Article I: ... | ✅/❌ | ... |

  ### Checklist

  - [x/✗] Plan respects all Articles
  - [x/✗] Contracts defined before implementation
  - [x/✗] Every new file/class has clear justification
  - [x/✗] No speculative features

  ### Blocking Issues (if any)
  - [Specific issue + which Article + which plan task]

  ### Recommendations (non-blocking)
  - [Suggestions for plan improvement]",
  subagent_type: "Architecture Guardian"
)
```

## Step 3: Handle Result

**If PASS:** Continue to Phase 3 (or Phase 2.5/2.7 if applicable).

**If BLOCKED:**
1. Log blocking issues to conversation
2. Adjust the plan to resolve violations:
   - Remove tasks that violate Articles
   - Reorder tasks to ensure contracts-before-implementation
   - Simplify over-engineered approaches
3. Re-run the gate (max 2 attempts)
4. If still blocked after 2 attempts → pause pipeline, report to user

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_3_implement constitution_gate='pass|blocked' gate_notes='<brief>'
```
