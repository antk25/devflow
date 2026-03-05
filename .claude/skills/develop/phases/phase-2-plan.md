# Phase 2: Plan Feature (Dual: Claude + Qwen)

## Step 2a: Claude PM Agent

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

## Step 2b: Qwen Plan (always runs, skip with `--no-qwen`)

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

## Step 2b2: ChatGPT Plan (always runs, skip with `--no-chatgpt`)

**Run IN PARALLEL with Step 2a and Step 2b** using the MCP tool:

```
mcp__chatgpt-review__gpt_plan(
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

**IMPORTANT:** Launch Step 2a (Task), Step 2b (MCP call), and Step 2b2 (MCP call) in the SAME message to run all three in parallel. Collect all results before proceeding to Step 2c.

**If Qwen or ChatGPT MCP tool is unavailable** (server not running, tool not found), log a warning and continue with available planners. Do not fail the pipeline.

## Step 2c: Merge Plans

Merge all plans (Claude, Qwen, ChatGPT) into a unified plan (see `templates/dual-plan-format.md` for the output format).

**Merge rules:**
1. **Deduplicate tasks:** If multiple planners propose the same task (same layer + same goal), keep the most detailed description and tag with all sources (e.g., `[Claude + Qwen + ChatGPT]`, `[Claude + ChatGPT]`)
2. **Unique tasks:** Tasks proposed by only one planner are tagged `[Claude]`, `[Qwen]`, or `[ChatGPT]`
3. **Edge cases:** Union of all edge cases from all planners, deduplicated, tagged by source
4. **Dependencies:** If planners disagree on task order, prefer Claude's ordering (primary planner)
5. **Complexity:** If planners disagree on complexity, note all estimates

The **merged plan** is what gets stored and used for subsequent phases. Claude is the primary planner — Qwen and ChatGPT supplement with additional tasks and edge cases.

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

See also: `templates/dual-plan-format.md` for the output format.
