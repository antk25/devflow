---
name: explore
description: Explore a feature idea - research codebase and propose solution approaches
user_invocable: true
arguments:
  - name: feature
    description: Feature idea, requirement, or problem to explore (can be vague)
    required: true
---

# /explore - Feature Exploration Skill

This skill researches the codebase, analyzes architecture, and proposes 2-3 solution approaches with trade-offs — **without making any code changes**.

**Position in workflow:** `/explore` -> user picks approach -> `/develop` or `/plan`

## Usage

```
/explore We need analytics for credit settlements
/explore Add real-time notifications to the app
/explore How should we implement multi-tenancy?
/explore User activity tracking and reporting
```

## What It Does

1. **Parses the feature idea** (extracts keywords, domain areas)
2. **Researches codebase** (finds related code, patterns, entities)
3. **Analyzes architecture** (integration points, constraints, feasibility)
4. **Proposes 2-3 approaches** (with pros, cons, effort, risk)
5. **Recommends best approach** (with reasoning)
6. **Generates actionable report** (feeds into `/develop` or `/plan`)

**NO changes made** — pure research and analysis.

## Instructions

You are the exploration orchestrator. Research the codebase and propose solution approaches without modifying any code.

### Phase 1: Understand the Request

Parse the feature description to identify:
- **Core intent** — what the user actually wants to achieve
- **Domain areas** — which parts of the system are likely involved
- **Keywords** — entities, services, concepts mentioned or implied
- **Ambiguities** — what's unclear or needs assumptions

Read project configuration:
```
1. Read `.claude/data/projects.json` - get active project config
2. Read project's `.claude/CLAUDE.md` - conventions and architecture
3. Read `.claude/patterns.md` - if exists
```

**Query RAG** for architecture context:
```
mcp__local-rag__query_documents(query: "<project_name> <feature_keywords> architecture design patterns implementation", limit: 10)
```
- Filter results: only include chunks with score < 0.50 (moderate — broad context for discovery)
- Format as `rag_context` (max ~2000 chars)
- If no relevant results or RAG unavailable, skip silently

### Phase 2: Research Codebase

Spawn Explore agent to find related code and patterns:

```
Task(
  description: "Research: <feature>",
  prompt: "Research the codebase for this feature idea:

## Feature
<feature description>

<if rag_context is not empty, append:>

## Architecture Context (from Knowledge Base)
<rag_context>

Use this to understand existing architecture and locate relevant code.

## Instructions
1. Find related entities, models, services, and components
2. Identify existing patterns that could be reused or extended
3. Map affected bounded contexts and modules
4. Check for similar implementations already in place
5. Find integration points (APIs, events, queues, shared state)
6. Note any constraints (database schema, external APIs, config)

Return:
- List of relevant files with brief descriptions
- Existing patterns found (with file:line references)
- Domain model overview (entities and relationships involved)
- Similar implementations found (if any)
- Integration points and constraints
- Any technical debt or limitations in related code",
  subagent_type: "Explore",
  model: "sonnet"
)
```

### Phase 3: Analyze Architecture

Spawn Architect agent to analyze how the feature fits:

```
Task(
  description: "Analyze: <feature>",
  prompt: "Analyze how this feature fits into the existing architecture:

## Feature
<feature description>

## Codebase Research Findings
<output from Phase 2>

<if rag_context is not empty, append:>

## Architecture Context (from Knowledge Base)
<rag_context>

## Instructions
1. Analyze how the feature integrates with existing architecture
2. Identify domain boundaries — does this cross bounded contexts?
3. Evaluate data model impact (new entities, schema changes)
4. Consider API surface changes (new endpoints, modified contracts)
5. Assess dependencies — what existing code must be touched?
6. Evaluate technical feasibility and constraints
7. Identify risks (data migration, backwards compatibility, performance)

Return:
- Architecture fit assessment
- Domain boundary analysis
- Data model impact
- API/interface changes needed
- Dependencies and coupling analysis
- Feasibility assessment
- Key risks and constraints
- 2-3 distinct solution approaches with trade-offs",
  subagent_type: "Architect",
  model: "sonnet"
)
```

### Phase 4: Propose Solutions

Based on research and analysis, formulate 2-3 distinct approaches. Each approach must include:

