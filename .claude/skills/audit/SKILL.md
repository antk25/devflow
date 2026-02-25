---
name: audit
description: Audit project documentation against codebase reality
user_invocable: true
arguments:
  - name: scope
    description: What to audit (all, patterns, lessons, or specific file/directory)
    required: false
---

# /audit - Documentation Audit Skill

This skill compares project documentation (patterns, conventions, CLAUDE.md) against the actual codebase to find drift, stale rules, and undocumented patterns.

## Usage

```
/audit                    # Full audit
/audit patterns           # Audit patterns.md only
/audit lessons            # Audit lessons-learned.md for promotion candidates
/audit src/services/      # Audit specific directory against documented patterns
/audit --fix              # Audit and auto-fix documentation
```

## What It Does

1. **Gathers documentation** (patterns.md, CLAUDE.md, CONTRIBUTING.md, lessons-learned.md)
2. **Scans codebase** (Architecture Guardian compares docs vs reality)
3. **Generates report** (confirmed, drift, stale, undocumented patterns)
4. **Optionally auto-fixes** (with `--fix` flag)

**NO code modifications** - only documentation changes (with `--fix`).

## Instructions

You are the documentation audit orchestrator. Compare documented conventions against codebase reality.

### Phase 0: Read Project Configuration

```
1. Read `.claude/data/projects.json` - get active project config
2. Read project's `.claude/CLAUDE.md` - documented conventions
3. Read `.claude/patterns.md` - if exists
4. Read `CONTRIBUTING.md` - if exists
5. Read `<project_path>/.claude/data/lessons-learned.md` - if exists
```

### Phase 1: Gather Documentation

Collect all documented rules:
- **Patterns:** directory structure, naming conventions, import order, component structure, forbidden patterns, required patterns
- **Conventions:** commit format, branch naming, code style
- **Lessons:** past mistakes and correct patterns

Parse each documented rule into a checklist of verifiable claims.

### Phase 2: Scan Codebase

Spawn Architecture Guardian to compare docs vs reality:

```
Task(
  description: "Audit: docs vs codebase",
  prompt: "Compare these documented patterns against the actual codebase:

  Repository: <repo_path>

  ## Documented Patterns
  <parsed patterns from Phase 1>

  ## Instructions
  For EACH documented pattern:
  1. Search the codebase for examples that follow it
  2. Search for examples that violate it
  3. Search for undocumented patterns (common code patterns not in docs)

  Return a structured report:
  {
    'confirmed': [patterns that match reality],
    'drift': [patterns where code has diverged from docs],
    'stale': [documented patterns with zero matches in code],
    'undocumented': [common code patterns not captured in docs]
  }

  For each finding, include specific file:line evidence.",
  subagent_type: "Architecture Guardian"
)
```

### Phase 3: Analyze Lessons

If `lessons-learned.md` exists, check for promotion candidates:

```
For each lesson:
  - Has this mistake occurred 2+ times? → Promote to patterns.md rule
  - Is the lesson no longer relevant (code deleted)? → Mark as stale
  - Is the lesson already captured in patterns.md? → Mark as redundant
```

### Phase 4: Generate Report

```markdown
## 📋 Documentation Audit Report

### Scope
[What was audited]

### ✅ Confirmed Patterns (X/Y)
Patterns in docs that match codebase reality:
- [pattern] — X files follow this

### ⚠️ Drift Detected (N items)
Patterns where code has diverged from documentation:
| Pattern | Documented | Actual | Files |
|---------|-----------|--------|-------|
| Import order | types last | types mixed | src/components/*.tsx |

### 🗑️ Stale Documentation (N items)
Documented patterns with no matches in code:
- [pattern] — zero files match, last relevant commit: [hash]

### 📝 Undocumented Patterns (N items)
Common code patterns not captured in documentation:
- [pattern] — found in X files, consider adding to patterns.md

### 🎓 Lesson Promotion Candidates (N items)
Lessons that should become permanent patterns:
| Lesson | Occurrences | Recommendation |
|--------|-------------|----------------|
| [lesson] | 3 times | Add to patterns.md Forbidden Patterns |

### 🧹 Stale Lessons (N items)
Lessons no longer relevant:
- [lesson] — referenced code was deleted in [commit]

### Summary
- Docs accuracy: X% (confirmed / total documented)
- Action items: N drift fixes, M stale removals, K new patterns to document
```

### Phase 5: Auto-Fix (only with `--fix` flag)

If `--fix` was specified:

1. **Remove stale patterns** from patterns.md
2. **Update drifted patterns** to match current code
3. **Add undocumented patterns** to patterns.md
4. **Promote mature lessons** to patterns.md
5. **Remove stale lessons** from lessons-learned.md
6. **Commit changes:**

```bash
cd /path/to/repo
git add .claude/patterns.md .claude/data/lessons-learned.md
git commit -m "docs: sync documentation with codebase reality

Audit findings:
- Updated N drifted patterns
- Removed M stale patterns
- Added K undocumented patterns
- Promoted L lessons to patterns

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

## Autonomous Mode Rules

1. **NO code changes** - only documentation changes (with `--fix`)
2. **Evidence-based** - every finding must cite specific files
3. **Non-destructive** - without `--fix`, only generates report
4. **Accurate counts** - confirmed/drift/stale numbers must be verifiable
