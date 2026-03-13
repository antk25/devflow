# Phase 2.7: Acceptance Tests from Contract

**WHEN:** Only runs if `feature_contract` is not empty (a contract was generated in Phase 2.5).
**SKIP:** If no contract was generated, proceed directly to Phase 3.

This phase generates acceptance tests from the contract's **Acceptance Scenarios** section BEFORE implementation, following the red-green cycle. Tests define the expected behavior from the user's perspective.

## Step 1: Determine Test Types

Read the `## Acceptance Scenarios` section from `feature_contract` and classify:

- **API scenarios** (Type: API) → PHPUnit acceptance tests (`tests/Acceptance/`)
- **UI scenarios** (Type: UI) → Playwright specs (`e2e/specs/`)
- **Mixed scenarios** (Type: API+UI) → both PHPUnit + Playwright

## Step 2: Generate Backend Acceptance Tests

Spawn Tester agent for API scenarios:

```
Task(
  description: "Generate acceptance tests from contract: <feature>",
  prompt: "Generate acceptance tests based on this feature contract. The implementation does NOT exist yet — these tests define the EXPECTED behavior.

  ## Feature Contract
  <feature_contract>

  ## Repository
  <backend_repo_path>

  ## Instructions
  1. Read the `## Acceptance Scenarios` section carefully
  2. For each scenario with Type: API or API+UI, generate a PHPUnit test:
     - Place in `tests/Acceptance/<DomainName>/` directory
     - Use `@group acceptance` annotation
     - Mark each test with `$this->markTestIncomplete('Acceptance: not yet implemented')`
     - Test name = scenario name in camelCase (e.g., `testAdminExportsRegistryForMonth`)
     - Given → test setup (fixtures, DB state)
     - When → HTTP request or use case call
     - Then → assertions (status code, response structure, file content)
  3. Also generate tests from contract's technical sections (API, DTO, Events, Database):
     - API endpoints → integration tests (HTTP request → expected response)
     - DTOs → unit tests (construction, validation)
     - Events → unit tests (event dispatched with correct payload)
     - Database → migration/schema assertions
  4. Follow existing test patterns in the project (check existing test files for style)
  5. Use absolute paths starting with <backend_repo_path>

  Return a summary: { files: [<paths>], acceptance_count: N, unit_count: N }",
  subagent_type: "Tester"
)
```

## Step 3: Generate Frontend Acceptance Tests (if applicable)

**Only if** there are scenarios with Type: UI or API+UI **AND** the project has a frontend repository:

```
Task(
  description: "Generate Playwright acceptance specs: <feature>",
  prompt: "Generate Playwright acceptance specs based on this feature contract. The implementation does NOT exist yet.

  ## Feature Contract
  <feature_contract>

  ## Repository
  <frontend_repo_path>

  ## Instructions
  1. Read the `## Acceptance Scenarios` section — focus on Type: UI and API+UI scenarios
  2. For each UI scenario, generate a Playwright spec:
     - Place in `e2e/specs/<feature-slug>/` directory
     - Use `test.skip()` wrapper (will be enabled after implementation)
     - Test name = scenario name (e.g., 'Admin sees registry section and downloads file')
     - Given → navigation, login as role
     - When → clicks, form fills, selections
     - Then → visible elements, downloaded files, navigation results
  3. Follow existing Playwright patterns in the project
  4. Use absolute paths starting with <frontend_repo_path>

  Return a summary: { files: [<paths>], spec_count: N }",
  subagent_type: "Tester"
)
```

**Run Step 2 and Step 3 in parallel** if both are needed.

## Step 4: Commit Tests

```bash
cd <worktree_path>
git add <generated test files>
git commit -m "<format per convention>: add acceptance tests for <feature>"
```

If multi-repo, commit in each repo separately.

## Step 5: Verify Tests Fail (Red Phase)

```bash
# Backend
./scripts/run-tests.sh <repo_name> unit --group=acceptance

# Frontend (if applicable)
cd <frontend_repo_path> && npx playwright test e2e/specs/<feature-slug>/ --reporter=list
```

- If tests **FAIL** or are **SKIPPED/INCOMPLETE** (expected) → continue to Phase 3. This confirms tests are meaningful.
- If tests **PASS** (unexpected) → log warning: "Tests pass before implementation — tests may be too weak or testing existing behavior." Continue anyway.

**CRITICAL:** Do NOT pass test file contents to the developer agent in Phase 3. The developer receives only test results (pass/fail + error messages), enforcing test isolation.

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_3_implement test_files_generated='<count>'
```
