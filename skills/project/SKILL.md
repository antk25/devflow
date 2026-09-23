---
name: project
description: Project registry and onboarding. init/add a project (AGENTS.md draft + vault + identity + database + registry), sync missing pieces, list, info, remove. Switching is done outside Claude Code via start.sh.
user_invocable: true
arguments:
  - name: command
    description: "init | add | sync | list | info | remove"
    required: true
  - name: target
    description: "Project path (init/add), project name or --all (sync/info/remove)"
    required: false
---

# /project — Project onboarding and registry

Thin wrapper over the shared CLI `~/.claude/skills/devflow/devflow project …`. The CLI owns what
a project consists of (vault directories, `AGENTS.md`, `.devflow/project.json`, database, registry
entry) and reports as JSON `{project, path, items: [{item, status, detail}]}`. This skill only runs
the dialogue: gathers facts, shows drafts and reports, asks before writing.

Registry: `<DEVFLOW_DIR>/.claude/data/projects.json` (`{version, active, projects: {name: {path,
description}}}`). Everything project-specific lives in the project's own `AGENTS.md`.

## Umbrella directory rule

A DevFlow project is the **umbrella directory** `<project>/` that contains one or more repositories
(`<project>/backend`, `<project>/frontend`). `AGENTS.md`, `.devflow/` and personal settings live in
the umbrella and are **never committed into the repositories**. `init` works only at umbrella level;
if the umbrella itself is a git repository the CLI reports `git: attention` — relay the warning and
ask the user to check `.gitignore` before continuing.

## Report table

Print every CLI report the same way, then one line for each `attention` item:

```
| Item | Status | Detail |
|------|--------|--------|
| agents_md | create | из черновика |
| identity  | skipped | /path/.devflow/project.json |
```

`created` — written now · `create` — would be written (`--dry-run`) · `skipped` — already there,
untouched · `attention` — needs the user; nothing was changed for it.

## Command: (no args)

```
**Active project:** <name>   **Path:** <path>
Commands: init|add <path> [name] | sync [name|--all] | list | info [name] | remove <name>
To switch projects: exit Claude Code and run `./start.sh [name]`.
```

## Command: `init <path> [name]` (`add` is an alias)

1. `ls <path>` — stop if the directory does not exist. Name defaults to the basename.
2. **`<path>/AGENTS.md` exists** → skip discovery, go to step 6 without `--agents-draft`
   (the CLI keeps the file and takes the name from its frontmatter).
3. **No `AGENTS.md`** → spawn the built-in `Explore` subagent (read-only, session model) with:

   > Только чтение, ничего не менять. Каталог `<path>` — общий каталог проекта, внутри могут быть
   > несколько репозиториев. Прочитай `AGENTS.md`/`CLAUDE.md`/`README*` в корне и в подкаталогах
   > первого уровня, файлы стека (`composer.json`, `package.json`, `pyproject.toml`, `go.mod`,
   > `Makefile`, `docker-compose*`), CI-конфиги и `git log --oneline -30` каждого репозитория.
   > Верни факты, **каждый с файлом-источником**: что делает проект; язык/фреймворк и версии;
   > команды install/dev/test/lint; базовая и продовая ветки; формат коммитов (по реальной
   > истории); неочевидные конвенции; список репозиториев. Чего в файлах нет — пиши `неизвестно`,
   > не додумывай.

4. Render a draft from `<DEVFLOW_DIR>/AGENTS.md.template` into
   `<scratchpad>/AGENTS-<name>.md`: frontmatter `project: <name>`,
   `vault: /mnt/f/notes_2/projects/<name>`; each fact goes into its section with a trailing
   `<!-- источник: file -->`; unknown facts keep the template placeholder. Keep the template's
   Workflow and Notes sections verbatim.
5. Show the draft and the list of `неизвестно` items. Wait for confirmation; apply requested edits
   to the draft file, not the target directory. Nothing is written to `<path>` before this point.
6. Run `devflow project init <path> --name <name> [--agents-draft <draft>]` and print the table.
   `WorkflowError` (name already registered, draft names another project) → show it, do not retry
   with another name silently.
7. Finish with: `To activate: exit Claude Code and run ./start.sh <name>.`

Re-running `init` is safe: everything present comes back `skipped`, files are not rewritten.

## Command: `sync [name…|--all]`

1. Without arguments ask: one project or `--all`.
2. `devflow project sync <names|--all> --dry-run` → table. `sync` never touches `AGENTS.md` or
   the registry; a missing `AGENTS.md`, a name mismatch, identity without database or a vanished
   directory come back as `attention` — route those to `init` or a manual fix.
3. If any item is `create`, ask for confirmation, then rerun without `--dry-run` and print the
   final table. All `skipped` → say so and stop.

## Command: `list`

Read the registry, print `| Active | Name | Path |` with `*` on the active entry.

## Command: `info [name]`

Default name = `active`. Show path, description, and — if `AGENTS.md` exists — `project`, `vault`
from its frontmatter plus the first 5 lines of the body. Missing `AGENTS.md` → suggest `init`.

## Command: `remove <name>`

Stop if `<name>` is absent. Delete the entry from `projects.json`; if it was `active`, set
`active: null`. Confirm `✓ Removed: <name> (files were not deleted)`. No CLI command yet — this
is the one place the skill edits the registry directly.

## Errors

- **Project not found** — list near matches by substring.
- **Path doesn't exist** — print the path; ask the user to check.
- **Registry corrupt** — back up to `projects.json.bak.<ts>`, ask how to recover.

## Notes

- Switching the active project stays outside this skill: `./start.sh <name>` relaunches Claude Code
  in the chosen directory so the global SessionStart hook reads the right `AGENTS.md`.
- The hook and publication rules live in the global `~/.claude/settings.json`
  (`settings.global.example.json`, checked by `./install.sh --check`) — `init` does not write them.
