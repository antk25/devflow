# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`/project agents`** command — analyzes the active project's codebase (stack, architecture, patterns, tests) and generates customized agents in `<project>/.claude/agents/`. Determines which agents are needed (developer, tester, guardian, reviewer) based on project complexity.

## [0.6.0] - 2026-03-05

### Added
- **Project-specific agents** — projects can define customized agents in `<project>/.claude/agents/` that override generic DevFlow agents with project-specific stack knowledge, architecture patterns, and conventions. Resolution order: specific agent (`js-developer.md`) → generic (`developer.md`) → DevFlow fallback.
- **Agent templates** (`.claude/agents/templates/`): extracted universal rules (test quality, security, architecture compliance, autonomous mode) into reusable templates for developer, reviewer, tester, and architecture guardian agents.
- **`resolve-agent.sh`** script: resolves the correct agent file for a given role and project path. Used by `/develop` phases 3, 4, 7 to load project agents before spawning.
- **Captivia project agent** (`captivia/.claude/agents/developer.md`): first project-specific agent — covers Symfony DDD, CQRS with 4 message buses, API Platform state pattern, EventBus rules, testing conventions.

### Changed
- `/develop` Phase 3 (implement), Phase 4 (validate), Phase 7 (review) now load project-specific agents and prepend them to task prompts with `## Project-Specific Instructions (PRIORITY)` header.
- `read-project-config.sh` now detects `has_project_agents` in project config output.
- **Serena memories migrated**: captivia and rs project memories moved from DevFlow's Serena to their own project Serena directories. DevFlow Serena now contains only devflow-related memories.

## [0.5.0] - 2026-03-05

### Added
- **Triple review** — ChatGPT added as third reviewer alongside Claude and Qwen. All three run in parallel during `/develop` Phase 7 and `/review`. Findings merged with confidence scoring: 3 agree → highest confidence, 2 agree → high, 1 only → normal.
- **ChatGPT MCP server** (`mcp-servers/chatgpt-review/`): MCP server providing `gpt_code_review`, `gpt_contract`, and `gpt_plan` tools via OpenAI API. Used by triple review, triple planning, and triple contract generation.
- **Triple planning** — ChatGPT participates in `/develop` Phase 2 planning alongside Claude and Qwen. Plans merged with source tagging (`[Claude + Qwen + ChatGPT]`).
- **Triple contract generation** — ChatGPT participates in `/develop` Phase 2.5 contract generation. Contracts merged with agreement annotations.

### Changed
- Review output format updated from "Dual Review" to "Triple Review" with confidence scoring table (`All 3 | 2 of 3` columns).

## [0.4.0] - 2026-03-03

### Added
- **Background queue execution** (DF-3): `scripts/queue-bg.sh` — launch `/queue run` in a detached tmux session (`start`/`stop`/`status` subcommands). Queue items execute autonomously while you work.
- **Morning report** (DF-3): `scripts/queue-report.sh` — generates a summary of overnight queue results (completed, failed, skipped) with branch names and error details.
- **Per-task notifications** (DF-3): Queue skill sends desktop notifications (`notify-send`) on each task completion/failure during background runs.
- **`devflow-status` CLI** (DF-4): `scripts/devflow-status.sh` — one-shot dashboard displaying active session (phase progress bar, duration, loops), queue status, and recent sessions. Subcommands: `session`, `queue`, `recent [N]`. Designed for `watch -n2`. Bash + embedded Python, no external dependencies.
- **tmux status bar** (DF-4): `scripts/tmux-status.sh` — compact one-line output (`⏳ /develop Implement 47% [Q:2/5]`) for tmux `status-right`. No ANSI colors, max ~50 chars.

### Removed
- **devflow-tui** (DF-4): Removed Textual-based TUI monitor (`devflow-tui/`). Replaced by simpler `devflow-status` CLI and tmux integration that require no Python venv or external dependencies.

## [0.3.0] - 2026-03-02

### Added
- **`/resume` skill** (DF-2): Resume interrupted `/develop`, `/fix`, or `/refactor` sessions. Finds sessions by branch name or picks the most recent interrupted one. Validates git state, displays phase progress, and dispatches to the original skill's pipeline with `--resume` flag. Supports `list` mode to show all interrupted sessions.
- **Interrupted session detection at startup**: `project-restore.sh` hook checks for interrupted/stale sessions and displays `INTERRUPTED_SESSION` info in the greeting. Claude shows a resume prompt automatically.
- **`mark-interrupted` / `check-interrupted` CLI commands** in `session-log.py`: Mark stale running sessions as interrupted (5-min staleness window), check for interrupted sessions filtered by project (1-hr staleness for running). Atomic JSON writes via tempfile + `os.replace` prevent corruption.

## [0.2.0] - 2026-02-27

### Added
- **Improvement Notes artifact** (DF-1): Agents collect out-of-scope observations during development and save them as a structured Obsidian note. Three collection points: developer agents (`json:improvement_observations`), Architecture Guardian (`json:out_of_scope_findings`), Code Reviewer (`json:review_improvement_notes`). Phase 9 aggregates, deduplicates by `(category, file)`, and saves to Obsidian vault with priority-sorted table. High-priority items generate suggested `/queue add` commands.
- **Observation support in `/fix` and `/refactor`**: Developer agents in both skills can now report out-of-scope findings via `json:improvement_observations`. Summaries include an Observations section with pseudo-template conditional display.

### Changed
- **`/develop` SKILL.md split into phase files**: Compact 246-line router + 14 phase files (`phases/phase-*.md`) + 2 templates (`templates/dual-*.md`). Each phase is loaded on-demand via Read tool before execution, reducing context window pressure by ~1300 lines per invocation.

## [0.1.0] - 2026-02-27

### Added
- **Test isolation policy**: Developer agents are prohibited from modifying test files. Only the Tester agent can write tests. Post-implementation verification (Phase 3.5) reverts any test file changes made by developer agents. Rules enforced in `/develop`, `/fix`, and `/refactor` skills.
- **Test-first from contract** (Phase 2.7): When a C-DAD contract exists, Tester agent generates tests from the contract BEFORE implementation (red-green-refactor cycle). Developer agents receive only pass/fail results, never test source code.
- **Cross-model code review** in `/develop` Phase 7: Claude Code Reviewer and Qwen Code Review run in parallel. Findings are merged with deduplication and source tagging (`[Claude]`, `[Qwen]`, `[Claude + Qwen]`).
- **Auto-ADR generation** in `/develop` Phase 9: Automatically generates Architecture Decision Records when new patterns, technology choices, or data flow changes are detected. Stored in `<project>/.claude/data/adrs/`.
- **Serena memory capture** in `/develop` Phase 9: Automatically saves discovered patterns and gotchas to Serena memories after each development session.
- **CHANGELOG.md**: Project now follows Keep a Changelog and Semantic Versioning.

### Changed
- **patterns.template.md** restructured from 140 to 68 lines. Removed abstract rule sections ("Forbidden Patterns", "Required Patterns"), inlined naming conventions into directory structure, folded code patterns into Reference Implementations. Advisory warning logged when project patterns.md exceeds 100 lines.
- **`/develop` pipeline** updated: `→ [test-first] → implement → ... → dual review (Claude + Qwen) → knowledge capture → STOP`

[Unreleased]: https://github.com/antk25/devflow/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/antk25/devflow/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/antk25/devflow/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/antk25/devflow/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/antk25/devflow/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/antk25/devflow/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/antk25/devflow/releases/tag/v0.1.0
