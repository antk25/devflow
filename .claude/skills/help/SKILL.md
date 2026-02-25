---
name: help
description: Show available commands and tools
user_invocable: true
arguments: []
---

# /help - Orchestrator Help

Display available commands, agents, and workflows.

## Instructions

When this skill is invoked, output the following help message:

```markdown
# 🎯 DevFlow

## Commands

| Command | Description |
|---------|-------------|
| `/develop <feature>` | **Autonomous development** - full pipeline with atomic commits |
| `/fix <issue>` | **Quick bug fix** - search → implement → test (no planning) |
| `/refactor <scope>` | **Code refactoring** - analyze → refactor → validate → test |
| `/investigate <issue>` | **Deep analysis** - investigate without changes |
| `/explore <feature>` | **Explore feature** - research codebase, propose solutions |
| `/finalize [branch]` | **Clean up commits** - create atomic commits from work branch |
| `/plan <feature>` | Plan a feature (manual mode) |
| `/implement <task>` | Implement a task (manual mode) |
| `/review [scope]` | Review code changes (local or PR/MR) |
| `/queue <cmd>` | **Batch queue** — add, list, run tasks across projects |
| `/audit [scope]` | **Documentation audit** — compare docs with codebase reality |
| `/project <cmd>` | Manage projects (list, switch, add, info) |
| `/note <cmd>` | **Obsidian notes** — save, read, search, tz, contract, list |
| `/help` | Show this help |

## Workflows

### 🚀 Full Development (new features)
```
/develop Add user authentication
```
Pipeline: `work branch → plan → [contract → user review] → implement → validate → E2E → review → FINALIZE → summary`

Creates two branches:
- `feature/xxx-work` — iterations (backup)
- `feature/xxx` — atomic commits (push this)

### ⚡ Quick Fix (bugs, small issues)
```
/fix Login button not responding
```
Pipeline: `branch → search → implement → test → commit → summary`

### 🔧 Refactoring (code improvements)
```
/refactor src/services/auth.ts
```
Pipeline: `branch → analyze → refactor → validate → test → commit → summary`

### 💡 Exploration (new feature ideas)
```
/explore We need analytics for credit settlements
```
Pipeline: `research → analyze → propose solutions → report` (NO changes)

### 🔍 Investigation (complex issues)
```
/investigate Why is login slow on Safari?
```
Pipeline: `search → analyze → hypotheses → report` (NO changes)

### 🧹 Finalize (cleanup commits)
```
/finalize feature/auth-work
```
Pipeline: `analyze → group → create clean branch → atomic commits`

Use after manual development or interrupted `/develop`.

### 📦 Batch Queue
```
/queue add my-app: develop Add dark mode
/queue add my-api: fix Login timeout
/queue list
/queue run
```
Pipeline: sequential execution with automatic project switching.

### 📋 Documentation Audit
```
/audit                    # Full audit (patterns + lessons)
/audit patterns           # Audit patterns.md only
/audit --fix              # Audit and auto-fix documentation
```
Pipeline: `gather docs → scan codebase → compare → report` (NO code changes)

Use `--fix` to auto-update documentation to match codebase reality.

### 🤖 Smart Routing
`/develop` auto-detects workflow from keywords:
- "fix", "bug", "error" → uses `/fix` workflow
- "refactor", "clean up", "extract" → uses `/refactor` workflow
- otherwise → full development pipeline

You control only `git push`.

## Manual Workflow

```
/plan Add login feature     # Create plan
/implement 1                # Implement task #1
/review                     # Review changes
/finalize                   # Clean up commits before push
```

## Project Management

```
/project list               # List projects
/project switch myproject   # Switch context
/project add /path/to/proj  # Register project
/project info               # Current project info
```

## Agents

| Agent | Role |
|-------|------|
| PM | Requirements, planning |
| Architect | System design, ADRs |
| JS Developer | TypeScript, React, Node.js |
| PHP Developer | Laravel, Symfony |
| Tester | Unit, integration, E2E tests |
| Reviewer | Security, performance, quality |
| Architecture Guardian | Pattern validation |

## Tips

- Create `.claude/patterns.md` in your project to define conventions
- Git conventions are read from project's git log automatically
- `/develop` creates work branch (messy OK) then finalizes to clean branch
- Use `/finalize` to clean up any branch manually
- `git push` is always manual (blocked for safety)
- Work branches (`-work` suffix) kept as backup
```
