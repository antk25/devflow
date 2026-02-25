---
name: plan
description: Plan a feature or task with the PM agent
user_invocable: true
arguments:
  - name: task
    description: The feature or task to plan
    required: true
---

# /plan - Feature Planning Skill

This skill helps you plan a feature or task by analyzing requirements and creating a structured implementation plan.

## Usage

```
/plan <description of feature or task>
```

## Process

When this skill is invoked:

1. **Read the current project context** from CLAUDE.md and any existing task files
2. **Spawn the PM agent** to analyze the requirements
3. **Generate a structured plan** with subtasks, estimates, and dependencies

## Instructions

You are acting as the orchestrator for the planning process.

### Step 1: Gather Context

First, understand the current project by:
- Reading `.claude/CLAUDE.md` for project overview
- Checking `.claude/data/tasks.json` for existing tasks (if exists)
- Scanning the project structure to understand the codebase
- **Query RAG** for project knowledge:
  - Read `.claude/data/projects.json` to get active project name
  - `mcp__local-rag__query_documents(query: "<project_name> <task_keywords> architecture implementation", limit: 10)`
  - Filter results: only include chunks with score < 0.50 (moderate — broader context helps planning)
  - Format as `rag_context` (max ~2000 chars)
  - If no relevant results or RAG unavailable, skip silently

### Step 2: Spawn PM Agent

Use the Task tool to spawn the PM agent:

```
Task(
  description: "Plan feature: <task>",
  prompt: "Analyze the following feature request and create a detailed implementation plan:

<task description>

Project context:
<relevant context from step 1>

<if rag_context is not empty, append:>

## Project Knowledge Base Context
<rag_context>

Use this context to inform task breakdown and complexity estimates.

Please provide:
1. Requirements analysis
2. Subtask breakdown
3. Complexity estimates
4. Dependencies
5. Implementation order
6. Open questions",
  subagent_type: "general-purpose",
  model: "sonnet"
)
```

### Step 3: Store the Plan

After receiving the plan from PM agent:
1. Format the plan as structured JSON
2. Save to `.claude/data/tasks.json`
3. Present the plan to the user

## Output Format

Present the final plan as:

```markdown
## 📋 Feature Plan: [Title]

### Summary
[Brief description]

### Subtasks

| # | Task | Agent | Size | Depends On |
|---|------|-------|------|------------|
| 1 | [Task name] | js-developer | M | - |
| 2 | [Task name] | tester | S | 1 |

### Implementation Order
1. Start with [task 1] (no dependencies)
2. Then [task 2] after [task 1] completes
...

### Questions for Clarification
- [ ] Question 1?
- [ ] Question 2?

---
Ready to start? Use `/implement 1` to begin with the first task.
```

## Example

**Input:**
```
/plan Add user authentication with email/password login
```

**Output:**
```markdown
## 📋 Feature Plan: User Authentication

### Summary
Implement email/password authentication system with secure login, registration, and session management.

### Subtasks

| # | Task | Agent | Size | Depends On |
|---|------|-------|------|------------|
| 1 | Design auth architecture | architect | S | - |
| 2 | Create User model and migration | js-developer | S | 1 |
| 3 | Implement registration endpoint | js-developer | M | 2 |
| 4 | Implement login endpoint | js-developer | M | 2 |
| 5 | Add session/token management | js-developer | M | 3,4 |
| 6 | Create login/register UI | js-developer | M | 3,4 |
| 7 | Write auth tests | tester | M | 3,4,5 |
| 8 | Security review | reviewer | S | 7 |

### Implementation Order
1. Architecture design (task 1)
2. Data model (task 2)
3. Backend endpoints (tasks 3,4 in parallel)
4. Session management (task 5)
5. Frontend UI (task 6)
6. Testing (task 7)
7. Security review (task 8)

### Questions for Clarification
- [ ] Should we support OAuth (Google, GitHub)?
- [ ] What password requirements?
- [ ] Session duration preference?

---
Ready to start? Use `/implement 1` to begin with architecture design.

**Tip:** For multi-layer features (API + DB, Handler + Event), use `/develop` instead — it auto-generates a feature contract (C-DAD) before implementation.
```
