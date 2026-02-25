# Workflows Reference

Detailed documentation for all orchestrator workflows. Skills read this file when they need workflow details.

## Autonomous Development (`/develop`)

```
/develop <feature description>
```

Autonomous implementation pipeline:
```
create work branch → [deep trace] → plan → [contract → user review] → implement (atomic commits) → validate → fix → E2E test → summary
                          ↑                                                                              ↓
                 (for business logic)                                                      user reviews commits & code
                                                                                                         ↓
                                                                                      user requests fixes (if needed)
                                                                                                         ↓
                                                                                           /review → fix (if needed)
                                                                                                         ↓
                                                                                   /finalize → clean branch with merged commits
```

**Two-Branch Strategy:**
- `DEV-XXX-work` — atomic logical commits during development, user reviews & fixes here
- `DEV-XXX` — final clean commits (merged: tests joined with implementation commits where possible)

Work branch is kept as backup. You push only the clean branch.

**Work branch commit strategy:**
Each logical unit of work gets its own commit during development. Examples:
- `DEV-488 Extend BankAnalytics repository with findById and deleteOverlapping`
- `DEV-488 Add UpdateBankAnalytics command and handler`
- `DEV-488 Add functional tests for BankAnalytics handlers`

Commits in the work branch should already be atomic and logical — NOT messy WIP commits.

**Smart Routing:** `/develop` automatically detects the workflow type:
- Keywords like "fix", "bug", "error" → routes to `/fix` workflow
- Keywords like "refactor", "clean up" → routes to `/refactor` workflow
- Keywords like "analytics", "event", "status", "sync" → **requires Deep Trace phase**
- Otherwise → full development pipeline

**Deep Trace Phase (for business logic):**
When task involves modifying existing business logic, event handlers, or calculations, `/develop` performs Deep Trace analysis BEFORE planning:
- Traces data flow: source → filters → processing → output
- Maps event chains: what triggers what, what dispatches what
- Identifies entity relationships: correct join paths, one-to-many vs many-to-many
- Finds edge cases: first run behavior, null states, missing relations

This prevents bugs like:
- Listening to wrong events (e.g., `Created` instead of `StatusChanged`)
- Wrong entity relationships (e.g., iterating ALL providers instead of ONE)
- Missing edge cases (e.g., entity created already in final state)

**Contract-Driven Phase (C-DAD):**
When the plan involves 2+ layers (API + DB, Handler + Event, etc.) or is a multi-repo feature, `/develop` generates a **feature contract** and saves it to Obsidian:
- Architect generates contract with YAML code blocks (API, DTO, Events, Database, Components)
- Contract saved to `projects/<project>/contracts/<branch>-<feature>.md`
- Pipeline **pauses** — you review/edit the contract in Obsidian
- When you type `go`, the pipeline re-reads the contract (with your edits) and continues
- All agents (Developer, Tester, Guardian, Reviewer) receive the contract as source of truth
- Contract status tracks: `draft` → `approved` → `implemented`

Use `/note contract <branch>` to read a contract later.

**Multi-repo projects:** Creates branches in all affected repositories and handles git operations per-repo.

---

## Quick Bug Fix (`/fix`)

```
/fix <bug description>
```

Streamlined pipeline for bugs and small fixes:
```
create branch → search → implement → test → commit → summary
```

**No planning phase** - goes directly from search to implementation.

Best for:
- Bug fixes
- Small issues
- Typos and minor corrections
- Broken functionality

---

## Code Refactoring (`/refactor`)

```
/refactor <scope>
```

Structured refactoring pipeline:
```
create branch → analyze → refactor (step by step) → validate → test → commit → summary
```

**Behavior preservation** - tests must pass after each step.

Best for:
- Code cleanup
- Extracting methods/classes
- Renaming
- Restructuring

Examples:
```
/refactor src/services/auth.ts      # Refactor specific file
/refactor src/components/           # Refactor directory
/refactor Payment service           # Refactor by description
```

---

## Problem Investigation (`/investigate`)

```
/investigate <issue description>
```

Deep analysis pipeline for bugs and issues:
```
search → analyze → hypotheses → solutions report (NO changes)
```

**No code modifications** - pure investigation and analysis.

