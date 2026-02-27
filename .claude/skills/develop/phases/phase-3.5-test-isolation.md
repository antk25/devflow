# Phase 3.5: Test Isolation Verification

After all implementation tasks are complete, verify that dev agents did not touch test files:

```bash
TEST_FILES_TOUCHED=$(git -C <worktree_path> diff main --name-only | grep -E '(Test\.|\.test\.|\.spec\.|/tests/|/test/)' || true)
```

**If `TEST_FILES_TOUCHED` is not empty:**
1. Revert only the test file changes:
   ```bash
   git -C <worktree_path> checkout main -- <each test file>
   ```
2. Record a lesson learned: "Developer agent modified test files despite isolation rules"
3. Log warning: "Test isolation violation detected — reverted changes to: <files>"

**If empty:** Continue to Phase 4.

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_4_validate
```
