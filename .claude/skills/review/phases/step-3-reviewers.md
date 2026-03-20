# Step 4: Spawn Reviewers

**CRITICAL: Launch ALL THREE reviewers in ONE message (parallel). Do NOT review the code yourself.**

Skip Qwen with `--no-qwen`, skip ChatGPT with `--no-chatgpt`.

## 4a: Claude Code Reviewer (always runs)

```
Task(
  description: "Review: <scope>",
  prompt: "You are the Code Reviewer agent. Review the following code changes:

## Review Type
<Local | GitHub PR | GitLab MR | Branch>

## Author
<author name if external>

## Change Summary
<what the change does>

## Code to Review
<review_diff>

## Context
<relevant surrounding code, existing patterns>

<if pattern_context exists:>
## Project Patterns (verified from codebase — MUST RESPECT)
<pattern_context>

CRITICAL: Do NOT flag code that follows established project patterns. Only flag:
- Deviations FROM these patterns (inconsistency)
- Genuine bugs that patterns cannot excuse
- Security vulnerabilities not covered by project-level config
- Performance issues regardless of patterns
<endif>

<if rag_context exists and pattern_context is empty:>
## Project Conventions (from Knowledge Base)
<rag_context>
<endif>

<if feature_contract exists:>
## Feature Contract (verify compliance)
<feature_contract>
Verify: API endpoints, status codes, field names, DTO types, events, DB schema match contract.
<endif>

## Focus Areas
- Security vulnerabilities
- Performance issues
- Code quality
- Test coverage
- Adherence to project patterns

Provide:
1. Critical issues (must fix before merge)
2. Warnings (should fix)
3. Suggestions (nice to have)
4. Questions for the author
5. Positive observations",
  subagent_type: "Code Reviewer",
  model: "sonnet"
)
```

## 4b: Qwen Code Review (skip with `--no-qwen`)

```
mcp__qwen-review__qwen_code_review(
  diff: "<review_diff>",
  context: "<pattern_context + rag_context + focus areas + feature contract>

IMPORTANT: The 'Project Patterns' section below was verified against the actual codebase.
Do NOT flag code as an issue if it follows these established patterns.
Only flag deviations from patterns, genuine bugs, or security/performance issues.

<pattern_context>"
)
```

## 4c: ChatGPT Code Review (skip with `--no-chatgpt`)

```
mcp__chatgpt-review__gpt_code_review(
  diff: "<review_diff>",
  context: "<pattern_context + rag_context + focus areas + feature contract>

IMPORTANT: The 'Project Patterns' section below was verified against the actual codebase.
Do NOT flag code as an issue if it follows these established patterns.
Only flag deviations from patterns, genuine bugs, or security/performance issues.

<pattern_context>"
)
```

**If Qwen or ChatGPT MCP tool is unavailable**, log a warning and continue with available reviewers.

**Collect ALL results before proceeding to Step 5 (debate).**