Best for:
- Intermittent bugs
- Complex issues with multiple possible causes
- Understanding before fixing
- Documenting findings for the team

**Flags:**
- `--deep` - More thorough, checks git history
- `--quick` - Fast scan, top 3 suspects only
- `--test` - Also run tests to gather data

---

## Feature Exploration (`/explore`)

```
/explore <feature idea>
```

Research and analysis pipeline for vague feature ideas:
```
research codebase → analyze architecture → propose 2-3 approaches → recommend → report
```

**No code modifications** - pure research and solution design.

**Position in workflow:** `/explore` -> user picks approach -> `/develop` or `/plan`

Best for:
- Vague or high-level feature ideas
- Architecture decisions before implementation
- Understanding impact before committing
- Comparing multiple solution approaches

---

## Code Review (`/review`)

```
/review                          # Review staged changes
/review --pr 123                 # Review GitHub PR
/review --mr 45                  # Review GitLab MR
/review --branch feature/auth    # Review branch vs main
```

Comprehensive code review with support for external PRs/MRs:
```
gather code → gather project patterns → dual review (Claude + Qwen) → merged report
```

**Dual review is always on** — both Claude Code Reviewer and Qwen run in parallel on every review. Use `--no-qwen` to run Claude-only.

**Project pattern awareness** — before spawning reviewers, gathers analogous code patterns from the codebase (via Serena memories + Explore agent). Reviewers are instructed not to flag code that follows established project conventions, preventing false positives.

**Supports external developer review** - PRs from teammates or open source.

**Options:**
- `--focus security` - Focus on security issues only
- `--quick` - Fast review, critical issues only
- `--comment` - Post review comments to PR/MR
- `--base develop` - Compare against non-main branch
- `--no-qwen` - Skip Qwen, run Claude-only review

---

## Documentation Audit (`/audit`)

```
/audit                    # Full audit
/audit patterns           # Audit patterns.md only
/audit --fix              # Audit and auto-fix documentation
```

Compares project documentation against codebase reality:
```
gather docs → scan codebase → compare → report (optionally auto-fix)
```

**No code modifications** - only documentation changes (with `--fix`).

---

## Finalize Branch (`/finalize`)

```
/finalize                    # Finalize current branch
/finalize feature/auth-work  # Finalize specific branch
```

Analyzes work branch commits and creates a clean final branch with merged atomic commits:
```
analyze work branch commits → merge related changes (impl + tests) → create clean branch → apply merged commits → verify
```

**Merging logic:**
- Test commits are merged with the implementation commit they cover (when possible)
- Fix/refactor commits after review are merged into the original implementation commit
- Independent changes remain as separate commits

---

## Manual Step-by-Step

```
1. /plan     → PM analyzes requirements, creates subtasks
2. /implement → Developer agent implements the solution
3. /review   → Reviewer performs code review
4. /finalize → Clean up commits before push
```

---

## E2E Testing

After implementation, the orchestrator verifies the feature works:

**Backend (API):**
- Uses `curl` to test affected endpoints
- Validates response status and structure
- Falls back gracefully if server not running

**Frontend (UI):**
- Uses Playwright MCP or `npx playwright test`
- Tests affected user flows
- Falls back gracefully if not running

---

## Data Storage

Task and project data is stored in `.claude/data/`:
- `tasks.json` - Current tasks and their status
- `projects.json` - Project registry and active project
- `queue.json` - Batch task queue and execution history
- `sessions.json` - Session tracking, loop detection, and checkpoints

### Session Tracking (`sessions.json`)

Tracks active and past workflow sessions for loop detection and resume capability.

