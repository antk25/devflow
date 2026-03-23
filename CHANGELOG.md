# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.15.0] - 2026-03-23

### Added
- **`/monitor` skill** (DF-9) — DevFlow health monitor that analyzes session logs, detects problems, and suggests improvements.
  - `full` mode — analyzes failed/stuck/looping/empty sessions, recurring problems, interruption rates, lessons-learned violations
  - `trends` mode — session statistics by skill, project, status over configurable periods
  - Python analysis script (`scripts/monitor-check.py`) with 7 check types and JSON output
- **SessionEnd hook** — `session-end-monitor.sh` runs lightweight check after every session, appends findings to `checks.jsonl`, sends desktop notification on critical/high findings.
- **Runtime debug integration** — stack-agnostic debug tooling for Debugger agent via MCP tools (Xdebug for PHP, Chrome DevTools for JS, etc.).

### Changed
- **Phase 6.5 merged into Phase 6** — test-reaction step was systematically skipped by LLM (0/19 sessions executed it). Now embedded directly in `phase-6-commit.md`, checkpoint transitions to `phase_7_review`. Eliminates the problematic intermediate decimal phase.
- **Review skill refactored** — split from single file into orchestrator + phase files architecture for better maintainability.

### Fixed
- Auto-routing for external projects now explicitly instructs Skill tool invocation.

## [0.14.0] - 2026-03-20

### Added
- **Adversarial Verification Protocol** — Tester agent template now includes structured adversarial testing (boundary values, concurrency, idempotency, orphan state) with mandatory `VERDICT: PASS/FAIL/PARTIAL` format.
- **Action Classification Framework** — Developer agent template formalizes three action levels: Prohibited (git push, gh, permanent deletions), Requires Confirmation (deps, CI config, env vars), Automatic (edits, tests, commits).
- **Autonomous Safety rules** — Developer, Reviewer, and Tester templates enforce: explicit intent required, untrusted tool results, no composite escalation, no enabling actions, independent command authorization.
- **Phase-transition reminders** — `/develop` workflow prints constraint reminders before phases 3, 4, 5, 7, 8 as drift guard for long sessions.

## [0.13.0] - 2026-03-19

### Added
- **User-level skill distribution** (DF-7) — DevFlow skills are now installed to `~/.claude/skills/` and available in any project without symlinks or copying. Uses Claude Code's native user-level skill discovery.
- **`devflow-setup.sh`** — setup script with 4 commands:
  - `install` / `update` — copies 13 skills to `~/.claude/skills/`, installs `devflow-instructions.md`, adds `@include` to `~/.claude/CLAUDE.md`
  - `project <name>` — generates `project.json`, `settings.json`, `.mcp.json`, `.gitignore` entries
  - `status` — shows installed skills (devflow vs custom), per-project configuration status
  - `uninstall` — removes devflow-managed skills only, preserves custom skills
- **Per-project config (`project.json`)** — each project gets its own `.claude/data/project.json` with all config (git, repos, testing, docker, obsidian). Central `projects.json` remains only for `start.sh` launcher and `/project list/add`.
- **Per-project Obsidian paths** — `obsidian.vault` + `obsidian.project_dir` in `project.json` allow each project to specify its own artifact storage location.
- **Project-specific skills** — projects can add their own skills in `<project>/.claude/skills/` alongside devflow skills. Project skills override same-named devflow skills (Claude Code priority: project > user).
- **`start.sh setup` passthrough** — `./start.sh setup <args>` delegates to `devflow-setup.sh`

### Changed
- **`start.sh` launches from project directory** — for non-devflow projects, `cd` to project path before `exec claude`. DevFlow itself still launches from its own directory (project skills take priority for development).
- **`start.sh` warns unconfigured projects** — shows setup instructions if `.claude/settings.json` is missing.
- **`read-project-config.sh`** reads local `project.json` first, falls back to central `projects.json`.
- **`project-restore.sh`** reads local `project.json` first for session start context.
- **`obsidian-active.sh` / `obsidian-save-tz.sh`** read vault path from local `project.json`.
- All skill references updated from `projects.json` to `project.json` (except `/project` skill which manages the central registry).
- Updated `multi-project.md` with full skill distribution architecture documentation.

## [0.12.0] - 2026-03-18

### Added
- **Auto-save TZ to Obsidian** (DF-6) — `/develop` Phase 0 automatically saves the user's feature description to `projects/<project>/tz/` in Obsidian vault. Incremental additions appended with `## Дополнение (timestamp)` via `--update` mode.
- **Contract sync after fixes** (DF-6) — Phase 8 updates the Obsidian contract when post-review fixes change the implementation: changelog entries and section-level updates keep the contract as a living document.
- **Active Obsidian context at startup** (DF-6) — `project-restore.sh` hook outputs `OBSIDIAN_CONTEXT` JSON with active contracts, TZ, and improvement notes. Phase 0 of `/develop`, `/fix`, and `/resume` reads this context automatically.
- New scripts: `obsidian-save-tz.sh`, `obsidian-sync-contract.sh`, `obsidian-active.sh`

