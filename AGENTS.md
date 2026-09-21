---
project: devflow
vault: /mnt/f/notes_2/projects/devflow
---

# DevFlow

## What
AI development workflow orchestration for Claude Code. The `/devflow` driver runs a research → plan → implement pipeline as three autonomous **phase agents**, each writing an artifact to the project's obsidian vault, with an explicit approval gate between phases. `/standup` gives a Jira digest ("what's new on my tasks") and routes you into the pipeline. Plus `/note` and `/project` for vault and registry management.

DevFlow itself is the meta-project. Skills (`skills/`) and phase agents (`agents/`) are symlinked into `~/.claude/skills/` and `~/.claude/agents/` via `install.sh`, so any project on this machine can use them once `AGENTS.md` is set.

## Stack
- Bash + Python 3 (scripts and hooks)
- Markdown (skills are `SKILL.md` files with YAML frontmatter)
- JSON (project registry at `.claude/data/projects.json`)
- SQLite (execution state per project); PyYAML (document metadata)

## Run
- Install/update skills + phase agents: `./install.sh` (symlinks `skills/<name>` → `~/.claude/skills/`, `agents/<name>.md` → `~/.claude/agents/`)
- Check install state: `./install.sh --check`
- Remove: `./install.sh --remove`
- Launch with project picker: `./start.sh` (interactive gum menu → opus driver)

## Conventions
- Model policy: per-phase models live in the **agent frontmatter** — `research`, `plan` and `implement` all on **claude-fable-5-1** with `effort: low` — and hold for each agent's whole run (unlike a skill's `model:` hint, which lasts one turn). The `/devflow` driver session runs on **opus** (`./start.sh <project>` launches it, or `claude --model opus`). `/code-review` and ad-hoc reasoning also default to opus; switch to sonnet with `/model` for a mostly-mechanical ad-hoc session.
- Branch base: `main`
- Commit format: `<type>(<scope>): <subject>` (e.g. `feat(plan): tighten step format`); body optional; types from conventional commits (`feat`, `fix`, `docs`, `refactor`, `chore`).
- Skills are kept short (target ≤150 lines). Cut anything that isn't actionable.
- `git push` and `gh` are blocked by `.claude/settings.json` — pushing/PR-creation is always manual.

## Workflow
The `/devflow` driver orchestrates the whole pipeline in one interactive session:

- `/devflow` — Jira standup ("what's new since last time") → pick a task → route → run the phase.
- `/devflow <slug>` — skip standup, resume at the phase the artifacts imply.

It spawns a phase agent, shows you the artifact, and **waits for your approval at the gate** before the next phase:

1. `research` agent → `vault/research/<slug>.md`   (gate)
2. `plan` agent → `vault/plans/<slug>.md`   (gate)
3. `implement` agent → `vault/changelog/<date>-<slug>.md`   (autonomous; stops on red tests / plan drift)

`/standup` alone just shows the digest and recommends a route, without entering the loop.

The shared CLI `~/.claude/skills/devflow/devflow` owns routing and state transitions. Markdown
stores definitions; SQLite stores revision-specific approvals, run results and history. Plans use
stable step IDs with dependencies, not completion flags. The driver records explicit approvals;
changed documents require a fresh gate. See README for schema, migration, recovery and backup.

Vault layout: `tz/` (specs in) · `research/` · `plans/` · `changelog/` · `notes/` (ad-hoc patterns/rules)

Use `/note save <title>` (category `notes`) to persist patterns mid-implementation. `/note search <query>` to grep the vault.

## Token accounting
`/tokens` reports spend by task, project, phase, model, or day from the local Claude Code
transcripts (`skills/tokens/token-stats.py`). The driver tags each task it routes into
`~/.claude/devflow/task-ledger.jsonl`; anything untagged falls back to Jira keys found in
the user's messages. Use `--by phase` to see how much work bypasses the pipeline — a high
`—` share means it ran ad hoc in the main session.

## Notes
- Skills are model-agnostic markdown — readable by Codex/Cursor/Aider in principle, though only Claude Code currently invokes them as `/<name>`.
- The user controls git: no auto-branches, no auto-commits.
- Tests, planning docs, and review documents are not auto-generated — only the workflow artifacts above (research / plan / changelog).
