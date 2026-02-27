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

1. **Reads project config** (conventions, repositories, testing setup)
2. **Analyzes project commit style** (git log to match conventions)
3. **Creates work branch** (`feature/xxx-work` for iterations)
4. **Plans the feature** (PM agent)
5. **Implements each task** (Developer agents)
6. **Validates architecture** (Architecture Guardian)
7. **Fixes violations** (if any)
8. **Runs E2E tests** (curl for API, Playwright for frontend)
9. **Commits changes** (work-in-progress, any format)
10. **Reviews code** (Reviewer agent)
11. **Fixes review issues** (if critical)
12. **FINALIZE: Creates clean branch** (`feature/xxx` with atomic commits)
13. **Final summary** (both branches listed)

You control only the final `git push`.

## Branch Strategy

The workflow uses **two branches** to keep history clean:

```
feature/xxx-work  ← All iterations, fixes, refactoring (messy history OK)
       ↓
feature/xxx       ← Clean, atomic, logical commits (final result)
```

**Work branch** (`-work` suffix):
- Created at start
- All implementation happens here
- Commits can be messy, frequent, WIP
- Kept as backup after finalization

**Final branch** (clean name):
- Created from main at the end
- Receives atomic, logical commits
- Ready for PR/review
- This is what you push

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

### Phase 1: Create Work Branch

**For EACH repository in project.repositories:**

```bash
# Create work branch with --work suffix and worktree isolation
BRANCH_OUTPUT=$(./scripts/create-branch.sh feature <name> <repo_path> --work --worktree)
BRANCH_NAME=$(echo "$BRANCH_OUTPUT" | head -1)
WORKTREE_PATH=$(echo "$BRANCH_OUTPUT" | grep '^WORKTREE_PATH=' | cut -d= -f2-)
```

The script handles:
- Branch naming conventions (ticket-based names like DEV-488 pass through)
- Existing branch detection with actionable hints
- Worktree creation at `<repo_path>/.claude/worktrees/<branch-slug>`
- Main workspace stays on current branch (no dirty tree issues)

**Store worktree paths** in the session's `phase_data` for use in all subsequent phases:
```json
{
  "worktree_paths": {
    "backend": "/path/to/backend/.claude/worktrees/feature-auth-work",
    "frontend": "/path/to/frontend/.claude/worktrees/feature-auth-work"
  }
}
```

**If project has multiple repositories:** run the script for each repo with the same branch name.

**IMPORTANT:** From this point forward, ALL file operations and git commands must use the **worktree path** instead of the original repo path. Pass `<worktree_path>` to all agent prompts.

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_1.5_trace
```

### Phase 1.5: Deep Trace (for business logic tasks)

**REQUIRED** when BUSINESS_LOGIC_KEYWORDS are detected in the task description.
**OPTIONAL** for other tasks, but recommended when modifying existing features.

This phase prevents implementation errors by tracing the FULL data/event chain before writing code.

#### When to Run Deep Trace

Run if task involves ANY of:
- Modifying existing calculations/analytics
- Adding event handlers/listeners
- Changing data that other code depends on
- Working with status/lifecycle changes
- Sync/import/export functionality
- Triggers that cascade to other systems

#### How to Perform Deep Trace

**Spawn the Tracer agent** to perform analysis in separate context:

```
Task(
  description: "Deep Trace: <feature name>",
  prompt: "Trace the business logic for: <feature description>

  Repository: <repo_path>

  Focus on:
  1. Data flow - where does the data come from? What filters apply?
  2. Event chain - what triggers what? What events are dispatched?
  3. Entity relationships - what is the correct relationship chain?
  4. Edge cases - first run, null states, already in final state?

  Look for similar existing implementations to follow as pattern.

  Return structured JSON summary only, not code.",
  subagent_type: "Tracer"
)
```

#### Tracer Agent Output

The Tracer returns a structured JSON summary (~500-1000 chars):

```json
{
  "feature": "BankAnalytics deletion for credits",

  "data_flow": {
    "chain": ["Credit", "CreditProgram", "Provider", "BankAnalytics"],
    "filters": ["status = VALIDATED", "dateOfIssue in period"],
    "key_query": "BankAnalyticsDTOFactory uses CreditFilters(statuses: [VALIDATED])"
  },

  "event_chain": {
    "triggers": ["CreditStatusChangedEvent"],
    "warnings": ["NOT dispatched when oldStatus is null (first assignment)"]
  },

  "entity_relationships": {
    "correct_chain": "Credit → CreditProgram → Provider (ONE)",
    "wrong_assumption": "Credit → SalesOutlet → Providers (MANY)"
  },

  "edge_cases": [
    "Credit created already VALIDATED - CreditStatusChangedEvent not fired"
  ],

  "implementation_guidance": [
    "Listen to CreditStatusChangedEvent when newStatus=VALIDATED",
    "ALSO handle CreditCreatedEvent - check if already VALIDATED",
    "Use credit.creditProgram.provider (ONE bank)"
  ],

  "similar_implementations": [
    "DeleteBankAnalyticsAfterECreditEventHandler.php - same pattern"
  ]
}
```

#### Using Trace Results

Store the trace results and pass to PM agent in Phase 2:

```
deep_trace_results = <output from Tracer>
```

**CRITICAL:** Do NOT proceed to Phase 2 until Deep Trace is complete for business logic tasks.

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_2_plan trace_summary='<brief summary>'
```

