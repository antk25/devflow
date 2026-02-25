# Infrastructure Reference

Details on Local RAG, autonomous mode, permissions, and troubleshooting.

## Local RAG Knowledge Base

The orchestrator uses a local RAG (mcp-local-rag) for storing and retrieving project documentation, architecture patterns, and reference materials.

**MCP Server:** `local-rag` (registered at user scope)

**Knowledge base location:** `~/projects/rag-knowledge/`

```
~/projects/rag-knowledge/
├── shared/                    # Cross-project knowledge
│   ├── patterns/              # Design patterns, SOLID, DDD
│   ├── architecture/          # Architecture approaches, ADR examples
│   └── languages/             # Language/framework references
├── my-app/                    # Project-specific docs
├── my-api/                    # Project-specific docs
└── devflow/                  # Project-specific docs
```

**Available tools:**
- `mcp__local-rag__query_documents` — semantic search across knowledge base
- `mcp__local-rag__ingest_file` — add document (PDF, DOCX, TXT, MD)
- `mcp__local-rag__ingest_data` — index HTML/text content directly
- `mcp__local-rag__list_files` — view indexed documents
- `mcp__local-rag__delete_file` — remove document from index
- `mcp__local-rag__status` — system health and chunk count

**Usage guidelines:**
- When working on a project, query RAG for relevant patterns and architecture docs
- When implementing features, check if there are reference materials in the knowledge base
- Agents (Architect, Developers) should consult RAG for project conventions and patterns
- New project documentation should be ingested into the appropriate project subdirectory

### RAG Integration in Workflows

All development workflows automatically query the RAG knowledge base for project context.

**How it works:**
1. Orchestrator reads active project name from `projects.json`
2. Queries RAG with project name + feature/issue keywords
3. Filters results by relevance using per-skill score thresholds (see table below)
4. Injects as contextual section into agent prompts (max ~2000 chars)
5. Agents use this context alongside code analysis — they don't query RAG themselves

**Query construction pattern:**
`"<project_name> <feature_keywords> <context_type>"`

Context types and score thresholds by workflow phase:

| Phase | Context Type | Score Threshold | Rationale |
|-------|-------------|-----------------|-----------|
| **Review** | `code style conventions patterns` | < 0.35 (strict) | Conventions must be highly relevant |
| **Refactoring** | `architecture pattern conventions` | < 0.35 (strict) | Patterns must be precise |
| **Development** | `architecture patterns conventions` | < 0.45 (standard) | Broad project context |
| **Implementation** | `implementation pattern example code` | < 0.45 (standard) | Reference patterns |
| **Exploration** | `architecture design patterns implementation` | < 0.50 (moderate) | Broad context for discovery |
| **Planning** | `architecture implementation design` | < 0.50 (moderate) | Broader context helps planning |
| **Investigation** | `architecture flow error handling` | < 0.55 (loose) | Cast wide net for clues |
| **Fix** | `bug fix error known issues` | < 0.55 (loose) | Find similar bugs broadly |

Lower score = more relevant. Strict thresholds reduce noise; loose thresholds increase recall.

**Fallback behavior:**
- If RAG server is unavailable — skip silently, workflow continues
- If no results pass score filter — skip injection, no empty sections
- RAG is always optional, never blocks workflow execution

**Auto-reindex (SessionStart hook):**

A `SessionStart` hook runs `.claude/hooks/rag-reindex-check.sh` at the beginning of each session. If it outputs `RAG_REINDEX_NEEDED`, you MUST process the listed changes:
- **NEW/CHANGED files**: Call `mcp__local-rag__ingest_file` for each listed file
- **DELETED files**: Call `mcp__local-rag__delete_file` for each listed file
- Process in batches of 5-10 parallel calls for efficiency
- State is tracked in `~/projects/rag-knowledge/.rag-index-state`

**Maintaining the knowledge base:**
- Ingest new docs: `mcp__local-rag__ingest_file(<path>)` (files must be in `~/projects/rag-knowledge/`)
- Copy project docs first, then ingest
- Auto-reindex hook handles change detection automatically
- Use `mcp__local-rag__list_files` to see what's indexed
- Use `mcp__local-rag__status` to check system health

---

## Autonomous Mode Details

The `/develop` skill uses a PreToolUse hook (`auto-approve.sh`) to automatically approve tool calls. This means:

- **No file edit confirmations** - agents write code directly
- **No command confirmations** - git operations run automatically
- **Architecture validation loop** - code is automatically fixed if it violates patterns
- **E2E test loop** - tests run automatically, failures auto-fixed
- **Review fix loop** - critical review issues are automatically fixed

Safety is maintained through:
- `git push` is blocked in settings.json
- All changes stay local until you push
- Full summary provided at the end for review

### Permissions Configuration

The `settings.json` pre-approves common development commands:

**Allowed (no confirmation):**
- All file operations (Read, Write, Edit, Glob, Grep)
- Git commands (except push)
- Package managers (npm, yarn, composer, etc.)
- Test runners (phpunit, jest, vitest, playwright)
- Build tools (make, docker)
- **curl** (for API testing)
- All MCP tools (serena, playwright, etc.)

**Blocked (always requires manual):**
- `git push` - you control when to push
- `gh` - GitHub CLI commands
- `ssh`, `scp`, `rsync` - remote operations

### Multi-Repository Git Operations

For projects with separate frontend/backend repos:

```bash
# Orchestrator handles git per-repo
cd /path/to/backend && git checkout -b feature/auth
cd /path/to/frontend && git checkout -b feature/auth

# Commits are per-repo
cd /path/to/backend && git commit -m "feat(auth): add login endpoint"
cd /path/to/frontend && git commit -m "feat(auth): add LoginForm"
```

**IMPORTANT:** Git commands must always be run from within the repo directory, not from the orchestrator directory.

### Troubleshooting: Still Getting Confirmations?

If you're still seeing permission prompts:

**1. Restart Claude Code session** - Settings changes require restart to take effect.

**2. Run with --dangerously-skip-permissions flag:**
```bash
claude --dangerously-skip-permissions
```
This bypasses ALL permission checks. Use with caution.

**3. Use Yolo mode (if available):**
```bash
/yolo
```
Enables full autonomous mode for the session.

**4. Check auto-approve hook:**
Ensure `.claude/hooks/auto-approve.sh` exists and is executable:
```bash
chmod +x .claude/hooks/auto-approve.sh
```

**5. Project paths outside orchestrator:**
When working from orchestrator directory on projects in other paths, permissions for those paths must be explicitly in settings.json. The `Read(**)` pattern should cover this, but if not:
- Add specific paths to `allow` list
- Or run Claude Code from the project directory itself
