---
name: note
description: Obsidian vault integration - save, read, search notes per project
user_invocable: true
arguments:
  - name: command
    description: "Command: save, read, search, tz, contract, list"
    required: true
  - name: args
    description: "Title, query, or folder depending on command"
    required: false
---

# /note - Obsidian Vault Integration

Integrates with Obsidian vault for saving development notes, reading specs (TZ), and searching project knowledge.

**IMPORTANT: All notes MUST be written in Russian.** Titles, content, tags — everything in the note file itself is in Russian. Only filenames remain in transliterated latin (for filesystem compatibility). When auto-populating from `/explore` or `/investigate` output (which may be in English), translate the content to Russian before saving.

## Usage

```
/note save <title>              # Save a note to projects/<active>/
/note read <title>              # Read a note (fuzzy match by name)
/note search <query>            # Search note contents
/note tz <title>                # Read TZ spec and route to workflow
/note contract <branch>         # Read feature contract by branch name
/note list [folder]             # List notes for current project
```

## Instructions

You are the Obsidian vault integration handler. Follow these steps based on the command.

### Phase 0: Config (all commands)

1. Read `.claude/data/projects.json` — get `active` project name and `obsidian_vault` path
2. Set vault base: `<obsidian_vault>/projects/<active_project>/`
3. If `obsidian_vault` is not set, report error and stop:
   ```
   Obsidian vault not configured. Add "obsidian_vault" to .claude/data/projects.json
   ```
4. If vault base dir doesn't exist yet, that's OK — commands like `save` will create it

---

### Command: `save <title>`

Save a note to the project's vault folder.

**Step 1: Determine category**

Ask the user which category (unless obvious from context):

```
AskUserQuestion:
  question: "Which category for this note?"
  options:
    - label: "research"
      description: "Exploration results, investigation findings, analysis"
    - label: "decisions"
      description: "Architecture decisions, approach choices, ADRs"
    - label: "tz"
      description: "Technical specification / task description"
    - label: "contracts"
      description: "Feature contract (API, DTO, Events, DB schemas)"
```

**Auto-detection rules** (skip asking if clear):
- If called right after `/explore` or `/investigate` — default to `research`
- If the user explicitly says "TZ" or "spec" — default to `tz`
- If the user explicitly says "decision" or "ADR" — default to `decisions`
- If called right after `/develop` Phase 2 (plan) or `/plan` — default to `contracts`
- If the user explicitly says "contract" or "контракт" — default to `contracts`

**Step 2: Determine content**

- If called right after `/explore` — use the exploration report as content
- If called right after `/investigate` — use the investigation report as content
- Otherwise — ask the user what to write, or accept content they provide

**Step 3: Generate frontmatter and write**

Generate the note with YAML frontmatter:

```markdown
---
created: YYYY-MM-DD
project: <active_project>
type: <category>
tags: [<тэги на русском>]
---

# <Заголовок на русском>

<содержание на русском>
```

**For `contracts` category**, use extended frontmatter:

```markdown
---
created: YYYY-MM-DD
project: <active_project>
type: contract
branch: <branch_name>
status: draft
tags: [контракт, <domain tags на русском>]
---
```

The `status` field tracks the contract lifecycle:
- `draft` — just generated, awaiting user review
- `approved` — user reviewed and confirmed
- `implemented` — code matches the contract

Tags auto-detection:
- Extract key domain terms from the title and content
- Include the project name
- Keep to 3-5 tags max
- **Tags must be in Russian** (e.g., `аналитика`, `авторизация`, `расчёты`)

**Language rule:** The entire note content (title, body, tags) MUST be in Russian. If the source material is in English (e.g., output from `/explore`), translate it to Russian before writing.

**Step 4: Write the file**

```
Path: <vault_base>/<category>/<title>.md
```

- Create intermediate directories if they don't exist (use Bash `mkdir -p`)
- Sanitize title for filename: replace spaces with `-`, remove special chars, lowercase
- If file already exists, ask user: overwrite or pick a new name?

**Step 5: Confirm**

```markdown
## Saved: <title>

**Path:** <full_path>
**Category:** <category>
**Tags:** <tags>

The note is now available in Obsidian under `projects/<project>/<category>/`.
```

---

### Command: `read <title>`

Read a note by title with fuzzy matching.

**Step 1: Search for the note**

Search in this order (stop at first match):

