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

**Update contract in Obsidian** (if `contract_path` exists):

If the fix changed the implementation in a way that diverges from the contract (new/modified API endpoints, changed DTO fields, different DB schema), update the contract:

```bash
# 1. Add changelog entry describing what changed
./scripts/obsidian-sync-contract.sh "<contract_path>" changelog "Phase 8 fix: <brief description of changes>"

# 2. If specific sections changed (API, DTO, Database, etc.), update them:
#    Generate updated section content to a temp file, then:
./scripts/obsidian-sync-contract.sh "<contract_path>" section "<SectionName>" /tmp/section-content.md
```

This keeps the contract as a living document that reflects the actual implementation, not just the original plan.

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_9_summary
```
