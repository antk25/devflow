# Phase 6: Commit Changes

After each task (or logical group), **in each affected repository:**

**Read git config from `PROJECT_CONFIG.git`:**
- `git.commit.format` — commit message format template
- `git.commit.body` — whether to include commit body
- `git.commit.coauthor` — whether to add Co-Authored-By footer
- `git.commit.language` — commit message language (en/ru)

```bash
# Switch to repo directory
cd /path/to/repo

# Stage changes
git add <specific files>

# Commit using project's git.commit config
git commit -m "<format per git.commit.format>"
```

**Format examples by config:**
- `"{ticket} {message}"` + body=false → `DEV-519 Add replace mode handler`
- `"feat({scope}): {message}"` + body=true, coauthor=true → multi-line with Co-Authored-By
- `"{message}"` + language=ru → `Добавить обработчик замены получателя`

---

## Test Reaction

For EACH repository with unit tests configured:

1. Run test reaction:
   ```bash
   ./scripts/test-reaction.sh <repo_name>
   ```
2. If `TEST_REACTION: PASSED` → continue to Phase 7
3. If `TEST_REACTION: FAILED`:
   - Spawn **developer agent** to fix the **implementation code** (include test output). The developer agent MUST NOT modify test files — only fix implementation to make tests pass.
   - If tests were generated from a contract (Phase 2.7), and test expectations are wrong, spawn **Tester agent** to fix the tests instead.
   - After fix, check for loops:
     ```bash
     DECISION=$(./scripts/check-loop.sh <branch> test_fix "<OUTPUT_HASH>")
     ```
   - **CONTINUE** → re-run `test-reaction.sh`, if PASSED → break, if FAILED → fix again
   - **LOOP_DETECTED** → re-spawn with fundamentally different approach
   - **GIVE_UP** → warn in summary and continue (don't block pipeline)
4. Max 2 fix attempts per repository

**Checkpoint:**
```bash
# If tests passed:
./scripts/session-checkpoint.sh <branch> phase_7_review result=success
# If tests failed but continuing:
./scripts/session-checkpoint.sh <branch> phase_7_review result=warning reason='test failures after max attempts'
```