1. **Exact match** in `<vault_base>/` — Glob for `**/<title>.md`
2. **Fuzzy match** in `<vault_base>/` — Glob for `**/*<title>*.md` (case-insensitive via Bash `find -iname`)
3. **Cross-project search** in `<obsidian_vault>/projects/` — same patterns
4. **Full vault search** in `<obsidian_vault>/` — same patterns

If multiple matches found, present a list and ask the user to pick:

```markdown
## Multiple notes found for "<title>"

1. `projects/my-app/research/credit-analytics.md`
2. `projects/my-app/tz/credit-analytics-spec.md`
3. `projects/my-api/research/analytics-overview.md`

Which one?
```

**Step 2: Read and display**

Read the file and display its contents. If it has YAML frontmatter, parse and show metadata:

```markdown
## <Title>

**Project:** my-app | **Type:** research | **Created:** 2026-01-15
**Tags:** analytics, credits, reporting

---

<note content>
```

---

### Command: `search <query>`

Search note contents by keyword or phrase.

**Step 1: Search current project**

Use Grep to search in `<vault_base>/`:
```
Grep(pattern: "<query>", path: "<vault_base>/", glob: "*.md", output_mode: "content", -C: 2)
```

**Step 2: Display results**

```markdown
## Search results for "<query>" in <project>

### projects/<project>/research/credit-analytics.md
> ...matching line with **context**...

### projects/<project>/tz/settlement-spec.md
> ...matching line with **context**...

**Found N matches in M files.**
```

If no results in current project, offer to expand:

```
AskUserQuestion:
  question: "No results in <project>. Search all projects or full vault?"
  options:
    - label: "All projects"
      description: "Search in all project folders"
    - label: "Full vault"
      description: "Search entire Obsidian vault"
    - label: "Cancel"
      description: "Stop searching"
```

---

### Command: `tz <title>`

Read a TZ (technical specification) and route it to a development workflow.

**Step 1: Find and read the TZ**

Search in `<vault_base>/tz/` first:
1. Glob for `<vault_base>/tz/<title>.md` (exact)
2. Glob for `<vault_base>/tz/*<title>*.md` (fuzzy)
3. If not in `tz/`, fall back to full `read` logic

If not found:
```markdown
## TZ not found: <title>

No spec found in `projects/<project>/tz/`.

Available TZ files:
<list files in tz/ folder>

Or create one with: `/note save <title>` (category: tz)
```

**Step 2: Display the TZ**

Read and display the full TZ content (same as `read` command).

**Step 2.5: Normalize to Standard Task Format**

Before routing, parse the TZ into the standardized task format:

1. Extract `title` from the first `#` heading in the TZ
2. Extract `description` from the full note content (minus frontmatter)
3. Extract `acceptance_criteria`:
   - Look for `- [ ]` checklist items anywhere in the TZ
   - Also look for a `## Критерии приёмки` section
   - Combine both sources, deduplicate
4. Set `source: "obsidian"` and `source_ref: "<tz_file_path>"`

Store as `standardized_task` and pass to the chosen workflow in Step 3.

**Step 3: Route to workflow**

After displaying, ask the user:

```
AskUserQuestion:
  question: "How would you like to proceed with this TZ?"
  options:
    - label: "/develop"
      description: "Start autonomous development from this TZ"
    - label: "/plan"
      description: "Create a detailed plan first"
    - label: "/explore"
      description: "Explore approaches before committing"
    - label: "Just read"
      description: "No action needed, just wanted to read it"
```

If user chooses a workflow, invoke the chosen skill with the standardized task and full TZ content:

```
Skill(skill: "<chosen>", args: "<standardized_task JSON>\n\n---\n\n<Full TZ content>")
```

**Important:** When passing to a skill, include both the standardized task (for structured acceptance criteria) and the full TZ text (for full context). Summarize only if the TZ exceeds ~3000 words.

---

### Command: `contract <branch>`

Read a feature contract by branch name. Designed for the C-DAD (Contract-Driven AI Development) workflow.

**Step 1: Find the contract**

Search in `<vault_base>/contracts/` first:
1. Glob for `<vault_base>/contracts/<branch>*.md` (prefix match — branch name is always the start of filename)
2. Glob for `<vault_base>/contracts/*<branch>*.md` (fuzzy)
3. If not in `contracts/`, fall back to full `read` logic

If not found:
```markdown
## Contract not found: <branch>

No contract found in `projects/<project>/contracts/`.

Available contracts:
<list files in contracts/ folder>

Contracts are auto-generated during `/develop` Phase 2.5.
Or create one manually with: `/note save <title>` (category: contracts)
```

**Step 2: Display the contract**

