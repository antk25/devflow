# Phase 7: Code Review

After all tasks complete, gather project pattern context and spawn Reviewer.

## Step 1: Gather Pattern Context

Same approach as `/review` Step 3b:

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

## Step 2a: Claude Code Reviewer (always runs)

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

  Verify code follows these documented conventions.

  ## Output Format (MUST follow)

  Structure your review into TWO separate sections:

  ### Critical Findings
  Issues with severity Critical or High that MUST be fixed before merge.
  These trigger the fix loop (Phase 8). List each with: severity, file, line, description, fix suggestion.

  ### Improvement Notes
  Issues with severity Minor or Info — good to fix but NOT blocking.
  These go to improvement notes, NOT to the fix loop.
  Return as a JSON block:

  ```json:review_improvement_notes
  [
    {
      \"category\": \"tech_debt|potential_bug|performance|security|style\",
      \"title\": \"Brief description\",
      \"files\": [\"path/to/file.ext\"],
      \"description\": \"Details and recommendation\",
      \"priority\": \"high|medium|low\",
      \"estimate\": \"30 min|1-2 hours|2-4 hours\"
    }
  ]
  ```
  If no minor/info findings, return an empty array.",
  subagent_type: "Code Reviewer"
)
```

## Step 2b: Qwen Code Review (always runs, skip with `--no-qwen`)

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

## Step 3: Merge Review Findings

Merge both reviews into a unified report:

1. **Deduplicate:** If both reviewers flag the same issue (same file + same problem), keep the more detailed description and tag `[Claude + Qwen]`
2. **Unique findings:** Issues found by only one reviewer are tagged `[Claude]` or `[Qwen]`
3. **Severity:** If reviewers disagree on severity, use the higher severity
4. **Agreement boosts confidence:** Issues flagged by both reviewers should be prioritized for fixing

**Route by severity:**
- **Critical/High findings** → passed to Phase 8 (fix critical issues) as before
- **Minor/Info findings** → parse `json:review_improvement_notes` blocks from both reviewers, merge, deduplicate, and append to `phase7_observations` list. These do NOT trigger Phase 8.

The Critical/High merged review is what gets passed to Phase 8 (fix critical issues)
