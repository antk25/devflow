# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/antk25/devflow/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/antk25/devflow/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/antk25/devflow/releases/tag/v0.1.0