**Schema:**
```json
{
  "version": "1.0",
  "sessions": {
    "<branch-name>": {
      "skill": "develop|fix|refactor",
      "feature": "description",
      "project": "project-name",
      "started_at": "ISO8601",
      "updated_at": "ISO8601",
      "status": "running|interrupted|completed|failed",
      "current_phase": "phase_3_implement",
      "completed_phases": ["phase_0_config", "phase_1_branch", "phase_2_plan"],
      "phase_data": {
        "phase_2_plan": { "plan_summary": "..." },
        "phase_2.5_contract": { "contract_path": "/path/to/contract.md" }
      },
      "loops": {
        "arch_validation": { "attempt": 0, "max_attempts": 3, "diff_hashes": [], "failures": [] },
        "review_fix": { "attempt": 0, "max_attempts": 2, "diff_hashes": [], "failures": [] },
        "test_fix": { "attempt": 0, "max_attempts": 2, "diff_hashes": [], "failures": [] }
      },
      "branches": { "work": "feature/xxx-work", "final": "feature/xxx" },
      "repos": ["backend", "frontend"],
      "worktree_paths": {
        "backend": "/path/to/backend/.claude/worktrees/feature-xxx-work",
        "frontend": "/path/to/frontend/.claude/worktrees/feature-xxx-work"
      },
      "phase_history": [
        {"phase": "phase_0_config", "completed_at": "ISO8601", "duration_seconds": 12, "result": "success", "reason": ""},
        {"phase": "phase_5_e2e", "completed_at": "ISO8601", "duration_seconds": 0, "result": "warning", "reason": "server not running"}
      ]
    }
  }
}
```

**Phase history:** Optional array tracking each completed phase with timing and result:
- `phase` — phase name
- `completed_at` — ISO8601 timestamp
- `duration_seconds` — seconds since previous phase completed (or session start)
- `result` — `success`, `warning`, `skipped`, or `failed`
- `reason` — explanation for non-success results (empty string if success)

Old sessions without `phase_history` still work — it's appended by `session-checkpoint.sh` when present.

**Loop detection:** Each retry loop computes an md5 hash of the diff or test output. If the same hash appears twice, the loop is broken and the pipeline continues with a warning.

**Resume:** Use `--resume` with `/develop` or `/refactor` to continue an interrupted session from the last completed phase.

**Session lifecycle:** `running` → `completed` (success) or `failed` (error). Sessions left as `running` after interruption are automatically resumable.

### Standardized Task Format

When tasks enter the orchestrator from different sources (user text, Obsidian TZ, GitHub issues), they are normalized into a standard format before being passed to workflows:

```json
{
  "title": "Short imperative title",
  "description": "Full description with context",
  "acceptance_criteria": ["criterion 1", "criterion 2"],
  "source": "text|obsidian|github",
  "source_ref": "path or URL or empty"
}
```

**Normalization rules by source:**

| Source | Title | Description | Acceptance Criteria |
|--------|-------|-------------|---------------------|
| `text` (user input) | First sentence or first line | Full message text | Extract from checklist items if present, otherwise empty |
| `obsidian` (TZ/note) | First `#` heading | Full note content (minus frontmatter) | Extract from `- [ ]` checklist items or `## Критерии приёмки` section |
| `github` (issue/PR) | Issue/PR title | Issue/PR body | Extract from task lists `- [ ]` in the body |

**Usage in workflows:**
- `/note tz` normalizes TZ into this format before routing to a skill
- `/develop` Phase 2 (PM prompt): if standardized task is provided, includes `acceptance_criteria` in the planning prompt
- `/develop` Phase 7 (Review): reviewer verifies implementation against `acceptance_criteria`

### Project Configuration (v2.0)

Projects support multi-repository setups and E2E testing configuration:

```json
{
  "name": "my-fullstack-app",
  "path": "/home/user/projects/my-app",
  "type": "fullstack",
  "repositories": {
    "backend": "/home/user/projects/my-app/backend",
    "frontend": "/home/user/projects/my-app/frontend"
  },
  "testing": {
    "backend": {
      "type": "api",
      "base_url": "http://localhost:8000",
      "commands": {
        "unit": "cd {{repo}} && ./vendor/bin/phpunit",
        "e2e": "curl -s {{base_url}}/api/health | jq ."
      }
    },
    "frontend": {
      "type": "browser",
      "base_url": "http://localhost:3000",
      "commands": {
        "unit": "cd {{repo}} && npm test",
        "e2e": "cd {{repo}} && npx playwright test"
      }
    }
  }
}
```

**Key fields:**
- `repositories` - paths to each git repository (required for multi-repo projects)
- `testing` - E2E testing configuration per component
- `branch_prefix` - prefix for feature branches (e.g., "DEV-")
