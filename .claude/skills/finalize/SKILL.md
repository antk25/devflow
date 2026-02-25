---
name: finalize
description: Finalize work branch into clean atomic commits
user_invocable: true
arguments:
  - name: branch
    description: Work branch name to finalize (optional, uses current branch if not specified)
    required: false
---

# /finalize - Create Clean Branch from Work Branch

This skill creates a clean branch with atomic, logical commits from a messy work branch.

## Usage

```
/finalize                           # Finalize current branch
/finalize feature/auth-work         # Finalize specific branch
```

## When to Use

- After manual development with many WIP commits
- When `/develop` was interrupted before finalize phase
- To clean up any branch history before PR

## What It Does

1. **Analyzes current branch** (or specified branch)
2. **Reads project commit conventions** (from git log)
3. **Groups changes logically** (feat, refactor, test, etc.)
4. **Creates clean branch** (removes `-work` suffix or adds `-clean`)
5. **Applies atomic commits** (following project style)
6. **Verifies all changes applied** (diff should be empty)
7. **Keeps work branch as backup**

## Instructions

You are the finalize agent. Clean up the work branch into atomic commits.

### Step 0: Detect Worktree

Check if the current directory is inside a worktree:

```bash
# Check if we're in a worktree
WORKTREE_DIR=$(git rev-parse --show-toplevel 2>/dev/null)
GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)

# If git-common-dir differs from .git, we're in a worktree
if [ "$GIT_COMMON_DIR" != ".git" ] && [ "$GIT_COMMON_DIR" != "$(git rev-parse --git-dir)" ]; then
    # We're in a worktree — find the main repo root
    MAIN_REPO_ROOT=$(dirname "$(dirname "$GIT_COMMON_DIR")")
    echo "Detected worktree. Main repo: $MAIN_REPO_ROOT"
    # Use MAIN_REPO_ROOT for creating the clean branch
fi
```

If in a worktree, the final clean branch should be created from the main repo (not the worktree), since the main workspace is already on `main`.

### Step 1: Identify Branches

```bash
# Get current branch
git branch --show-current

# If branch has -work suffix, final branch removes it
# feature/auth-work → feature/auth

# If no -work suffix, add -clean for final
# feature/auth → feature/auth-clean
```

### Step 2: Analyze Project Commit Style

```bash
# Read recent commits to understand project conventions
git log --oneline -30

# Look for patterns:
# - Conventional commits: feat(scope): description
# - Simple: Add/Fix/Update description
# - Ticket-based: [PROJ-123] description
# - Other project-specific formats
```

**Store the detected format for use in Step 5.**

### Step 3: Analyze Changes

```bash
# Get base branch (usually main or master)
git log --oneline main..HEAD  # Work branch commits
git diff main...HEAD --stat   # Changed files summary
git diff main...HEAD          # Full diff
```

### Step 4: Group Changes Logically

Analyze the diff and categorize:

| Category | Typical Files | Commit Type |
|----------|---------------|-------------|
| New features | models, controllers, components | `feat:` |
| Bug fixes | any file with fix | `fix:` |
| Refactoring | restructured code, renames | `refactor:` |
| Tests | *.test.*, *.spec.* | `test:` |
| Documentation | *.md, comments | `docs:` |
| Config/tooling | config/*, .*rc | `chore:` |

**Rules:**
- Each commit = one logical unit
- Each commit leaves codebase working
- 2-5 commits is typical for a feature
- Match project's granularity level

### Step 5: Create Clean Branch

```bash
# Ensure we're on work branch
git checkout feature/xxx-work

# Create clean branch from main
git checkout main
git checkout -b feature/xxx
```

### Step 6: Apply Atomic Commits

For each logical group:

```bash
# Checkout specific files from work branch
git checkout feature/xxx-work -- path/to/files

# Stage and commit with proper message
git add path/to/files
git commit -m "<format per project convention>"
```

**Example commit sequence:**
```bash
# Commit 1: Core feature
git checkout feature/auth-work -- src/models/User.php src/repositories/UserRepository.php
git add -A
git commit -m "feat(auth): add User model and repository"

# Commit 2: API endpoints
git checkout feature/auth-work -- src/controllers/AuthController.php routes/api.php
git add -A
git commit -m "feat(auth): add login and logout endpoints"

# Commit 3: Tests
git checkout feature/auth-work -- tests/Feature/AuthTest.php tests/Unit/UserTest.php
git add -A
git commit -m "test(auth): add authentication tests"
```

### Step 7: Verify

```bash
# Diff between branches should be empty (all changes applied)
git diff feature/xxx-work --stat

# If there are differences, apply remaining files
# Run tests to ensure nothing broken
```

### Step 8: Summary

```markdown
## ✅ Branch Finalized

### Branches
| Type | Name | Commits |
|------|------|---------|
| Final | `feature/xxx` | 3 atomic |
| Backup | `feature/xxx-work` | 12 WIP |

### Atomic Commits Created
1. `abc1234` - feat(auth): add User model and repository
2. `def5678` - feat(auth): add login and logout endpoints
3. `ghi9012` - test(auth): add authentication tests

### Verification
- All changes applied: ✅
- Tests passing: ✅

### Next Steps
1. Review: `git log main..feature/xxx --oneline`
2. Push: `git push -u origin feature/xxx`
3. (Optional) Delete backup: `git branch -d feature/xxx-work`
```

## Error Handling

### Merge Conflicts
If checkout causes conflicts:
1. Resolve manually or reset
2. Apply changes in smaller chunks
3. Report to user if unresolvable

### Missing Files
If some files exist only in work branch (new files):
```bash
git checkout feature/xxx-work -- path/to/new/file
```

### Tests Fail
If tests fail after applying changes:
1. Check if all files were applied
2. Check for missing dependencies
3. Report specific test failures