Read and display the full contract content. Parse frontmatter to show metadata:

```markdown
## Contract: <Title>

**Project:** <project> | **Branch:** <branch> | **Status:** <status>
**Created:** <date> | **Tags:** <tags>

---

<contract content>
```

**Step 3: Route to workflow**

After displaying, ask the user:

```
AskUserQuestion:
  question: "What would you like to do with this contract?"
  options:
    - label: "/develop"
      description: "Start development using this contract"
    - label: "Edit"
      description: "I'll edit it in Obsidian first, then continue"
    - label: "Approve"
      description: "Mark contract as approved (update status)"
    - label: "Just read"
      description: "No action needed"
```

If user chooses:
- `/develop` — invoke `/develop` with the contract content as context
- `Edit` — print the Obsidian file path and wait for user to come back
- `Approve` — update the frontmatter `status: draft` → `status: approved` in the file, confirm to user
- `Just read` — done

---

### Command: `list [folder]`

List notes for the current project.

**Step 1: Determine scope**

- If `folder` is specified (e.g., `tz`, `research`, `decisions`): list only that subfolder
- If no folder: list all subfolders with file counts, then files

**Step 2: List files**

If listing all (no folder specified):

First, check if the project directory exists. If not:
```markdown
## Notes for <project>

No notes yet. Project folder will be created on first `/note save`.

**Expected structure:**
```
projects/<project>/
  tz/          # Technical specifications
  research/    # Research & exploration results
  decisions/   # Architecture decisions
  contracts/   # Feature contracts (C-DAD)
```

Create a note with: `/note save <title>`
```

If directory exists, use Glob to find all `.md` files and display:

```markdown
## Notes for <project>

| Folder | File | Created |
|--------|------|---------|
| tz | settlement-spec.md | 2026-01-15 |
| tz | auth-flow.md | 2026-01-20 |
| research | credit-analytics.md | 2026-01-18 |
| decisions | event-sourcing.md | 2026-01-22 |

**Total:** N notes (X tz, Y research, Z decisions, W contracts)
```

Parse the `created` date from YAML frontmatter if available, otherwise use file modification time.

If listing a specific folder:

```markdown
## <project> / <folder>

| File | Created | Tags |
|------|---------|------|
| settlement-spec.md | 2026-01-15 | settlements, billing |
| auth-flow.md | 2026-01-20 | auth, jwt |

**Total:** N notes
```

---

## Filename Sanitization

When converting titles to filenames:
- Lowercase
- Replace spaces with hyphens (`-`)
- Remove special characters except hyphens and dots
- Collapse multiple hyphens into one
- Trim leading/trailing hyphens
- Max length: 100 characters

Examples:
- `Credit Analytics Research` → `credit-analytics-research.md`
- `DEV-488: Settlement Flow` → `dev-488-settlement-flow.md`
- `How to implement auth?` → `how-to-implement-auth.md`

---

## Error Handling

**Vault not accessible:**
```markdown
## Cannot access vault

Path `<obsidian_vault>` is not accessible. Check if the drive is mounted.

On WSL, ensure the Windows drive is mounted:
```bash
ls /mnt/d/
```
```

**Project not set:**
```markdown
## No active project

Set an active project first:
```
/project switch <name>
```
```

---

## Examples

### Save exploration results
```
User: /note save Credit settlement analytics
Bot: Which category? → research
Bot: [generates note from recent /explore output]
Bot: Saved: credit-settlement-analytics.md
     Path: /path/to/obsidian-vault/projects/my-project/research/credit-settlement-analytics.md
```

### Read a TZ and start development
```
User: /note tz auth-flow
Bot: [displays TZ content]
Bot: How would you like to proceed?
User: /develop
Bot: [invokes /develop with TZ content]
```

### Search across notes
```
User: /note search settlement
Bot: Found 3 matches in 2 files:
     - projects/my-app/tz/settlement-spec.md (2 matches)
     - projects/my-app/research/credit-analytics.md (1 match)
```

### Read a contract and start development
```
User: /note contract DEV-510
Bot: [displays contract content with frontmatter]
Bot: What would you like to do with this contract?
User: /develop
Bot: [invokes /develop with contract content as context]
```

### List project notes
```
User: /note list
Bot: Notes for my-app:
     | Folder | File | Created |
     | tz | settlement-spec.md | 2026-01-15 |
     | research | credit-analytics.md | 2026-01-18 |
     | contracts | dev-510-user-auth.md | 2026-02-11 |
     Total: 3 notes
```