---

### Phase 2: Plan Feature (Dual: Claude + Qwen)

#### Step 2a: Claude PM Agent

Spawn PM agent to analyze and plan:

```
Task(
  description: "Plan: <feature>",
  prompt: "Plan implementation for: <feature description>

  Repository: <repo_path>

  <if deep_trace_results exists, append:>

  ## Deep Trace Results (MUST follow these findings)
  <deep_trace_results as JSON>

  IMPORTANT: Your plan MUST incorporate these findings:
  - Use the correct entity relationships from trace
  - Handle ALL edge cases identified
  - Follow the implementation guidance
  - Reference similar implementations as patterns

  <endif>

  <if rag_context is not empty, append:>

  ## Project Knowledge Base Context
  <rag_context>

  <endif>

  <if standardized_task exists with acceptance_criteria, append:>

  ## Acceptance Criteria (from standardized task)
  <acceptance_criteria as numbered list>

  IMPORTANT: Each plan task should map to one or more acceptance criteria.
  All criteria must be covered by the plan.

  <endif>

  Use this context to inform task breakdown, complexity estimates, and architecture decisions.",
  subagent_type: "Project Manager"
)
```

#### Step 2b: Qwen Plan (always runs, skip with `--no-qwen`)

**Run IN PARALLEL with Step 2a** using the MCP tool:

```
mcp__qwen-review__qwen_plan(
  task: "<feature description>

  Repository: <repo_path>",
  context: "<combine all available context:>

  <if deep_trace_results exists, append:>
  ## Deep Trace Results
  <deep_trace_results as JSON>
  <endif>

  <if rag_context is not empty, append:>
  ## Project Knowledge Base Context
  <rag_context>
  <endif>

  <if standardized_task exists with acceptance_criteria, append:>
  ## Acceptance Criteria
  <acceptance_criteria as numbered list>
  <endif>"
)
```

**IMPORTANT:** Launch Step 2a (Task) and Step 2b (MCP call) in the same message to run them in parallel. Both return independently. Collect both results before proceeding to Step 2c.

**If Qwen MCP tool is unavailable** (server not running, tool not found), log a warning and continue with Claude-only plan. Do not fail the pipeline.

#### Step 2c: Merge Plans

