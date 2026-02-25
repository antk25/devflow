---
name: review
description: Review code changes for security, performance, and quality
user_invocable: true
arguments:
  - name: scope
    description: "Files, PR number (--pr 123), branch (--branch name), MR (--mr 45), or 'staged'"
    required: false
    default: staged
---

# /review - Code Review Skill

This skill performs comprehensive code review focusing on security, performance, and code quality. Supports local changes, PRs, MRs, and branches.

## Usage

```
/review                          # Review git staged changes
/review staged                   # Review git staged changes (explicit)
/review src/components/          # Review specific directory
/review path/to/file.ts          # Review specific file

# External code review (PRs, MRs, branches)
/review --pr 123                 # Review GitHub PR #123
/review --mr 45                  # Review GitLab MR #45
/review --branch feature/auth    # Review branch vs main
/review --branch feature/auth --base develop  # Custom base branch

# Options
/review --focus security         # Focus on security issues
/review --quick                  # Fast review, critical issues only
/review --comment                # Post review comments to PR/MR
/review --dual                   # Dual review: Claude + Qwen in parallel
/review --dual --branch feat/x   # Dual review on a branch
```

## Review Categories

### Security
- OWASP Top 10 vulnerabilities
- Input validation
- Authentication/authorization issues
- Sensitive data exposure
- Injection vulnerabilities

### Performance
- N+1 queries
- Memory leaks
- Unnecessary re-renders
- Missing indexes
- Inefficient algorithms

### Code Quality
- SOLID principles
- Error handling
- Type safety
- Code duplication
- Naming conventions

## Instructions

When this skill is invoked:

### Step 1: Determine Scope

Parse the arguments to determine review mode:

| Input | Mode | Action |
|-------|------|--------|
| (none) or `staged` | Local | `git diff --cached` |
| `path/to/file` | Local | Read file(s) |
| `--pr 123` | GitHub PR | `gh pr diff 123` |
| `--mr 45` | GitLab MR | `glab mr diff 45` |
| `--branch name` | Branch | `git diff main...branch` |

### Step 2: Gather Code and Context

#### For Staged Changes
```bash
git diff --cached
```

#### For Files/Directory
```bash
# Read files
cat <file>

# For directory
find <dir> -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.php" \) | head -20
```

#### For GitHub PR
```bash
# Get PR metadata
gh pr view 123 --json title,body,author,files,additions,deletions

# Get diff
gh pr diff 123

# Get PR comments (for context)
gh pr view 123 --json comments
```

#### For GitLab MR
```bash
# Get MR metadata
glab mr view 45

# Get diff
glab mr diff 45
```

#### For Branch
```bash
# Get branch diff against base (default: main)
git fetch origin
git diff origin/main...origin/<branch>

# Get commit list
git log origin/main...origin/<branch> --oneline
```

### Step 3: Analyze Context and Project Patterns

This step gathers two types of context: (A) general code context and (B) project-specific patterns from analogous code. Both are critical to avoid false-positive findings during review.

#### Step 3a: General Context (RAG + Explore)

**Query RAG** for project conventions:
```
mcp__local-rag__query_documents(query: "<project_name> code style conventions patterns", limit: 8)
```
- Filter results: only include chunks with score < 0.35 (strict — conventions must be highly relevant)
- Format as `rag_context` (max ~2000 chars)
- If no relevant results or RAG unavailable, skip silently

#### Step 3b: Project Pattern Context (Serena + Analogous Code)

**IMPORTANT:** This step prevents false-positive review findings by grounding reviewers in the project's actual conventions. Run this IN PARALLEL with Step 3a.

**1. Read Serena memories** (if the active project has a Serena project):
```
mcp__serena__list_memories()
```
Read memories whose names suggest conventions/patterns (e.g., `code_style_and_conventions`, `architecture_patterns`, `gotchas`, `testing_guidelines`). Collect as `serena_patterns` (max ~2000 chars).

**2. Find analogous code** in the codebase using an Explore agent:

Analyze the changed files to determine their **types** (e.g., Provider, UseCase, Repository, React component, DTO, enum, etc.), then search for existing files of the same type to extract established patterns.

