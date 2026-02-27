# Phase 8: Fix Critical Issues

If review finds critical issues, use loop detection script:

1. Spawn developer agent to fix critical issues (include review findings). **Do NOT modify test files** — fix implementation code only.
2. After fix, check for loops:
   ```bash
   HASH=$(cd <repo_path> && git diff HEAD~1 --stat | md5sum | cut -d' ' -f1)
   DECISION=$(./scripts/check-loop.sh <branch> review_fix "$HASH")
   ```
3. Based on `DECISION`:
   - **CONTINUE** → re-run validation, E2E tests, commit fixes, re-review. If PASS → break. If FAIL → go to step 1.
   - **LOOP_DETECTED** → re-spawn developer with fundamentally different approach instruction
   - **GIVE_UP** → add warning to summary, continue to finalize (do not block pipeline)

**Record lesson on fix:** When reviewer returns critical issues and developer fixes them, append a lesson to `<project_path>/.claude/data/lessons-learned.md`:
```markdown
### [Date] Review (<category>): <brief title>
- **Anti-pattern:** <what the reviewer flagged>
- **Correct pattern:** <what the fix looked like>
- **Files:** <affected files>
- **Category:** security | performance | quality
```

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_9_summary
```
