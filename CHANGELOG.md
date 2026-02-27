# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/user/devflow/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/user/devflow/releases/tag/v0.1.0
