# Step 3: Gather Project Patterns

This step prevents false-positive review findings by grounding reviewers in the project's actual conventions. Run sub-steps A and B **in parallel**.

## Step 3a: RAG Context

Query RAG for project conventions:
```
mcp__local-rag__query_documents(query: "<project_name> code style conventions patterns", limit: 8)
```
- Only include chunks with score < 0.35
- Format as `rag_context` (max ~2000 chars)
- If RAG unavailable, skip silently

## Step 3b: Project Pattern Context (run IN PARALLEL with 3a)

### 1. Read project memories

Read `MEMORY.md` index from `~/.claude/projects/.../memory/`. Read any memory files whose names suggest conventions/patterns (e.g., `patterns_*`, `gotchas_*`, `feedback_*`, `conventions_*`). Collect as `memory_patterns` (max ~2000 chars).

### 2. Find analogous code

Analyze the changed files to determine their **types** (Provider, UseCase, Repository, React component, DTO, enum, etc.), then spawn an Explore agent:

```
Task(
  description: "Find analogous patterns",
  prompt: "Find analogous code patterns in the codebase for the following changed file types.

## Changed File Types
<list each new/modified file with its architectural role>

## Instructions
For EACH file type, find 1-2 existing files of the SAME type and extract established patterns:
1. Structural patterns (class organization, constructor style, method signatures)
2. Convention patterns (naming, directory structure, attributes/annotations)
3. Security patterns (auth handling — per-class, per-operation, or globally)
4. Dependency patterns (which libraries/tools for similar tasks)
5. Config patterns (autowiring, manual config, etc.)

Return a structured list of patterns, grouped by file type.",
  subagent_type: "Explore",
  model: "haiku"
)
```

### 3. Compile pattern_context

Merge RAG, memories, and analogous code findings into:

```markdown
## Project Patterns (verified from codebase)

### Security Model
<how auth is handled>

### <FileType> Conventions
<patterns for each file type found>

### Other Patterns
<from memories or RAG>
```

**Prepend this preamble** to pattern_context for reviewers:
> These patterns were verified against the actual codebase. Do NOT flag code as an issue if it follows an established project pattern listed below, even if it contradicts general best practices. Only flag deviations FROM these patterns, or genuine bugs/security issues that patterns cannot excuse.
