# Phase 2.7: Test-First from Contract

**WHEN:** Only runs if `feature_contract` is not empty (a contract was generated in Phase 2.5).
**SKIP:** If no contract was generated, proceed directly to Phase 3.

This phase generates tests from the contract BEFORE implementation, following the red-green-refactor cycle.

## Step 1: Generate Tests from Contract

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

## Step 2: Commit Tests

```bash
cd <worktree_path>
git add <generated test files>
git commit -m "<format per convention>: add contract-based tests for <feature>"
```

## Step 3: Verify Tests Fail (Red Phase)

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
