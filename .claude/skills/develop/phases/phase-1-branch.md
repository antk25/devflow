# Phase 1: Create Work Branch

**For EACH repository in project.repositories:**

```bash
# Create work branch with --work suffix and worktree isolation
BRANCH_OUTPUT=$(./scripts/create-branch.sh feature <name> <repo_path> --work --worktree)
BRANCH_NAME=$(echo "$BRANCH_OUTPUT" | head -1)
WORKTREE_PATH=$(echo "$BRANCH_OUTPUT" | grep '^WORKTREE_PATH=' | cut -d= -f2-)
```

The script handles:
- Branch naming conventions (ticket-based names like DEV-488 pass through)
- Existing branch detection with actionable hints
- Worktree creation at `<repo_path>/.claude/worktrees/<branch-slug>`
- Main workspace stays on current branch (no dirty tree issues)

**Store worktree paths** in the session's `phase_data` for use in all subsequent phases:
```json
{
  "worktree_paths": {
    "backend": "/path/to/backend/.claude/worktrees/feature-auth-work",
    "frontend": "/path/to/frontend/.claude/worktrees/feature-auth-work"
  }
}
```

**If project has multiple repositories:** run the script for each repo with the same branch name.

**IMPORTANT:** From this point forward, ALL file operations and git commands must use the **worktree path** instead of the original repo path. Pass `<worktree_path>` to all agent prompts.

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_1.5_trace
```
