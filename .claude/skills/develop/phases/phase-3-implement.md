# Phase 3: Implement Tasks

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

  ## Improvement Observations (required output)

  While implementing, note any issues you find in surrounding code that are OUTSIDE the scope of your current task:
  - Code duplication
  - Outdated patterns or deprecated API usage
  - Potential bugs in adjacent code
  - Performance optimization opportunities
  - Violations of project patterns

  At the END of your response, output a JSON block in this exact format:

  ```json:improvement_observations
  [
    {
      "category": "tech_debt|potential_bug|performance|security|style",
      "title": "Brief description",
      "files": ["path/to/file.ext"],
      "description": "Details of the issue and why it matters",
      "priority": "high|medium|low",
      "estimate": "30 min|1-2 hours|2-4 hours"
    }
  ]
  ```

  Rules:
  - ONLY report issues OUTSIDE your current task scope — do NOT report things you already fixed
  - If no observations, return an empty array: `[]`
  - Keep descriptions concise (1-2 sentences)
  - Be specific about files and locations

  IMPORTANT: All file operations must use absolute paths starting with <repo_path>
  IMPORTANT: All git commands must be run from <repo_path>",
  subagent_type: "<JS Developer|PHP Developer|Architect>"
)
```

**After each task completes**, parse the developer's response for the `json:improvement_observations` block. Extract the JSON array and append its items to the `phase3_observations` list (accumulates across all tasks).

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