```
Task(
  description: "Find analogous patterns",
  prompt: "Find analogous code patterns in the codebase for the following changed file types.

## Changed File Types
<list each new/modified file with its architectural role, e.g.:
- GetECreditApplicationsAsXLSXProvider.php → API Platform Provider
- GetECreditApplicationsAsXLSXUseCase.php → UseCase DTO
- ECreditApplicationXLSXExportColumns.php → Domain ValueObject enum
- ECreditApplicationsListActions.jsx → React component>

## Instructions
For EACH file type above, find 1-2 existing files of the SAME type in the codebase and extract the established patterns. Focus on:

1. **Structural patterns**: How are similar classes organized? Constructor style, property initialization, method signatures
2. **Convention patterns**: Naming, placement in directory structure, use of attributes/annotations
3. **Security patterns**: How is auth/security handled — per-class, per-operation, or globally? Check security.yaml if relevant
4. **Dependency patterns**: What libraries/tools are used for similar tasks (e.g., which spreadsheet library, which test patterns)
5. **Config patterns**: How are services registered? Autowiring, manual config, etc.

For each pattern found, provide:
- The analogous file path
- A brief code snippet showing the pattern
- What convention it establishes

Return a structured list of patterns, grouped by file type.",
  subagent_type: "Explore",
  model: "haiku"
)
```

**3. Compile pattern context** — merge RAG, Serena memories, and analogous code findings into a single `pattern_context` block. This will be passed to both reviewers.

Format:
```markdown
## Project Patterns (verified from codebase)

### Security Model
<e.g., "Auth is handled globally via security.yaml access_control, NOT per API Platform resource. No *Resource.php uses security attributes.">

### <FileType> Conventions
<e.g., "UseCase DTOs use uninitialized nullable public properties without = null defaults. Assert attributes are declared but not validated via ValidatorInterface — this is the established pattern.">

### <FileType> Conventions
<e.g., "XLSX export column enums are placed in Domain/*/Entities/ValueObject(s)/, not in Application layer. See CreditXLSXExportColumns, CreditSettlementXLSXExportColumns.">

### Other Patterns
<any additional patterns from Serena memories or RAG>
```

**CRITICAL INSTRUCTION FOR REVIEWERS:** Include this preamble in the pattern_context passed to reviewers:
> These patterns were verified against the actual codebase. Do NOT flag code as an issue if it follows an established project pattern listed below, even if it contradicts general best practices. Only flag deviations FROM these patterns, or genuine bugs/security issues that patterns cannot excuse.

### Step 4: Spawn Reviewer(s)

**IMPORTANT: Always run BOTH Claude Code Reviewer and Qwen Code review in parallel.**
Both reviewers run by default on every review. The `--dual` flag is kept for backwards compatibility but has no effect — dual mode is always on.

If user explicitly passes `--no-qwen`, skip Qwen and run Claude-only.

#### Step 4a: Claude Code Reviewer (always runs)

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
<diff or file contents>

## Context
<relevant surrounding code, existing patterns>

<if pattern_context is not empty, append:>

## Project Patterns (verified from codebase — MUST RESPECT)
<pattern_context>

CRITICAL: These patterns were verified against the actual codebase. Do NOT flag code
as an issue if it follows an established project pattern listed above, even if it
contradicts general best practices. Only flag:
- Deviations FROM these established patterns (inconsistency)
- Genuine bugs that patterns cannot excuse
- Security vulnerabilities not covered by project-level security config
- Performance issues regardless of patterns

<endif>

<if rag_context is not empty and pattern_context is empty, append:>

## Project Conventions (from Knowledge Base)
<rag_context>

Verify code follows these documented conventions.

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

## Focus Areas
- Security vulnerabilities
- Performance issues
- Code quality
- Test coverage
- Adherence to project patterns

