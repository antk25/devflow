# Phase 4: Architecture Validation

After each implementation, spawn Architecture Guardian:

```
Task(
  description: "Validate architecture",
  prompt: "Review the following changes for architecture compliance:

  Repository: <repo_path>
  Changed files: [list]

  Project patterns: [patterns from Phase 0]

  <if rag_context contains architecture/pattern info, append:>

  ## Documented Project Patterns (from Knowledge Base)
  <architecture-related rag_context>

  <if feature_contract is not empty, append:>

  ## Feature Contract (verify compliance)
  <feature_contract>

  Verify implementation matches ALL contract sections (API, DTO, Events, Database, Components).
  Parse YAML code blocks for exact field names and types.

  <endif>

  Return TWO sections:

  ## Validation Result
  Status: pass/warn/fail with specific issues for the CHANGED files.

  ## Out-of-Scope Findings
  Issues you noticed in SURROUNDING code (NOT in the changed files) that violate patterns or could be improved.
  Return as a JSON block:

  ```json:out_of_scope_findings
  [
    {
      \"category\": \"tech_debt|potential_bug|performance|security|style\",
      \"title\": \"Brief description\",
      \"files\": [\"path/to/file.ext\"],
      \"description\": \"Details\",
      \"priority\": \"high|medium|low\",
      \"estimate\": \"30 min|1-2 hours|2-4 hours\"
    }
  ]
  ```
  If no out-of-scope findings, return an empty array. These do NOT affect the pass/warn/fail status.",
  subagent_type: "Architecture Guardian"
)
```

**After Guardian responds**, parse the `json:out_of_scope_findings` block from its output. Extract the JSON array and append items to the `phase4_observations` list.

**If FAIL:** Use loop detection script to track retry attempts:

1. Spawn developer agent with fix instructions (include Guardian's failure details)
2. After fix, check for loops:
   ```bash
   HASH=$(cd <repo_path> && git diff HEAD~1 --stat | md5sum | cut -d' ' -f1)
   DECISION=$(./scripts/check-loop.sh <branch> arch_validation "$HASH")
   ```
3. Based on `DECISION`:
   - **CONTINUE** → re-run Guardian validation. If PASS → break. If FAIL → go to step 1.
   - **LOOP_DETECTED** → re-spawn developer with: `"LOOP DETECTED: Try a FUNDAMENTALLY DIFFERENT approach. Previous failures listed in stderr above."`
   - **GIVE_UP** → add warning to summary, continue to next phase (do not block pipeline)

**Record lesson on fix:** When Guardian returns `fail` and developer fixes it, append a lesson to `<project_path>/.claude/data/lessons-learned.md`:
```markdown
### [Date] Architecture: <brief title>
- **Anti-pattern:** <what was wrong>
- **Correct pattern:** <what the fix looked like>
- **Files:** <affected files>
- **Rule:** <which pattern was violated>
```

**If WARN:** Note warnings, continue.
**If PASS:** Continue to next task.

**Checkpoint:**
```bash
# If validation passed:
./scripts/session-checkpoint.sh <branch> phase_5_e2e result=success
# If validation had warnings:
./scripts/session-checkpoint.sh <branch> phase_5_e2e result=warning reason='architecture warnings noted'
# If GIVE_UP:
./scripts/session-checkpoint.sh <branch> phase_5_e2e result=warning reason='validation loop — gave up after max attempts'
```
