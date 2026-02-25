---
name: implement
description: Implement a feature or task with the appropriate developer agent
user_invocable: true
arguments:
  - name: task
    description: Task number from plan or feature description
    required: true
---

# /implement - Implementation Skill

This skill implements features or tasks by selecting and spawning the appropriate developer agent.

## Usage

```
/implement <task number or description>
```

## Examples

```
/implement 1                    # Implement task #1 from current plan
/implement Add login button     # Implement described feature directly
/implement --agent php-developer Create user model  # Force specific agent
```

## Agent Selection Logic

The skill automatically selects the appropriate agent based on:

1. **File extensions in scope:**
   - `.ts`, `.tsx`, `.js`, `.jsx` → js-developer
   - `.php` → php-developer
   - Architecture/design tasks → architect

2. **Framework detection:**
   - `package.json` with React/Vue/Next → js-developer
   - `composer.json` with Laravel/Symfony → php-developer

3. **Task keywords:**
   - "design", "architecture", "ADR" → architect
   - "test", "spec" → tester
   - "review", "audit" → reviewer

4. **Explicit override:**
   - `--agent <agent-name>` flag

## Instructions

When this skill is invoked:

### Step 1: Parse Input

Determine if input is:
- A task number (e.g., "1", "3") → Load from `.claude/data/tasks.json`
- A description → Create ad-hoc implementation task

### Step 2: Gather Context

1. Read relevant existing code
2. Check for existing patterns in the codebase
3. Identify files that will be modified/created
4. **Query RAG** for implementation references:
   - Read `.claude/data/projects.json` to get active project name
   - `mcp__local-rag__query_documents(query: "<project_name> <task_keywords> implementation pattern example", limit: 8)`
   - Filter results: only include chunks with score < 0.45 (standard — implementation references)
   - Format as `rag_context` (max ~2000 chars)
   - If no relevant results or RAG unavailable, skip silently

### Step 3: Select Agent

Based on the logic above, determine which agent to use.

### Step 4: Spawn Agent

Use the Task tool:

```
Task(
  description: "Implement: <task summary>",
  prompt: "You are the <agent-name> agent. Implement the following task:

## Task
<task description>

## Context
<relevant code context>

<if rag_context is not empty, append:>

## Implementation References (from Knowledge Base)
<rag_context>

<if feature_contract is not empty and task touches a contracted layer, append:>

## Feature Contract (MUST match exactly)
<feature_contract>

Your implementation MUST match this contract:
- Field names and types in YAML blocks are the source of truth
- API endpoints, request/response schemas as specified
- DTO class fields must match the dtos: YAML block
- Events must be dispatched by the specified class with the specified payload
- Database columns/indexes must match the database: YAML block

<endif>

## Requirements
<acceptance criteria from plan>

## Guidelines
- Follow existing code patterns in the project
- Write clean, maintainable code
- Include appropriate error handling
- Add comments only where logic isn't self-evident

Please implement this task and show me the changes.",
  subagent_type: "general-purpose",
  model: "sonnet"
)
```

### Step 5: Report Results

After implementation:
1. Summarize changes made
2. List files created/modified
3. Suggest next steps (tests, review)

## Output Format

```markdown
## ✅ Implementation Complete: [Task]

### Agent Used
[js-developer | php-developer | architect]

### Changes Made

#### Created Files
- `path/to/new-file.ts` - [Description]

#### Modified Files
- `path/to/existing.ts` - [What changed]

### Code Highlights
[Brief explanation of key implementation decisions]

### Next Steps
- [ ] Run tests: `npm test`
- [ ] Use `/review` to check code quality
- [ ] Implement related task: `/implement 2`
```

## Example

**Input:**
```
/implement Add logout button to navigation
```

**Output:**
```markdown
## ✅ Implementation Complete: Logout Button

### Agent Used
js-developer

### Changes Made

#### Modified Files
- `src/components/Navigation.tsx` - Added logout button with handler
- `src/hooks/useAuth.ts` - Added logout function

### Code Highlights
- Used existing auth context for logout functionality
- Button styled consistently with other nav items
- Clears session storage and redirects to /login

### Next Steps
- [ ] Run tests: `npm test`
- [ ] Use `/review` to verify security
- [ ] Test manually in browser
```

## Error Handling

If implementation fails or encounters issues:

```markdown
## ⚠️ Implementation Issue: [Task]

### Problem
[Description of the issue]

### Attempted Approach
[What was tried]

### Blockers
- [Blocker 1]
- [Blocker 2]

### Suggestions
- [Possible solution 1]
- [Possible solution 2]

### Questions
- [Clarification needed]
```
