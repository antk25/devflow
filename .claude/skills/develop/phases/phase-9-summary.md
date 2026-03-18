# Phase 9: Stop & Summary

**IMPORTANT:** Do NOT finalize or create a clean branch. The workflow stops on the work branch so the user can review the result and decide on next steps (refactor, adjust, or finalize manually).

## Step 1: Mark Session as Review

Read sessions.json, set session `status: "review"`, `updated_at` to now, write back.

## Step 2: Update Claude Code Memories

Capture knowledge gained during this development session using the auto-memory system (`~/.claude/projects/.../memory/`):

1. Read `MEMORY.md` in the project memory directory to check for existing memories (avoid duplicates)
2. **Patterns:** If architecture validation or review revealed project patterns, write/update memory files:
   - File: `patterns_<category>.md` (categories: `architecture`, `testing`, `api`, `events`, `database`)
   - Use frontmatter: `type: project`, `name: patterns/<category>`
   - Content: pattern description with file references
3. **Gotchas:** If there were architecture violations, test failures, or review issues that required fixes:
   - File: `gotchas_<topic>.md`
   - Use frontmatter: `type: feedback`, `name: gotchas/<topic>`
   - Content: what went wrong, why, and how it was fixed
4. Each memory should be < 500 characters, with references to specific files
5. Update `MEMORY.md` index with pointers to new/updated memory files

Store the list of updated memories as `updated_memories` for the summary.

## Step 3: Auto-ADR (conditional)

Generate an Architecture Decision Record if ANY of these conditions are met:
- A **new architectural pattern** was established (not seen in existing code before)
- A **technology choice** was made (new library, framework, approach)
- The **data flow changed** significantly (new events, new entity relationships)
- A **feature contract** was generated (Phase 2.5)

If none of these conditions are met, skip ADR generation.

```
Task(
  description: "Auto-ADR: <feature>",
  prompt: "Evaluate whether this feature warrants an Architecture Decision Record (ADR).

  Feature: <feature description>
  Changes: <git diff --stat summary>
  Review findings: <summary of review issues>
  Architecture violations: <summary of Guardian findings, if any>
  Contract: <contract existed: yes/no>

  If the answer is NO (minor change, no new patterns, no tech choices), respond with exactly:
  NO_ADR_NEEDED

  If YES, generate an ADR in this format (max 30 lines):

  # ADR-NNN: <Title>

  ## Status
  Accepted

  ## Context
  <2-3 sentences: what was the situation?>

  ## Decision
  <2-3 sentences: what was decided?>

  ## Consequences
  <2-3 bullet points: what are the implications?>

  ## References
  - <affected files or contract path>",
  subagent_type: "Architect",
  model: "haiku"
)
```

**If NOT `NO_ADR_NEEDED`:**
1. Determine next ADR number:
   ```bash
   NEXT_ADR=$(ls <project_path>/.claude/data/adrs/adr-*.md 2>/dev/null | wc -l)
   NEXT_ADR=$((NEXT_ADR + 1))
   ```
2. Create directory if needed: `mkdir -p <project_path>/.claude/data/adrs/`
3. Write ADR file: `<project_path>/.claude/data/adrs/adr-$(printf '%03d' $NEXT_ADR)-<slug>.md`
4. Store as `adr_path` for the summary

## Step 4: Improvement Notes (mandatory)

Aggregate all observations collected during the pipeline and save to Obsidian.

1. **Merge observations** from all sources:
   - `phase3_observations` — from developer agents (Phase 3)
   - `phase4_observations` — from Architecture Guardian (Phase 4)
   - `phase7_observations` — from Code Reviewer (Phase 7)

2. **Deduplicate** by `(category, files[0])` — if same category on the same primary file appears multiple times, keep the entry with higher priority.

3. **Guard:** If the merged list is empty after dedup, skip entirely — do NOT create the file. Print: `"No improvement observations collected."` and continue.

4. **Generate Markdown file** with this format:

```markdown
---
created: <YYYY-MM-DD>
project: <project_name>
type: improvement-notes
branch: <work_branch_name>
feature: <feature description>
status: new
tags: [улучшения, <project_name>]
---

# Improvement Notes: <branch_name>

| Приоритет | Категория | Файлы | Описание | Оценка |
|-----------|-----------|-------|----------|--------|
| high | tech_debt | `src/Service/Foo.php` | Дублирование логики | 1-2 hours |
| medium | performance | `src/Repository/Bar.php` | N+1 запрос | 1 hour |
| low | style | `src/Entity/Baz.php` | Устаревший паттерн | 30 min |
```

Rows sorted by priority: high → medium → low.

5. **Save to Obsidian:**
   ```bash
   VAULT_PATH=<obsidian_vault from projects.json>
   NOTES_DIR="$VAULT_PATH/projects/<project>/improvement-notes"
   mkdir -p "$NOTES_DIR"
   # Write file: <NOTES_DIR>/<branch-slug>-improvements.md
   ```
   If Obsidian vault is not accessible (path doesn't exist), save to `.claude/data/improvement-notes/<branch-slug>-improvements.md` as fallback.

6. Store path as `improvement_notes_path` for the summary.

7. **High-priority notification** (only if high-priority items exist):
   If any items have `priority: high`, print:

   ```
   📝 Improvement Notes: N items saved to <path>
     🔴 X high priority — consider addressing these next
   ```

**Update contract status:** If `contract_path` exists, use the sync script:
```bash
./scripts/obsidian-sync-contract.sh "<contract_path>" status in_review
```
This signals in Obsidian that the implementation is ready for review.

**Update TZ status:** If `tz_path` exists (from Phase 0), update its status:
```bash
python3 -c "
import re
path = '<tz_path>'
with open(path) as f: content = f.read()
content = re.sub(r'^(status:\s*).*$', 'status: in_progress', content, count=1, flags=re.MULTILINE)
with open(path, 'w') as f: f.write(content)
"
```

**Desktop notification:**
```bash
./scripts/notify.sh "Development Ready for Review" "<feature> — work branch ready"
```

**Prepare diff summary for user:**

```bash
# For each repository
WORKTREE_PATH=<from session worktree_paths>

# Get changes summary
git -C "$WORKTREE_PATH" diff main...HEAD --stat
git -C "$WORKTREE_PATH" log main..HEAD --oneline
```

Present results to user:

```markdown
## 🔍 Ready for Review: [Feature Name]

### Work Branch

| Repo | Work Branch | Worktree Path |
|------|-------------|---------------|
| backend | `feature/auth-work` | `/path/to/.claude/worktrees/...` |
| frontend | `feature/auth-work` | `/path/to/.claude/worktrees/...` |

### Changes Summary

**backend:** (`feature/auth-work`)
<git log main..HEAD --oneline output>

**frontend:** (`feature/auth-work`)
<git log main..HEAD --oneline output>

### Files Changed
- backend: 5 created, 2 modified
- frontend: 3 created, 1 modified

### Feature Contract
<if contract_path exists>
📋 Contract: `<contract_path>` (status: in_review)
<else>
⏭️ No contract generated (simple task)
<endif>

### Architecture Compliance
✅ All patterns validated

### E2E Testing
- Backend API: ✅ Passed
- Frontend UI: ✅ Passed

### Code Review
✅ Passed (1 warning noted)
- ⚠️ Consider adding rate limiting

### Knowledge Captured
<if updated_memories is not empty>
**Memories updated:**
- `patterns/<category>` — <brief description>
- `gotchas/<topic>` — <brief description>
<else>
No new memories captured.
<endif>

<if adr_path exists>
**ADR generated:** `<adr_path>`
<else>
No ADR needed.
<endif>

### Improvement Notes
<if improvement_notes_path exists>
📝 Saved to: `<improvement_notes_path>`
<N> items (<X> high, <Y> medium, <Z> low priority)
<else>
No improvement observations collected.
<endif>

### Next Steps
Review the changes, then choose:
1. **Happy with the result?** → `/finalize` to create clean branch with atomic commits
2. **Need refactoring?** → `/refactor <what to improve>`
3. **Need fixes?** → `/fix <what to fix>`
4. **Review the diff:**
   - `cd /path/to/backend && git diff main`
   - `cd /path/to/frontend && git diff main`
```

### Worktrees
List active worktrees created during this session. The work branch stays active for further iteration.
To switch to worktree: `cd <worktree_path>`
