# Phase 7: Code Review

**First**, load project-specific reviewer context (if available):
```bash
AGENT_FILE=$(./scripts/resolve-agent.sh "<project_path>" "Code Reviewer")
```
- If found (exit 0), read the file and store as `project_reviewer_context`
- If not found (exit 1), set `project_reviewer_context = ""`

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
  prompt: "<if project_reviewer_context is not empty, prepend:>

  ## Project-Specific Review Context (PRIORITY)
  <project_reviewer_context>

  ---

  <endif>

  Review code changes in:

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

## Step 2c: ChatGPT Code Review (always runs, skip with `--no-chatgpt`)

**Run IN PARALLEL with Step 2a and Step 2b** using the MCP tool:

```
mcp__chatgpt-review__gpt_code_review(
  diff: "<git diff main...HEAD from each affected repo>",
  context: "<combine pattern_context + rag_context + feature_contract>

  IMPORTANT: The 'Project Patterns' section below was verified against the actual codebase.
  Do NOT flag code as an issue if it follows these established patterns.
  Only flag deviations from patterns, genuine bugs, or security/performance issues.

  <pattern_context>"
)
```

**IMPORTANT:** Launch Step 2a (Task), Step 2b (MCP call), and Step 2c (MCP call) in the SAME message to run all three in parallel. Collect all results before proceeding to Step 3.

**Key principle:** Reviewers receive ONLY the diff + spec/contract. They do NOT receive the developer agent's prompt or implementation instructions.

**If Qwen or ChatGPT MCP tool is unavailable** (server not running, tool not found), log a warning and continue with available reviewers. Do not fail the pipeline.

## Step 3: Merge Review Findings (Preliminary)

Collect all reviews into a preliminary findings list:

1. **Deduplicate:** If multiple reviewers flag the same issue (same file + same problem), keep the most detailed description and tag with all sources (e.g., `[Claude + Qwen + ChatGPT]`, `[Claude + ChatGPT]`, `[Qwen + ChatGPT]`)
2. **Unique findings:** Issues found by only one reviewer are tagged `[Claude]`, `[Qwen]`, or `[ChatGPT]`
3. **Severity:** If reviewers disagree on severity, use the highest severity

This preliminary list is the input for the Debate Protocol (if enabled) or the final output (if `--no-debate`).

## Step 4: Debate Protocol (default ON, skip with `--no-debate`)

If `agent_config.review_debate` is false OR `--no-debate` flag is passed, skip to Step 7 (Final Verdict) and use the preliminary merged findings as-is with standard confidence scoring.

### Step 4a: Challenge Round

Each reviewer receives ALL findings from the other two reviewers and must respond to each:

**Claude Reviewer challenge:**
```
Task(
  description: "Challenge: review debate",
  prompt: "You are participating in a review debate. You already reviewed this code.

## Your Original Findings
<Claude's findings from Step 2a>

## Other Reviewers' Findings (respond to EACH)
<Qwen + ChatGPT findings, tagged by source>

For EACH finding from other reviewers, respond with exactly one of:

- **AGREE** — You confirm this is a real issue. Optionally add supporting evidence.
- **CHALLENGE** — You disagree. Explain WHY this is not a real issue (e.g., it follows project patterns, the code is actually correct, the context was misread).
- **ESCALATE** — The issue is MORE serious than described. Explain why.

Format your response as:

### Finding: [file:line] [original title]
**Verdict:** AGREE | CHALLENGE | ESCALATE
**Reasoning:** [1-2 sentences]

Do NOT re-state your original findings. Only respond to others' findings.",
  subagent_type: "Code Reviewer"
)
```

**Qwen challenge** (in parallel with Claude):
```
mcp__qwen-review__qwen_code_review(
  diff: "<original diff>",
  context: "DEBATE MODE: You already reviewed this code. Now respond to other reviewers' findings.

## Your Original Findings
<Qwen's findings from Step 2b>

## Other Reviewers' Findings (respond to EACH)
<Claude + ChatGPT findings, tagged by source>

For EACH finding, respond: AGREE (confirm), CHALLENGE (disagree + why), or ESCALATE (more serious + why).
Format: ### Finding: [file:line] [title] → Verdict: AGREE|CHALLENGE|ESCALATE → Reasoning: [1-2 sentences]"
)
```

