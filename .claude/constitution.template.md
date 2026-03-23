<!-- Project Constitution: immutable principles that ALL agents must follow.
     Copy to `.claude/constitution.md` and customize for your project.
     Keep under 50 lines — these are hard rules, not guidelines. -->

# Constitution

## Architectural Principles

<!-- Define 3-7 non-negotiable rules for your project.
     Each rule should be testable by the Architecture Guardian.
     Format: short title + one-sentence rationale. -->

### Article I: [Domain Purity]
<!-- Example: Domain layer has no infrastructure dependencies -->
Domain/business logic MUST NOT depend on infrastructure (filesystem, HTTP, database drivers).
Extract interfaces at the Application layer; implement in Infrastructure.

### Article II: [Single Representation]
<!-- Example: One DTO per boundary, no redundant mapping layers -->
Each boundary (API, Events, Commands) uses a single DTO representation.
Do not create wrapper/adapter DTOs unless crossing an explicit module boundary.

### Article III: [Test-First for Contracts]
<!-- Example: Contract tests before implementation -->
When a feature contract exists, tests MUST be written before implementation code.
Implementation is driven by making red tests green.

### Article IV: [Integration over Mocks]
<!-- Example: Real databases in tests, not mocks -->
Tests MUST use real infrastructure (database, queues) where feasible.
Mocks are allowed ONLY for external third-party services.

### Article V: [Simplicity Gate]
<!-- Example: No premature abstractions -->
No abstraction layer may be introduced for a single use case.
Wrap framework features only when 3+ consumers exist with divergent needs.

## Pre-Implementation Checklist

<!-- These are verified by the Architecture Guardian BEFORE implementation starts.
     A "no" answer blocks the pipeline until resolved. -->

- [ ] Does the plan respect all Articles above?
- [ ] Are boundary contracts (API, Events, DB) defined before coding?
- [ ] Is there a clear reason for every new file/class introduced?
- [ ] Are there no speculative features (YAGNI)?
