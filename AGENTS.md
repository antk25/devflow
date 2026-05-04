---
project: devflow
vault: /mnt/f/notes_2/projects/devflow
---

# DevFlow

## What
AI development workflow orchestration for Claude Code. Provides three thin skills — `/research`, `/plan`, `/implement` — that structure work into discrete phases, each writing an artifact to the project's obsidian vault. Plus `/note` and `/project` for vault and registry management.

DevFlow itself is the meta-project. Skills shipped from `skills/` are symlinked into `~/.claude/skills/` via `install.sh`, so any project on this machine can use them once `AGENTS.md` is set.

## Stack
- Bash + Python 3 (scripts and hooks)
- Markdown (skills are `SKILL.md` files with YAML frontmatter)
- JSON (project registry at `.claude/data/projects.json`)

## Run
- Install/update skills: `./install.sh` (creates symlinks `~/.claude/skills/<name>` → `skills/<name>`)
- Check install state: `./install.sh --check`
- Remove: `./install.sh --remove`
- Launch with project picker: `./start.sh` (interactive gum menu)

## Conventions
- Branch base: `main`
- Commit format: `<type>(<scope>): <subject>` (e.g. `feat(plan): tighten step format`); body optional; types from conventional commits (`feat`, `fix`, `docs`, `refactor`, `chore`).
- Skills are kept short (target ≤150 lines). Cut anything that isn't actionable.
- `git push` and `gh` are blocked by `.claude/settings.json` — pushing/PR-creation is always manual.

## Workflow
Three phases, each in a fresh session:

1. `/research <task>` → `vault/research/<slug>.md`
2. `/plan <slug>` → `vault/plans/<slug>.md`
3. `/implement <slug>` → `vault/changelog/<date>-<slug>.md`

Vault layout: `tz/` (specs in) · `research/` · `plans/` · `changelog/` · `notes/` (ad-hoc patterns/rules)

Use `/note save <title>` (category `notes`) to persist patterns mid-implementation. `/note search <query>` to grep the vault.

## Notes
- Skills are model-agnostic markdown — readable by Codex/Cursor/Aider in principle, though only Claude Code currently invokes them as `/<name>`.
- The user controls git: no auto-branches, no auto-commits.
- Tests, planning docs, and review documents are not auto-generated — only the three workflow artifacts above.