**ChatGPT challenge** (in parallel):
```
mcp__chatgpt-review__gpt_code_review(
  diff: "<original diff>",
  context: "DEBATE MODE: You already reviewed this code. Now respond to other reviewers' findings.

## Your Original Findings
<ChatGPT's findings from Step 2c>

## Other Reviewers' Findings (respond to EACH)
<Claude + Qwen findings, tagged by source>

For EACH finding, respond: AGREE (confirm), CHALLENGE (disagree + why), or ESCALATE (more serious + why).
Format: ### Finding: [file:line] [title] → Verdict: AGREE|CHALLENGE|ESCALATE → Reasoning: [1-2 sentences]"
)
```

**Launch all three challenge calls in the SAME message** (parallel).

### Step 5: Defense Round

For each finding that received at least one CHALLENGE, the original reviewer gets a chance to defend or withdraw.

**Claude defense** (for Claude's findings that were challenged):
```
Task(
  description: "Defend: review debate",
  prompt: "Your review findings were challenged by other reviewers. For each challenged finding, respond:

## Challenged Findings

<For each of Claude's findings that received CHALLENGE from Qwen or ChatGPT:>

### [file:line] [title]
**Your original finding:** <summary>
**Challenge from [Qwen/ChatGPT]:** <their reasoning>

**Your response** — choose one:
- **DEFEND** — Your finding IS valid. Provide additional evidence (specific code references, documentation, security standards).
- **WITHDRAW** — You accept the challenge. The finding is not a real issue.

Do NOT defend findings that were not challenged.",
  subagent_type: "Code Reviewer"
)
```

**Qwen defense** (for Qwen's challenged findings):
```
mcp__qwen-review__qwen_code_review(
  diff: "<original diff>",
  context: "DEFENSE ROUND: Your findings were challenged. For each challenge, respond with DEFEND (provide evidence) or WITHDRAW (accept the challenge).

<list of Qwen's challenged findings with challenger's reasoning>"
)
```

**ChatGPT defense** (for ChatGPT's challenged findings):
```
mcp__chatgpt-review__gpt_code_review(
  diff: "<original diff>",
  context: "DEFENSE ROUND: Your findings were challenged. For each challenge, respond with DEFEND (provide evidence) or WITHDRAW (accept the challenge).

<list of ChatGPT's challenged findings with challenger's reasoning>"
)
```

**Launch all three defense calls in the SAME message** (parallel).

**Optimization:** If no findings were challenged (all AGREE/ESCALATE), skip Step 5 entirely.

### Step 6: Parse Debate Results

For each finding, determine final status:

| Scenario | Result |
|----------|--------|
| All AGREE (or AGREE + ESCALATE) | Keep finding, highest confidence |
| CHALLENGE + DEFEND with evidence | Keep finding, note the debate |
| CHALLENGE + WITHDRAW | **Remove finding** from final report |
| CHALLENGE + DEFEND without new evidence | Keep but lower confidence |
| ESCALATE by any reviewer | Increase severity one level |

## Step 7: Final Verdict

Compile the final review report:

1. **Surviving findings** — findings that passed the debate (not withdrawn)
2. **Confidence scoring** (updated from debate):
   - Unanimous AGREE → highest confidence
   - AGREE + DEFEND (won challenge) → high confidence
   - Disputed (CHALLENGE + weak DEFEND) → medium confidence, flag for human review
3. **Debate log** — for each finding, include a one-line debate summary:
   - `[Claude + Qwen + ChatGPT: unanimous]`
   - `[Claude: challenged by Qwen, defended with evidence]`
   - `[Qwen: challenged by Claude, withdrawn]`

**Route by severity:**
- **Critical/High findings** → passed to Phase 8 (fix critical issues)
- **Minor/Info findings** → parse `json:review_improvement_notes` blocks, merge, deduplicate, append to `phase7_observations`
- **Withdrawn findings** → excluded entirely

The final review report is what gets passed to Phase 8 (fix critical issues)