Please provide a detailed review with:
1. Critical issues (must fix before merge)
2. Warnings (should fix)
3. Suggestions (nice to have)
4. Questions for the author
5. Positive observations",
  subagent_type: "Code Reviewer",
  model: "sonnet"
)
```

#### Step 4b: Qwen Code Review (always runs, skip with `--no-qwen`)

**Run IN PARALLEL with Step 4a** (always, unless `--no-qwen` is passed) using the MCP tool:

```
mcp__qwen-review__qwen_code_review(
  diff: "<diff from Step 2>",
  context: "<pattern_context + rag_context + focus areas + feature contract>

IMPORTANT: The 'Project Patterns' section below was verified against the actual codebase.
Do NOT flag code as an issue if it follows these established patterns.
Only flag deviations from patterns, genuine bugs, or security/performance issues.

<pattern_context>"
)
```

**IMPORTANT:** Launch Step 4a (Task) and Step 4b (MCP call) in the same message to run them in parallel.
Both return independently. Collect both results before proceeding to Step 5.

**If Qwen MCP tool is unavailable** (server not running, tool not found), log a warning and continue with Claude-only review. Do not fail the entire review.

### Step 5: Present Results

**Default (dual):** merge both reviews into a unified Dual Review report (see [Dual Review Output Format](#dual-review-output-format) below).
**If `--no-qwen`:** format the Claude review output only, based on the mode.

## Output Format

### For Local Reviews

```markdown
## 🔍 Code Review Results

### Summary
**Status**: ✅ Approved | ⚠️ Changes Requested | ❌ Needs Work

**Files Reviewed**: X
**Issues Found**: X critical, X warnings, X suggestions

---

### 🔴 Critical Issues

#### 1. [Issue Title]
**File**: `path/to/file.ts:42`
**Category**: Security | Performance | Quality

```typescript
// Problematic code
const data = eval(userInput);
```

**Problem**: [Description of the issue]

**Fix**:
```typescript
// Recommended fix
const data = JSON.parse(userInput);
```

---

### 🟡 Warnings

#### 1. [Warning Title]
**File**: `path/to/file.ts:100`

[Description and suggestion]

---

### 🔵 Suggestions

- **file.ts:50** - Consider using `useMemo` here for performance
- **file.ts:75** - Variable name could be more descriptive

---

### ✨ Positive Observations

- Good error handling in `handleSubmit`
- Well-structured component hierarchy
- Comprehensive type definitions

---

### Test Coverage

- [ ] Unit tests present
- [ ] Edge cases covered
- [ ] Integration tests needed

### Recommended Actions

1. Fix critical issue #1 (security)
2. Address warning about N+1 query
3. Add test for error case
```

### For External PR/MR Reviews

```markdown
## 🔍 PR Review: #123 - Add user authentication

### PR Information
**Author**: @developer-name
**Branch**: `feature/auth` → `main`
**Files Changed**: 12 (+450, -120)
**Created**: 2024-01-15

### Summary
**Verdict**: ✅ Approve | 🔄 Request Changes | 💬 Comment

This PR implements JWT authentication for the API. Overall well-structured
with a few security concerns that need addressing.

---

### 🔴 Must Fix Before Merge

#### 1. Token stored in localStorage (Security)
**File**: `src/auth/storage.ts:15`

```typescript
localStorage.setItem('token', jwt);
```

**Issue**: localStorage is vulnerable to XSS attacks.

**Suggestion**: Use httpOnly cookies or secure session storage.

---

### 🟡 Should Fix

#### 1. Missing rate limiting on login endpoint
**File**: `src/api/auth.ts:42`

The login endpoint has no rate limiting, allowing brute force attacks.

---

### 💬 Questions for Author

1. **Line 88**: Why was `bcrypt` rounds reduced from 12 to 10?
2. **Line 120**: Is there a reason for the 7-day token expiry vs the standard 1 day?

---

### ✅ Looks Good

- Clean separation of auth logic
- Good error messages (not leaking info)
- Tests cover happy path

---

### Suggested Improvements (Optional)

- Consider adding refresh token mechanism
- Add audit logging for auth events

---

### Review Actions

```bash
# To approve
gh pr review 123 --approve

# To request changes
gh pr review 123 --request-changes --body "Please fix security issues"

# To add comments only
gh pr review 123 --comment --body "See review notes"
```
```

## Quick Review Mode

For fast feedback:

```
/review --quick
```

Output:
```markdown
## Quick Review: 3 files