## [0.11.0] - 2026-03-18

### Added
- **Unified git workflow config** (DF-5) — declarative `git` section in `projects.json` with per-project base branch, branch naming, commit format, MR/release settings. Replaces scattered `branch_prefix`, `main_branch`, `commit_style` fields.
  - `git.base_branch` — which branch to create features from (`dev`, `develop`, `main`, `master`)
  - `git.branch` — prefix, work suffix, type prefix toggle
  - `git.commit` — format template, body, coauthor, language
  - `git.mr` — MR/PR target, tool (gitlab/github), squash policy
  - `git.release` — tag/branch release config

### Changed
- `create-branch.sh` reads `git.base_branch` and `git.branch.type_prefix` from project config (with auto-detection fallback).
- `read-project-config.sh` exposes `git` config with backward compatibility for legacy fields.
- Skills (`/develop`, `/fix`, `/refactor`, `/finalize`) use `git.commit` config instead of parsing `git log` each time.
- `/project add` now detects and asks for git workflow config during registration.
- All 9 projects migrated to new `git` section. Legacy fields removed.
- `projects.json` version bumped to 2.1.

## [0.10.0] - 2026-03-18

### Added
- **Reasoning Before Action** (SGR-inspired) — developer and tester agent templates now include an explicit reasoning phase before making changes. Developer: Assess → Trace impact → Identify risks → Choose approach. Tester: 4 mandatory questions (behavior, boundaries, dependencies, failure condition) before writing any test.

### Removed
- **`/queue` skill** — batch task queue (`SKILL.md`, `queue-bg.sh`, `queue-report.sh`, `queue.json`). Rarely used in practice.
- **`/help` skill** — redundant with startup greeting that lists all commands.
- **`/plan` + `/implement` skills** — manual step-by-step mode. `/develop` has built-in checkpoints that serve the same purpose.
- **`/jira` skill** — moved to project-level (each project defines its own integration in `<project>/.claude/skills/jira/`).

### Changed
- `devflow-status.sh` and `tmux-status.sh` simplified — removed queue display logic.
- Phase 9 improvement notes no longer suggest `/queue add` commands; shows high-priority notification instead.
- `/explore` routing updated: flows into `/develop` instead of removed `/plan`.
- Documentation updated across CLAUDE.md, README.md, workflows.md, multi-project.md.

## [0.9.0] - 2026-03-18

### Added
- **Reasoning Before Action** in agent templates (developer, tester) — explicit reasoning phase before code changes.
- **Enhanced Contract-Driven Development** — dual contract format, test-first expansion, simplified review/project workflows.

## [0.8.0] - 2026-03-13

### Added
- **Adversarial debate protocol** for code review — 3-round debate (Independent → Challenge → Defense) between Claude, Qwen, and ChatGPT reviewers. Challenged findings get defended with evidence or withdrawn, eliminating false positives. Enabled by default, disable with `--no-debate` or `review_debate: false` in `agent_config`.
- **Recursive sub-agents** (toggleable) — subagents can spawn sub-subagents up to configurable `max_depth`. Enables divide-and-conquer for complex tasks. Disabled by default, enable per-project with `agent_config.recursive_agents: true`.
- **Generative analysis** — agents can write and execute analysis scripts (Python/TS) instead of chaining grep calls. Added to developer, debugger, and tracer agent templates. Always available, no config needed.
- **Structured return contract** — all subagents follow a mandatory return format (Answer, Key Files, Implementation Notes). Raw file contents, grep output, and intermediate reasoning prohibited in returns. Reduces context pollution in orchestrator.
- **`agent_config`** in `projects.json` — per-project agent behavior configuration (`recursive_agents`, `max_depth`, `review_debate`). Defaults applied via `read-project-config.sh`.

### Changed
- `/develop` Phase 7 review now includes debate rounds (Steps 4-7) when `review_debate` is enabled.
- `/review` skill now includes debate protocol (Step 5) with Challenge and Defense rounds.
- All agent templates updated with Return Format section.
- Developer template updated with Generative Analysis and Delegation sections.
- Debugger and Tracer agents updated with Generative Analysis examples.

## [0.7.0] - 2026-03-05

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

[Unreleased]: https://github.com/antk25/devflow/compare/v0.10.0...HEAD
[0.10.0]: https://github.com/antk25/devflow/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/antk25/devflow/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/antk25/devflow/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/antk25/devflow/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/antk25/devflow/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/antk25/devflow/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/antk25/devflow/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/antk25/devflow/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/antk25/devflow/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/antk25/devflow/releases/tag/v0.1.0