```markdown
#### Approach N: <descriptive name>

**Description**: What this approach does and how it works.

**Key Design Decisions**:
- [decision 1]
- [decision 2]

**Affected Components**:
- `path/to/file.ts` — [what changes]
- `path/to/other.ts` — [what changes]
- New: `path/to/new.ts` — [what it does]

**Pros**:
- [advantage 1]
- [advantage 2]

**Cons**:
- [disadvantage 1]
- [disadvantage 2]

**Effort**: Low | Medium | High
**Risk**: Low | Medium | High
**Architecture Impact**: Minimal | Moderate | Significant
```

**Guidelines for approaches:**
- At least 2 approaches, at most 3
- Approaches should be genuinely different (not minor variations)
- One can be a "quick and simple" option
- One can be a "proper/scalable" option
- Consider: simplest solution, best long-term solution, and compromise
- Be specific about files and components — not abstract hand-waving

### Phase 5: Recommend

Select the recommended approach with clear reasoning:

```markdown
### Recommendation

**Approach N** is recommended because:
- [reason 1 — why it's the best fit for this project]
- [reason 2 — why the trade-offs are acceptable]
- [reason 3 — why alternatives are less suitable]

**When to choose differently:**
- Choose Approach X if [condition]
- Choose Approach Y if [condition]
```

### Phase 6: Generate Report

Output the complete exploration report:

```markdown
## Exploration Report: <feature>

### Problem Understanding

**Feature**: <one-line summary of what the user wants>

**Interpretation**: <your understanding of the intent, including assumptions made>

**Domain Areas**: <list of system areas involved>

---

### Relevant Existing Code

| File/Module | Purpose | Relevance |
|-------------|---------|-----------|
| `src/path/file.ts` | [what it does] | [why it matters] |
| `src/path/other.ts` | [what it does] | [why it matters] |

**Existing Patterns**:
- [pattern 1 — e.g., "Event-driven updates via EventBus in `src/events/`"]
- [pattern 2]

**Similar Implementations**:
- [if any existing feature is similar, describe it]

---

### Solution Approaches

#### Approach 1: <name> (recommended)

**Description**: ...

**Key Design Decisions**: ...

**Affected Components**: ...

**Pros**: ...
**Cons**: ...

| Metric | Rating |
|--------|--------|
| Effort | Low/Medium/High |
| Risk | Low/Medium/High |
| Architecture Impact | Minimal/Moderate/Significant |

---

#### Approach 2: <name>

[same structure]

---

#### Approach 3: <name> (optional)

[same structure, only if meaningfully different from 1 & 2]

---

### Comparison

| Criteria | Approach 1 | Approach 2 | Approach 3 |
|----------|-----------|-----------|-----------|
| Effort | ... | ... | ... |
| Risk | ... | ... | ... |
| Scalability | ... | ... | ... |
| Complexity | ... | ... | ... |
| Architecture Impact | ... | ... | ... |

---

### Recommendation

[which approach and why]

[when to choose differently]

---

### Next Steps

Ready to proceed? Use one of these commands:

**If using recommended approach:**
```
/develop <concrete description based on recommended approach>
```

**If using alternative approach:**
```
/develop <concrete description based on chosen approach>
```

**If more planning is needed:**
```
/plan <concrete description with chosen approach specified>
```

**If more investigation is needed:**
```
/investigate <specific technical question to answer first>
```
```

## When to Use

**Use /explore when:**
- Feature idea is vague or high-level
- Multiple implementation strategies are possible
- You want to understand impact before committing
- Architecture decisions need to be made
- You're unfamiliar with the relevant parts of the codebase

**Use /develop instead when:**
- Requirements are clear and specific
- Implementation approach is obvious
- You know exactly what needs to be built

**Use /investigate instead when:**
- You're debugging an existing issue
- You need root cause analysis
- The problem is a bug, not a new feature

## Integration with Other Commands

```bash
# Typical flow
/explore We need user analytics          # Research and propose
# ... review report, pick approach ...
/develop Add analytics using event-based approach  # Implement chosen approach

# If feature is complex
/explore Add multi-tenancy support       # Research
/plan Implement multi-tenancy with schema-per-tenant  # Detailed planning
/implement 1                             # Step-by-step implementation
```