✅ `auth.ts` - No critical issues
⚠️ `user.ts:42` - Missing null check
🔴 `api.ts:15` - SQL injection risk

Run `/review` for detailed analysis.
```

## Focus Mode

Narrow the review scope:

```
/review --focus security src/api/
/review --pr 123 --focus performance
```

Only checks the specified category.

## Posting Comments (--comment flag)

When `--comment` is specified, post review to PR/MR:

```bash
# GitHub
gh pr review 123 --comment --body "<review markdown>"

# For specific line comments
gh api repos/{owner}/{repo}/pulls/123/comments \
  -f body="Security issue: use parameterized query" \
  -f path="src/api.ts" \
  -f line=42 \
  -f side=RIGHT
```

## Integration with Git Workflow

### Before Your Own Commit
```bash
git add .
/review              # Review staged changes
# Fix any issues
git commit -m "..."
```

### Reviewing Teammate's PR
```bash
/review --pr 123                    # Full review
/review --pr 123 --focus security   # Security-focused
/review --pr 123 --comment          # Post comments to PR
```

### Reviewing a Branch Before Merge
```bash
/review --branch feature/new-api --base develop
```

## Autonomous Mode Integration

When called by `/develop`:

```json
{
  "status": "pass" | "fail",
  "critical": [
    {
      "file": "src/auth.ts",
      "line": 42,
      "issue": "SQL injection",
      "fix": "Use parameterized query"
    }
  ],
  "warnings": [...],
  "summary": "1 critical issue, 2 warnings"
}
```

Critical issues trigger automatic fix loop.

## Dual Review Output Format

When `--dual` is used, merge both reviews into a unified report. The orchestrator (you) reads both outputs and produces the merged report.

**Merge rules:**
1. **Deduplicate:** If both reviewers flag the same issue (same file + same problem), keep the more detailed description and note `[Claude + Qwen]` agreement
2. **Unique findings:** Issues found by only one reviewer are tagged with their source: `[Claude]` or `[Qwen]`
3. **Severity:** If reviewers disagree on severity, use the higher severity
4. **Agreement boosts confidence:** Issues flagged by both reviewers should be prioritized

```markdown
## Dual Code Review: Claude + Qwen

### Review Sources
- **Claude** (Code Reviewer): ✅ Completed
- **Qwen** (Qwen Code): ✅ Completed | ⚠️ Failed (Claude-only review below)

### Summary
**Status**: ✅ Approved | ⚠️ Changes Requested | ❌ Needs Work
**Agreement**: X of Y issues found by both reviewers

---

### Critical Issues

#### 1. [Issue Title] [Claude + Qwen]
Both reviewers identified this issue, increasing confidence.
**File**: `path/to/file.ts:42`
...

#### 2. [Issue Title] [Qwen]
Found only by Qwen.
**File**: `path/to/file.ts:88`
...

---

### Warnings
(same format, tagged by source)

---

### Suggestions
(same format, tagged by source)

---

### Positive Observations
(merged from both reviewers)

---

### Reviewer Comparison

| Category | Claude | Qwen | Agreed |
|----------|--------|------|--------|
| Critical | 1 | 2 | 1 |
| Warnings | 3 | 2 | 2 |
| Suggestions | 2 | 4 | 0 |
```

**For autonomous mode** (`/develop` calling `/review --dual`), return JSON with source tags:

```json
{
  "status": "pass" | "fail",
  "mode": "dual",
  "critical": [
    {
      "file": "src/auth.ts",
      "line": 42,
      "issue": "SQL injection",
      "fix": "Use parameterized query",
      "source": ["claude", "qwen"]
    }
  ],
  "warnings": [...],
  "summary": "1 critical (agreed), 2 warnings"
}
```

## Comparison with /investigate

| Aspect | /review | /investigate |
|--------|---------|--------------|
| Purpose | Evaluate code quality | Find bug root cause |
| Input | Code changes (diff) | Problem description |
| Output | Issues to fix | Hypotheses and solutions |
| When | Before merge | When debugging |