Merge both plans into a unified Dual Plan (see [Dual Plan Output Format](#dual-plan-output-format) below).

**Merge rules:**
1. **Deduplicate tasks:** If both planners propose the same task (same layer + same goal), keep the more detailed description and tag `[Claude + Qwen]`
2. **Unique tasks:** Tasks proposed by only one planner are tagged `[Claude]` or `[Qwen]`
3. **Edge cases:** Union of all edge cases from both, deduplicated, tagged by source
4. **Dependencies:** If planners disagree on task order, prefer Claude's ordering (primary planner)
5. **Complexity:** If planners disagree on complexity, note both estimates

The **merged plan** is what gets stored and used for subsequent phases. Claude is the primary planner — Qwen supplements with additional tasks and edge cases.

Store merged plan in memory, do NOT ask user to confirm plan.

**Merged plan must include:**
- Which repositories are affected
- Tasks per repository (tagged by source)
- Edge cases (tagged by source)
- **If Deep Trace was run:** Edge cases to handle in each task

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_2.5_contract plan_summary='<brief summary>'
```

### Phase 2.5: Feature Contract (C-DAD, Dual: Claude + Qwen)

Contract-Driven AI Development: generate a feature contract, save to Obsidian for user review, then use as source of truth for all agents.

#### When to Generate a Contract

**Generate contract** if ANY of these conditions are true:
- Plan contains **2+ tasks touching different layers** (API + DB, Handler + Event, Controller + Service, etc.)
- Feature is **multi-repo** (frontend + backend)
- Plan includes **new domain events** or **event handler changes**
- Plan includes **database schema changes** (new tables, new columns, migrations)

**Skip contract** if ALL of these are true:
- Single task or single-file change
- Single layer (e.g., just a service refactor, just a UI fix)
- No schema changes, no events, no API changes

When skipping, set `feature_contract = ""` and proceed to Phase 3.

#### Step 1a: Claude Architect Agent

Spawn Architect to generate the feature contract:

```
Task(
  description: "Feature Contract: <feature>",
  prompt: "Generate a feature contract for this development task.

  Feature: <feature description>
  Plan tasks: <all task summaries from Phase 2>
  Repository/ies: <repo paths>

  <if deep_trace_results exists, append:>
  Deep Trace findings: <deep_trace_results>
  <endif>

  Analyze the plan and generate a contract with ONLY the sections that apply:
  - API section: if new/modified endpoints
  - DTO section: if new commands/queries/response objects
  - Events section: if domain events are dispatched or consumed
  - Database section: if schema changes (tables, columns, indexes)
  - Component section: if frontend components (multi-repo only)

  Use the C-DAD contract template format (Markdown + YAML code blocks).
  Write content in Russian (descriptions, headers) with English code identifiers in YAML.
  Include branch name: <work_branch_name>

  Return the COMPLETE contract file content including frontmatter.",
  subagent_type: "Architect"
)
```

#### Step 1b: Qwen Contract (always runs, skip with `--no-qwen`)

**Run IN PARALLEL with Step 1a** using the MCP tool:

```
mcp__qwen-review__qwen_contract(
  task: "<feature description>",
  plan: "<all task summaries from Phase 2, joined with newlines>",
  context: "<combine all available context:>

  Repository/ies: <repo paths>
  Branch: <work_branch_name>

  <if deep_trace_results exists, append:>
  ## Deep Trace Results
  <deep_trace_results as JSON>
  <endif>

  <if rag_context is not empty, append:>
  ## Project Knowledge Base Context
  <rag_context>
  <endif>

  Generate contract in C-DAD format (Markdown + YAML code blocks).
  Write descriptions in Russian, code identifiers in English.
  Include ONLY applicable sections: API, DTO, Events, Database, Components."
)
```

**IMPORTANT:** Launch Step 1a (Task) and Step 1b (MCP call) in the same message to run them in parallel. Both return independently. Collect both results before proceeding to Step 1c.

**If Qwen MCP tool is unavailable** (server not running, tool not found), log a warning and continue with Claude-only contract. Do not fail the pipeline.

#### Step 1c: Merge Contracts

Merge both contracts into a unified Dual Contract (see [Dual Contract Output Format](#dual-contract-output-format) below).

**Merge rules:**
1. **Sections:** Union of all sections from both contracts. If both have the same section (e.g., API), merge entries within it
2. **YAML entries:** If both define the same endpoint/DTO/event/table, keep Claude's version as primary but annotate differences from Qwen as comments
3. **Extra entries:** Fields/endpoints/columns proposed by only one are tagged `# [Claude]` or `# [Qwen]` as YAML comments
4. **Descriptions:** Use Claude's Russian descriptions as primary
5. **Conflicts:** If YAML field types disagree, note both: `type: string # [Claude: string, Qwen: int] — verify`

The **merged contract** uses Claude as the base, enriched with Qwen's additions and annotated disagreements for the user to resolve during review.

Store merged result as `feature_contract`.

#### Step 2: Save Contract to Obsidian

1. Read `obsidian_vault` from `.claude/data/projects.json`
2. Build path: `<obsidian_vault>/projects/<project>/contracts/<branch>-<feature_slug>.md`
3. Create directory if needed: `mkdir -p <obsidian_vault>/projects/<project>/contracts/`
4. Write the contract file
5. Store the full path as `contract_path`

```bash
mkdir -p <obsidian_vault>/projects/<project>/contracts/
# Write contract content to file
```

#### Step 3: Pause for User Review

**IMPORTANT:** This is the only intentional pause in the autonomous pipeline.

Print to user:

```markdown
## Dual Feature Contract Generated (Claude + Qwen)

**Saved to:** `<contract_path>`
**Open in Obsidian:** `projects/<project>/contracts/<filename>`

The contract was generated by both Claude and Qwen in parallel.
- Agreed entries are unmarked
- Entries from one source are tagged `[Claude]` or `[Qwen]`
- Disagreements are annotated with both values — please resolve

Review and edit in Obsidian, then type `go` to continue.
```

Wait for user to respond (any message = continue).

#### Step 4: Re-read Contract and Update Status

1. Read the contract from `contract_path` (user may have edited it)
2. Update frontmatter `status: draft` → `status: approved` in the file
3. Store the (potentially edited) content as `feature_contract`

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_3_implement contract_path='<path>'
```

---

### Contract Gate (mandatory before Phase 3)

**CRITICAL:** Before starting Phase 3, you MUST run the contract gate script:

```bash
# Get plan summary from Phase 2 (task descriptions joined)
PLAN_SUMMARY="<all task descriptions from PM plan, joined with semicolons>"
CONTRACT_DECISION=$(./scripts/require-contract.sh <branch> "$PLAN_SUMMARY")
```

**Exit code 3 = CONTRACT_REQUIRED:**
→ You MUST execute Phase 2.5 (Feature Contract) before proceeding.
→ Do NOT skip to Phase 3.

**Exit code 0 = CONTRACT_SKIP:**
→ Contract not needed, proceed directly to Phase 3.
→ Run checkpoint: `./scripts/session-checkpoint.sh <branch> phase_3_implement`

**This gate CANNOT be bypassed.** If the script says CONTRACT_REQUIRED and you proceed without generating the contract, the session-checkpoint.sh will block the transition to phase_3_implement.

---

### Phase 2.7: Test-First from Contract

**WHEN:** Only runs if `feature_contract` is not empty (a contract was generated in Phase 2.5).
**SKIP:** If no contract was generated, proceed directly to Phase 3.

This phase generates tests from the contract BEFORE implementation, following the red-green-refactor cycle.

**Step 1: Generate Tests from Contract**

Spawn Tester agent with the contract:

```
Task(
  description: "Generate tests from contract: <feature>",
  prompt: "Generate tests based on this feature contract. The implementation does NOT exist yet — these tests should define the EXPECTED behavior.

  ## Feature Contract
  <feature_contract>

  ## Repository
  <repo_path>

  ## Instructions
  1. Read the contract sections (API, DTO, Events, Database) carefully
  2. For each contracted behavior, generate a test:
     - API endpoints → integration/functional tests (HTTP request → expected response)
     - DTOs → unit tests (construction, validation, serialization)
     - Events → unit tests (event is dispatched with correct payload)
     - Database → migration test or schema assertions
  3. Follow existing test patterns in the project (check existing test files for style)
  4. Tests MUST fail at this point (no implementation yet) — this is expected
  5. Use absolute paths starting with <repo_path>

  Return a summary of generated test files and test count.",
  subagent_type: "Tester"
)
```

**Step 2: Commit Tests**

```bash
cd <worktree_path>
git add <generated test files>
git commit -m "<format per convention>: add contract-based tests for <feature>"
```

**Step 3: Verify Tests Fail (Red Phase)**

```bash
./scripts/run-tests.sh <repo_name> unit <TestFilter>
```

- If tests **FAIL** (expected) → continue to Phase 3. This confirms tests are meaningful.
- If tests **PASS** (unexpected) → log warning: "Tests pass before implementation — tests may be too weak or testing existing behavior." Continue anyway.

**CRITICAL:** Do NOT pass test file contents to the developer agent in Phase 3. The developer receives only test results (pass/fail + error messages), enforcing test isolation.

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_3_implement test_files_generated='<count>'
```

---

### Phase 3: Implement Tasks

For each task in the plan:

**First**, check for reference implementations:
- If `<project_path>/.claude/patterns.md` exists and contains a `## Reference Implementations` section:
  - Read the relevant reference for the current task type (e.g., "Service" reference for a service task, "Controller" for a controller task)
  - Store as `reference_impl`
- Otherwise, set `reference_impl = ""`

**Then**, query RAG for task-specific context:
```
mcp__local-rag__query_documents(query: "<project_name> <task_keywords> implementation example", limit: 5)
```
Filter results with score < 0.45. Format as `task_rag_context`.

**Then**, spawn appropriate developer agent:

```
Task(
  description: "Implement: <task>",
  prompt: "Implement this task in repository: <repo_path>

  Task: <task description>

  <if task_rag_context is not empty, append:>

  ## Implementation References (from Knowledge Base)
  <task_rag_context>

  <if reference_impl is not empty, append:>

  ## Reference Implementation (follow this pattern PRECISELY)
  <reference_impl>

  <endif>

  <if lessons_context is not empty, append:>

  ## Lessons Learned (DO NOT repeat these mistakes)
  <lessons_context>

  <endif>

  <if feature_contract is not empty and task touches a contracted layer, append:>

  ## Feature Contract (MUST match exactly)
  <feature_contract>

  Your implementation MUST match this contract:
  - Field names and types in YAML blocks are the source of truth
  - API endpoints, request/response schemas as specified
  - DTO class fields must match the `dtos:` YAML block
  - Events must be dispatched by the specified class with the specified payload
  - Database columns/indexes must match the `database:` YAML block

  <endif>

  ## TEST ISOLATION RULES (MANDATORY)
  You are a DEVELOPER agent. You are PROHIBITED from:
  1. Creating, editing, or deleting ANY test files (files matching: *Test.php, *.test.ts, *.spec.ts, **/tests/**, **/test/**)
  2. Reading test files — you will receive ONLY test results (pass/fail + error messages)
  3. Modifying test config files (jest.config.*, phpunit.xml, vitest.config.*, playwright.config.*)

  Fix your IMPLEMENTATION code to make tests pass. Do NOT modify tests.

  <if feature_contract is not empty, append:>
  Contract-based tests have already been generated (Phase 2.7). You will NOT see test source code.
  After implementation, tests run automatically — you see only pass/fail results.
  <endif>

  IMPORTANT: All file operations must use absolute paths starting with <repo_path>
  IMPORTANT: All git commands must be run from <repo_path>",
  subagent_type: "<JS Developer|PHP Developer|Architect>"
)
```

**IMPORTANT for multi-repo projects:**
- Pass the exact repository path to each agent
- Agent must use absolute paths for all operations
- Agent must cd to repo for git operations

**Per-task checkpoint:** After each task completes:
```bash
./scripts/session-checkpoint.sh <branch> phase_3_implement tasks_completed='N/M'
```

**Checkpoint** (after all tasks):
```bash
./scripts/session-checkpoint.sh <branch> phase_3.5_test_isolation
```

### Phase 3.5: Test Isolation Verification

After all implementation tasks are complete, verify that dev agents did not touch test files:

```bash
TEST_FILES_TOUCHED=$(git -C <worktree_path> diff main --name-only | grep -E '(Test\.|\.test\.|\.spec\.|/tests/|/test/)' || true)
```

**If `TEST_FILES_TOUCHED` is not empty:**
1. Revert only the test file changes:
   ```bash
   git -C <worktree_path> checkout main -- <each test file>
   ```
2. Record a lesson learned: "Developer agent modified test files despite isolation rules"
3. Log warning: "Test isolation violation detected — reverted changes to: <files>"

**If empty:** Continue to Phase 4.

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_4_validate
```

### Phase 4: Architecture Validation

After each implementation, spawn Architecture Guardian:

```
Task(
  description: "Validate architecture",
  prompt: "Review the following changes for architecture compliance:

  Repository: <repo_path>
  Changed files: [list]

  Project patterns: [patterns from Phase 0]

  <if rag_context contains architecture/pattern info, append:>

  ## Documented Project Patterns (from Knowledge Base)
  <architecture-related rag_context>

  <if feature_contract is not empty, append:>

  ## Feature Contract (verify compliance)
  <feature_contract>

  Verify implementation matches ALL contract sections (API, DTO, Events, Database, Components).
  Parse YAML code blocks for exact field names and types.

  <endif>

  Return status: pass/warn/fail with specific issues.",
  subagent_type: "Architecture Guardian"
)
```

**If FAIL:** Use loop detection script to track retry attempts:

1. Spawn developer agent with fix instructions (include Guardian's failure details)
2. After fix, check for loops:
   ```bash
   HASH=$(cd <repo_path> && git diff HEAD~1 --stat | md5sum | cut -d' ' -f1)
   DECISION=$(./scripts/check-loop.sh <branch> arch_validation "$HASH")
   ```
3. Based on `DECISION`:
   - **CONTINUE** → re-run Guardian validation. If PASS → break. If FAIL → go to step 1.
   - **LOOP_DETECTED** → re-spawn developer with: `"LOOP DETECTED: Try a FUNDAMENTALLY DIFFERENT approach. Previous failures listed in stderr above."`
   - **GIVE_UP** → add warning to summary, continue to next phase (do not block pipeline)

**Record lesson on fix:** When Guardian returns `fail` and developer fixes it, append a lesson to `<project_path>/.claude/data/lessons-learned.md`:
```markdown
### [Date] Architecture: <brief title>
- **Anti-pattern:** <what was wrong>
- **Correct pattern:** <what the fix looked like>
- **Files:** <affected files>
- **Rule:** <which pattern was violated>
```

**If WARN:** Note warnings, continue.
**If PASS:** Continue to next task.

**Checkpoint:**
```bash
# If validation passed:
./scripts/session-checkpoint.sh <branch> phase_5_e2e result=success
# If validation had warnings:
./scripts/session-checkpoint.sh <branch> phase_5_e2e result=warning reason='architecture warnings noted'
# If GIVE_UP:
./scripts/session-checkpoint.sh <branch> phase_5_e2e result=warning reason='validation loop — gave up after max attempts'
```

### Phase 5: E2E Testing

**CRITICAL:** After implementation, verify the feature works end-to-end using the E2E script.

```bash
# For each affected repository:
./scripts/e2e-check.sh backend /api/affected-endpoint
./scripts/e2e-check.sh frontend
```

The script handles:
- **Server availability check** — if server is not running, outputs how to start it (docker command, manual instructions) and exits with clear error
- **E2E test execution** — runs configured E2E command from projects.json
- **Custom endpoint testing** — for API repos, pass specific endpoint as second argument
- **Troubleshooting hints** — framework-specific debug instructions on failure

**Exit codes:** 0 = passed, 2 = server not running, 3 = tests failed.

If exit code is 2 (server not running), note in summary as "⏭️ E2E skipped" and continue.
If exit code is 3, attempt to fix and re-run (max 1 retry).

**Checkpoint:**
```bash
# If E2E passed:
./scripts/session-checkpoint.sh <branch> phase_6_commit result=success
# If E2E skipped (server not running):
./scripts/session-checkpoint.sh <branch> phase_6_commit result=skipped reason='server not running'
# If E2E failed but continuing:
./scripts/session-checkpoint.sh <branch> phase_6_commit result=warning reason='e2e tests failed'
```

### Phase 6: Commit Changes

After each task (or logical group), **in each affected repository:**

```bash
# Switch to repo directory
cd /path/to/repo

# Stage changes
git add <specific files>

# Commit
git commit -m "<format per project convention>"
```

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_6.5_test_reaction
```

### Phase 6.5: Test Reaction

For EACH repository with unit tests configured:

1. Run test reaction:
   ```bash
   ./scripts/test-reaction.sh <repo_name>
   ```
2. If `TEST_REACTION: PASSED` → continue to Phase 7
3. If `TEST_REACTION: FAILED`:
   - Spawn **developer agent** to fix the **implementation code** (include test output). The developer agent MUST NOT modify test files — only fix implementation to make tests pass.
   - If tests were generated from a contract (Phase 2.7), and test expectations are wrong, spawn **Tester agent** to fix the tests instead.
   - After fix, check for loops:
     ```bash
     DECISION=$(./scripts/check-loop.sh <branch> test_fix "<OUTPUT_HASH>")
     ```
   - **CONTINUE** → re-run `test-reaction.sh`, if PASSED → break, if FAILED → fix again
   - **LOOP_DETECTED** → re-spawn with fundamentally different approach
   - **GIVE_UP** → warn in summary and continue (don't block pipeline)
4. Max 2 fix attempts per repository

**Checkpoint:**
```bash
# If tests passed:
./scripts/session-checkpoint.sh <branch> phase_7_review result=success
# If tests failed but continuing:
./scripts/session-checkpoint.sh <branch> phase_7_review result=warning reason='test failures after max attempts'
```

### Phase 7: Code Review

After all tasks complete, gather project pattern context and spawn Reviewer.

**Step 1: Gather pattern context** (same approach as `/review` Step 3b):

1. Read Serena memories about conventions/patterns (if Serena project is active)
2. Spawn Explore agent to find analogous code for changed file types
3. Compile into `pattern_context` block

```
Task(
  description: "Find analogous patterns",
  prompt: "Find analogous code patterns in the codebase for the following changed file types.

  ## Changed File Types
  <list each new/modified file with its architectural role>

  ## Instructions
  For EACH file type, find 1-2 existing files of the SAME type and extract patterns:
  1. Structural patterns (constructor style, property initialization)
  2. Convention patterns (naming, directory placement, attributes/annotations)
  3. Security patterns (per-class, per-operation, or global?)
  4. Dependency patterns (libraries, test patterns)

  Return a structured list of patterns, grouped by file type.",
  subagent_type: "Explore",
  model: "haiku"
)
```

**Step 2a: Claude Code Reviewer** (always runs):

```
Task(
  description: "Review implementation",
  prompt: "Review code changes in:

  Repository: <repo_path>
  Changed files: <list>

  Focus on: security, performance, best practices

  <if pattern_context is not empty, append:>

  ## Project Patterns (verified from codebase — MUST RESPECT)
  <pattern_context>

  CRITICAL: These patterns were verified against the actual codebase. Do NOT flag code
  as an issue if it follows an established project pattern listed above. Only flag:
  - Deviations FROM these established patterns (inconsistency)
  - Genuine bugs that patterns cannot excuse
  - Security vulnerabilities not covered by project-level security config
  - Performance issues regardless of patterns

  <endif>

  <if rag_context contains conventions/style info and pattern_context is empty, append:>

  ## Project Conventions (from Knowledge Base)
  <conventions-related rag_context>

  <endif>

  <if feature_contract is not empty, append:>

  ## Feature Contract (verify compliance)
  <feature_contract>

  Additionally verify that the implementation matches the feature contract:
  - API endpoints, status codes, field names match YAML blocks
  - DTO fields and types match
  - Events are dispatched with correct payloads
  - Database schema changes match contract

  <endif>

  <if standardized_task exists with acceptance_criteria, append:>

  ## Acceptance Criteria
  <acceptance_criteria as numbered list>

  Additionally verify that ALL acceptance criteria are met by the implementation.
  Flag any criteria that are NOT covered.

  <endif>

  Verify code follows these documented conventions.",
  subagent_type: "Code Reviewer"
)
```

**Step 2b: Qwen Code Review** (always runs, skip with `--no-qwen`):

**Run IN PARALLEL with Step 2a** using the MCP tool:

```
mcp__qwen-review__qwen_code_review(
  diff: "<git diff main...HEAD from each affected repo>",
  context: "<combine pattern_context + rag_context + feature_contract>

  IMPORTANT: The 'Project Patterns' section below was verified against the actual codebase.
  Do NOT flag code as an issue if it follows these established patterns.
  Only flag deviations from patterns, genuine bugs, or security/performance issues.

  <pattern_context>"
)
```

**IMPORTANT:** Launch Step 2a (Task) and Step 2b (MCP call) in the same message to run them in parallel. Both return independently. Collect both results before proceeding to Step 3.

**Key principle:** Reviewers receive ONLY the diff + spec/contract. They do NOT receive the developer agent's prompt or implementation instructions.

**If Qwen MCP tool is unavailable** (server not running, tool not found), log a warning and continue with Claude-only review. Do not fail the pipeline.

**Step 3: Merge Review Findings**

Merge both reviews into a unified report:

1. **Deduplicate:** If both reviewers flag the same issue (same file + same problem), keep the more detailed description and tag `[Claude + Qwen]`
2. **Unique findings:** Issues found by only one reviewer are tagged `[Claude]` or `[Qwen]`
3. **Severity:** If reviewers disagree on severity, use the higher severity
4. **Agreement boosts confidence:** Issues flagged by both reviewers should be prioritized for fixing

The merged review is what gets passed to Phase 8 (fix critical issues)
```

### Phase 8: Fix Critical Issues

If review finds critical issues, use loop detection script:

1. Spawn developer agent to fix critical issues (include review findings). **Do NOT modify test files** — fix implementation code only.
2. After fix, check for loops:
   ```bash
   HASH=$(cd <repo_path> && git diff HEAD~1 --stat | md5sum | cut -d' ' -f1)
   DECISION=$(./scripts/check-loop.sh <branch> review_fix "$HASH")
   ```
3. Based on `DECISION`:
   - **CONTINUE** → re-run validation, E2E tests, commit fixes, re-review. If PASS → break. If FAIL → go to step 1.
   - **LOOP_DETECTED** → re-spawn developer with fundamentally different approach instruction
   - **GIVE_UP** → add warning to summary, continue to finalize (do not block pipeline)

**Record lesson on fix:** When reviewer returns critical issues and developer fixes them, append a lesson to `<project_path>/.claude/data/lessons-learned.md`:
```markdown
### [Date] Review (<category>): <brief title>
- **Anti-pattern:** <what the reviewer flagged>
- **Correct pattern:** <what the fix looked like>
- **Files:** <affected files>
- **Category:** security | performance | quality
```

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_9_summary
```

### Phase 9: Stop & Summary

**IMPORTANT:** Do NOT finalize or create a clean branch. The workflow stops on the work branch so the user can review the result and decide on next steps (refactor, adjust, or finalize manually).

**Step 1: Mark session as review:** Read sessions.json, set session `status: "review"`, `updated_at` to now, write back.

**Step 2: Update Serena Memories** (if Serena project is active):

Capture knowledge gained during this development session:

1. Check `mcp__serena__list_memories()` for existing memories to update (avoid duplicates)
2. **Patterns:** If architecture validation or review revealed project patterns, write/update:
   - `mcp__serena__write_memory(memory_name: "patterns/<category>", content: "<pattern description with file references>")`
   - Categories: `architecture`, `testing`, `api`, `events`, `database`
3. **Gotchas:** If there were architecture violations, test failures, or review issues that required fixes, write:
   - `mcp__serena__write_memory(memory_name: "gotchas/<topic>", content: "<what went wrong, why, and how it was fixed>")`
4. Each memory should be < 500 characters, with references to specific files

Store the list of updated memories as `updated_memories` for the summary.

**Step 3: Auto-ADR** (conditional):

Generate an Architecture Decision Record if ANY of these conditions are met:
- A **new architectural pattern** was established (not seen in existing code before)
- A **technology choice** was made (new library, framework, approach)
- The **data flow changed** significantly (new events, new entity relationships)
- A **feature contract** was generated (Phase 2.5)

If none of these conditions are met, skip ADR generation.

```
Task(
  description: "Auto-ADR: <feature>",
  prompt: "Evaluate whether this feature warrants an Architecture Decision Record (ADR).

  Feature: <feature description>
  Changes: <git diff --stat summary>
  Review findings: <summary of review issues>
  Architecture violations: <summary of Guardian findings, if any>
  Contract: <contract existed: yes/no>

  If the answer is NO (minor change, no new patterns, no tech choices), respond with exactly:
  NO_ADR_NEEDED

  If YES, generate an ADR in this format (max 30 lines):

  # ADR-NNN: <Title>

  ## Status
  Accepted

  ## Context
  <2-3 sentences: what was the situation?>

  ## Decision
  <2-3 sentences: what was decided?>

  ## Consequences
  <2-3 bullet points: what are the implications?>

  ## References
  - <affected files or contract path>",
  subagent_type: "Architect",
  model: "haiku"
)
```

**If NOT `NO_ADR_NEEDED`:**
1. Determine next ADR number:
   ```bash
   NEXT_ADR=$(ls <project_path>/.claude/data/adrs/adr-*.md 2>/dev/null | wc -l)
   NEXT_ADR=$((NEXT_ADR + 1))
   ```
2. Create directory if needed: `mkdir -p <project_path>/.claude/data/adrs/`
3. Write ADR file: `<project_path>/.claude/data/adrs/adr-$(printf '%03d' $NEXT_ADR)-<slug>.md`
4. Store as `adr_path` for the summary

**Update contract status:** If `contract_path` exists, read the contract file from Obsidian and update frontmatter `status: approved` → `status: in_review`. This signals in Obsidian that the implementation is ready for review.

**Desktop notification:**
```bash
./scripts/notify.sh "Development Ready for Review" "<feature> — work branch ready"
```

**Prepare diff summary for user:**

```bash
# For each repository
WORKTREE_PATH=<from session worktree_paths>

# Get changes summary
git -C "$WORKTREE_PATH" diff main...HEAD --stat
git -C "$WORKTREE_PATH" log main..HEAD --oneline
```

Present results to user:

```markdown
## 🔍 Ready for Review: [Feature Name]

### Work Branch

| Repo | Work Branch | Worktree Path |
|------|-------------|---------------|
| backend | `feature/auth-work` | `/path/to/.claude/worktrees/...` |
| frontend | `feature/auth-work` | `/path/to/.claude/worktrees/...` |

### Changes Summary

**backend:** (`feature/auth-work`)
<git log main..HEAD --oneline output>

**frontend:** (`feature/auth-work`)
<git log main..HEAD --oneline output>

### Files Changed
- backend: 5 created, 2 modified
- frontend: 3 created, 1 modified

### Feature Contract
<if contract_path exists>
📋 Contract: `<contract_path>` (status: in_review)
<else>
⏭️ No contract generated (simple task)
<endif>

### Architecture Compliance
✅ All patterns validated

### E2E Testing
- Backend API: ✅ Passed
- Frontend UI: ✅ Passed

### Code Review
✅ Passed (1 warning noted)
- ⚠️ Consider adding rate limiting

### Knowledge Captured
<if updated_memories is not empty>
**Serena memories updated:**
- `patterns/<category>` — <brief description>
- `gotchas/<topic>` — <brief description>
<else>
No new memories captured.
<endif>

<if adr_path exists>
**ADR generated:** `<adr_path>`
<else>
No ADR needed.
<endif>

### Next Steps
Review the changes, then choose:
1. **Happy with the result?** → `/finalize` to create clean branch with atomic commits
2. **Need refactoring?** → `/refactor <what to improve>`
3. **Need fixes?** → `/fix <what to fix>`
4. **Review the diff:**
   - `cd /path/to/backend && git diff main`
   - `cd /path/to/frontend && git diff main`
```

### Worktrees
List active worktrees created during this session. The work branch stays active for further iteration.
To switch to worktree: `cd <worktree_path>`

## Error Handling

### Session Failure Handling

If any phase encounters an unrecoverable error:
1. Read `.claude/data/sessions.json`
2. Set session `status: "failed"`, `updated_at` to now
3. Store error details in `phase_data.<current_phase>.error`
4. Write sessions.json
5. Present error to user with suggestion: `"To resume: /develop --resume <feature>"`

If the orchestrator detects it was interrupted (session status is `running` but phases are incomplete):
1. On next invocation, the Resume Check will find this session
2. Status remains `running` — resume will pick up from `current_phase`

### Git Not Found in Directory
If working from orchestrator directory and git fails:
```bash
# Always use explicit repo path from project config
cd /path/to/actual/repo && git status
```

### E2E Tests Fail
1. Note the failure
2. Attempt to fix with developer agent
3. Re-test
4. If still failing after 2 attempts:
   - Report to user with error details
   - Continue with review (code may be correct, env issue)

### Implementation Failures
If implementation fails after 3 attempts:
1. Commit partial progress
2. Document blockers
3. Report to user with options

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

**CRITICAL:** Always pass repository path to agents:

```
Task(
  description: "Implement: user auth",
  prompt: "Repository path: /home/user/project/backend

  Implement user authentication.

  Use absolute paths starting with /home/user/project/backend for all file operations.
  Run git commands from /home/user/project/backend directory.",
  subagent_type: "PHP Developer"
)
```

## Dual Plan Output Format

When both Claude and Qwen produce plans (Phase 2), merge them into a unified report. The orchestrator reads both outputs and produces the merged plan.

**Merge rules:**
1. **Deduplicate tasks:** Same layer + same goal → keep more detailed, tag `[Claude + Qwen]`
2. **Unique tasks:** Only one planner → tag `[Claude]` or `[Qwen]`
3. **Edge cases:** Union of all, deduplicated, tagged by source
4. **Dependencies:** If disagreement, prefer Claude's ordering
5. **Complexity:** If disagreement, note both estimates

```markdown
## Dual Plan: Claude + Qwen

### Plan Sources
- **Claude** (PM Agent): ✅ Completed
- **Qwen** (Qwen Code): ✅ Completed | ⚠️ Failed (Claude-only plan below)

### Tasks

#### 1. <Task Title> [Claude + Qwen]
Both planners identified this task.
**Layer**: Domain / Application / Infrastructure / UI
**Complexity**: Medium
**Description**: ...

#### 2. <Task Title> [Claude]
Proposed by Claude only.
**Layer**: ...
**Complexity**: ...
**Description**: ...

#### 3. <Task Title> [Qwen]
Proposed by Qwen only.
**Layer**: ...
**Complexity**: ...
**Description**: ...

### Dependencies
1 → 2 → 3 (from Claude's ordering)

### Edge Cases
- [Claude + Qwen] Edge case found by both
- [Claude] Edge case from Claude only
- [Qwen] Edge case from Qwen only

### Planner Comparison

| Aspect | Claude | Qwen |
|--------|--------|------|
| Total tasks | N | M |
| Agreed tasks | X | X |
| Unique tasks | Y | Z |
| Edge cases found | A | B |
```

## Dual Contract Output Format

When both Claude and Qwen produce contracts (Phase 2.5), merge them into a unified contract. The merged contract uses Claude as the base, enriched with Qwen's additions.

**Merge rules:**
1. **Sections:** Union — if both have same section, merge entries within
2. **Same entries:** Keep Claude's version, annotate Qwen differences as YAML comments
3. **Extra entries:** Tag with `# [Claude]` or `# [Qwen]` YAML comments
4. **Type conflicts:** Note both: `type: string # [Claude: string, Qwen: int] — verify`
5. **Descriptions:** Use Claude's Russian descriptions as primary

**Frontmatter includes sources:**

```markdown
---
created: YYYY-MM-DD
project: <project_name>
type: contract
branch: <branch_name>
status: draft
sources: [claude, qwen]
tags: [контракт, <domain_tags_ru>]
---

# Контракт: <Feature Name>

## Описание

<Claude's description>

---

## API

<Claude's description, enriched with Qwen's observations>

```yaml
api:
  - method: POST
    path: /api/resource
    auth: bearer
    request:
      body:
        field_name: { type: string, required: true }  # [Claude + Qwen]
        extra_field: { type: int }  # [Qwen] — not in Claude's contract, verify if needed
    response:
      201:
        id: { type: int }
        field_name: { type: string }
      400:
        error: { type: string }
        violations: { type: "array<{field: string, message: string}>" }  # [Claude]
```

## DTO

```yaml
dtos:
  CreateResourceCommand:
    field_name: { type: string }  # [Claude + Qwen]
    status: { type: string }  # [Claude: string, Qwen: enum(active,inactive)] — verify
```
```

**Contract comparison footer (after all sections):**

```markdown
---

## Contract Sources

| Section | Claude | Qwen | Agreed |
|---------|--------|------|--------|
| API endpoints | 2 | 2 | 2 |
| DTOs | 3 | 2 | 2 |
| Events | 1 | 1 | 1 |
| DB tables | 1 | 1 | 0 |
| Conflicts to resolve | — | — | 2 |
```
