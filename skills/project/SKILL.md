---
name: project
description: Manage the project registry. Lists registered projects, adds new ones, shows info. Switching is done outside Claude Code via start.sh.
user_invocable: true
arguments:
  - name: command
    description: "list | add | info | remove"
    required: true
  - name: target
    description: "Project name or path (depending on command)"
    required: false
---

# /project — Project Registry

Manages a small JSON registry of known projects. Each entry maps a project name to its filesystem path. Vault paths and project metadata live in each project's own `AGENTS.md` — the registry only knows where projects are on disk.

## Registry location

`<DEVFLOW_DIR>/.claude/data/projects.json`

## Schema

```json
{
  "version": "3.0",
  "active": "<project name or null>",
  "projects": {
    "<name>": {
      "path": "/absolute/path",
      "description": "<one line, optional>"
    }
  }
}
```

That's it. No `type`, `repositories`, `testing`, `docker`, `git`, `agent_config`. Anything project-specific belongs in the project's `AGENTS.md`.

---

## Command: (no args) or `/project`

Show current active project + available commands.

```
**Active project:** <name>
**Path:** <path>

Commands: list | add <path> [name] | info [name] | remove <name>
To switch projects: exit Claude Code and run `./start.sh [name]`.
```

---

## Command: `list`

1. Read `projects.json`.
2. Print a table:

```
| Active | Name | Path |
|--------|------|------|
|   *    | devflow  | /home/smg25/projects/devflow |
|        | captivia | /home/smg25/projects/captivia |
```

---

## Command: `add <path> [name]`

1. Validate `<path>` exists (`ls`).
2. If `name` not given — derive from the directory basename.
3. If `<path>/AGENTS.md` exists — parse frontmatter, suggest using `project:` value as the registry name.
4. Ask the user for a one-line `description` (optional).
5. Update `projects.json` — add the entry. Don't change `active`.
6. Confirm:

```
✓ Added: <name>
  Path: <path>
  AGENTS.md: <found | missing — create from AGENTS.md.template>

To activate: exit Claude Code and run `./start.sh <name>`.
```

If `AGENTS.md` is missing, suggest copying from `<DEVFLOW_DIR>/AGENTS.md.template` and filling it in.

---

## Command: `info [name]`

1. If `name` not given — use `active`.
2. Read registry entry for `<name>`.
3. If `<path>/AGENTS.md` exists — read its frontmatter and show key fields.
4. Display:

```
## <name>

**Path:** <path>
**Description:** <description or —>

### From AGENTS.md
**Project:** <project>
**Vault:** <vault>

<first 5 lines of AGENTS.md body>
```

If `AGENTS.md` missing — say so and suggest creating it.

---

## Command: `remove <name>`

1. Read registry. Stop if `<name>` not present.
2. Remove the entry. If it was `active`, set `active: null`.
3. Save. Confirm:

```
✓ Removed: <name> (files were not deleted)
```

---

## Errors

- **Project not found** — list near matches by simple substring.
- **Path doesn't exist** — print the path; ask the user to check.
- **Registry corrupt** — back up `projects.json` to `projects.json.bak.<ts>`, ask user how to recover (re-create empty / restore manually).

---

## Notes

- Switching active project is intentionally outside this skill — `./start.sh <name>` exits and re-launches Claude Code in the chosen directory, so the SessionStart hook reads the right `AGENTS.md`.
- This skill never edits files inside a project — only the central registry.
