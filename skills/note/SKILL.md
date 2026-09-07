---
name: note
description: Read, write, and search notes in the project's obsidian vault. Vault layout is tz/ research/ plans/ changelog/ notes/.
user_invocable: true
arguments:
  - name: command
    description: "save | read | search | list | tz"
    required: true
  - name: args
    description: "Title, query, slug, or folder — depends on command"
    required: false
---

# /note — Obsidian vault integration

Manages project notes outside the workflow skills (`/research`, `/plan`, `/implement` write their own files). Use `/note` for ad-hoc reading, search, and saving general notes.

**All note content (titles, body, tags) MUST be in Russian.** Filenames stay latin (kebab-case).

## Step 0: Read project context (every command)

1. Read `AGENTS.md` from cwd. Parse YAML frontmatter — extract `project` and `vault`.
2. If missing or no `vault` field — stop and tell the user to create `AGENTS.md` from the template.
3. Vault base = the `vault` value (e.g. `/mnt/f/notes_2/projects/devflow`).

Vault layout:
```
<vault>/
  tz/         # task specs — durable contracts (see the tz command)
  research/   # /research output
  plans/      # /plan output
  changelog/  # /implement output
  notes/      # ad-hoc notes (patterns, rules, decisions)
```

---

## Command: `save <title>`

Save an ad-hoc note to the vault.

1. **Determine category.** Ask the user (default: `notes`):
   - `tz` — task spec; scaffold it from `references/tz-template.md` instead of a bare note
   - `notes` — patterns, rules, decisions, anything reusable
   - (research/plans/changelog are normally written by skills — only allow if user insists)
2. **Determine content.** Either user-provided text, or content from current conversation (e.g. summary of a discussion).
3. **Slugify the title** for the filename (rules below).
4. **Generate frontmatter:**
   ```yaml
   ---
   created: YYYY-MM-DD
   project: <project>
   type: <category>
   tags: [<3-5 русских тегов>]
   ---
   ```
5. **Write** to `<vault>/<category>/<slug>.md`. Create the directory if missing.
6. If file exists — ask: overwrite, append, or pick a new slug.
7. Confirm with the path.

---

## Command: `read <title>`

Read a note by fuzzy match.

1. Glob in `<vault>/` for `**/<title>.md` (exact), then `**/*<title>*.md` (fuzzy, case-insensitive).
2. If multiple matches — list them and ask which one.
3. Read and display the file. Show frontmatter as a header line if present.

If not found, list available files in each subfolder and suggest `/note save`.

---

## Command: `search <query>`

Grep note contents.

1. Use `Grep` on `<vault>/` with `glob: "*.md"`, `output_mode: "content"`, `-C 2`.
2. Display matches grouped by file, with line context.
3. If zero results, ask whether to expand to the parent project folder or full vault.

---

## Command: `list [folder]`

List notes in the project vault.

- No folder: show counts per subfolder + a flat table of files (path, created, tags).
- Folder specified (`tz`, `research`, `plans`, `changelog`, `notes`): list only that folder, with frontmatter summary.

If the vault directory doesn't exist yet, say so and suggest `/note save` to bootstrap.

---

## Command: `tz <slug>` | `tz new <slug>`

Read or create a task spec. A TZ is a **durable contract** — it outlives the code it describes, so
it is checked against a fixed shape rather than read as free-form prose.

### `tz new <slug>`

1. Read `references/tz-template.md` (ships next to this file).
2. Fill the frontmatter — `created` today, `project` from `AGENTS.md`, `task` = the slug prefix
   upper-cased, `status: draft` — and write `<vault>/tz/<slug>.md`. If it exists, stop and say so.
3. Show the path and the section list. Leave the sections as placeholders; do **not** invent content
   the user has not given.

### `tz <slug>`

1. Look in `<vault>/tz/`: exact `<slug>.md`, then fuzzy `*<slug>*.md`. Not found — list `tz/`, stop.
2. Display the contents.
3. **Check the contract** and print a verdict under the doc:

| Check | Rule |
|---|---|
| Sections | All six present: `Суть`, `Текущее поведение`, `Желаемое поведение`, `Ключевые интерфейсы`, `Критерии приёмки`, `Вне объёма` |
| `Вне объёма` | Present **and non-empty** — an empty one means the TZ is not ready |
| Interfaces | The `Ключевые интерфейсы` section holds no file paths and no line numbers — grep it for `src/`, `.php:`, `.ts:`, `:<digits>`. A hit is a violation: rewrite the entry as a contract (signature, invariants, error modes). This ban is **specific to `tz/`** — plans name paths on purpose |
| Criteria | Each `Критерии приёмки` item is verifiable on its own. One that cannot be checked without opening another is a defect of the TZ — name it |

Verdict: `ТЗ готово` or `ТЗ не готово: <what is missing>`. A failing TZ is a **draft** — say so
plainly and name the fix; never hand it to `plan` as if it were settled.

TZ written before this shape will fail the check. That is the check working. Report it; don't
rewrite an old spec unless the user asks.

---

## Filename rules

Slugify: lowercase, spaces → `-`, drop non-alnum except `-` and `.`, collapse repeats, trim, max 100 chars.

Examples:
- `Credit Analytics Research` → `credit-analytics-research.md`
- `DEV-488: Settlement Flow` → `dev-488-settlement-flow.md`

---

## Errors

- **Vault path not accessible** (e.g. WSL drive not mounted): print the path and suggest `ls <vault>` to check.
- **`AGENTS.md` missing or no vault field:** stop, tell the user to set it up.
