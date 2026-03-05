---
name: project
description: Manage project registry (list, add, info, remove, agents)
user_invocable: true
arguments:
  - name: command
    description: "Command: list, add, info, remove, agents"
    required: true
  - name: target
    description: "Project name or path (for add/remove/info)"
    required: false
---

# /project - Project Registry Management

Manages the project registry. To **switch** between projects, exit Claude Code and use `./start.sh` — it shows an interactive menu and launches Claude with the selected project.

## Usage

```
/project list                    # List all registered projects
/project add <path> [name]       # Register a new project
/project info [name]             # Show project details (default: active)
/project remove <name>           # Remove project from registry
/project agents                  # Generate project-specific agents for active project
```

## Instructions

You are the orchestrator for project registry management. Follow the steps for each command below.

---

### Command: (no command) or just `/project`

If `/project` is called without arguments, show current project info and available commands:

```markdown
**Active project:** <name> (<type>)
**Path:** <path>

Available commands:
- `/project list` — list all registered projects
- `/project add <path>` — register a new project
- `/project info` — detailed info about current project
- `/project remove <name>` — unregister a project
- `/project agents` — generate project-specific agents

To switch projects, exit and run `./start.sh`
```

---

### Command: `list`

1. Read `.claude/data/projects.json`
2. Display all registered projects in a table:

```markdown
## Registered Projects

| Name | Type | Path | Serena | Docker |
|------|------|------|--------|--------|
| my-app | fullstack | /home/user/projects/acme/my-app | my-app | start/stop |
| my-api | fullstack | /home/user/projects/acme/my-api | my-api | start/stop |
| my-frontend | fullstack | /home/user/projects/my-frontend | my-frontend | - |

**Active:** my-app
```

---

### Command: `add <path> [name]`

1. Validate the path exists using Bash `ls`
2. If name not provided, derive from directory name
3. Detect project structure:
   - Check for separate `frontend/` and `backend/` directories → fullstack
   - Check for `package.json` → typescript/javascript
   - Check for `composer.json` → php
   - Check for `Cargo.toml` → rust
   - Check for `go.mod` → go
   - Check for `.claude/CLAUDE.md` → has orchestrator config
   - Otherwise → single
4. Detect repositories:
   - If fullstack: Look for git repos in backend/ and frontend/
   - If single: Use the main path
   - Store in `repositories` field
5. Check if project is registered in Serena (use `mcp__serena__get_current_config`)
6. Ask user for E2E testing configuration (optional)
7. Add to projects.json (v2.0 format):

```json
{
  "name": {
    "path": "/full/path",
    "type": "fullstack|single",
    "description": "Auto-detected or user-provided",
    "serena_project": "name-if-in-serena or null",
    "created": "YYYY-MM-DD",
    "tags": [],
    "repositories": {
      "backend": "/full/path/backend",
      "frontend": "/full/path/frontend"
    },
    "testing": {
      "backend": {
        "type": "api",
        "base_url": "http://localhost:8000",
        "commands": {
          "unit": "cd {{repo}} && ./vendor/bin/phpunit",
          "e2e": "curl -s {{base_url}}/api/health | jq ."
        }
      },
      "frontend": {
        "type": "browser",
        "base_url": "http://localhost:3000",
        "commands": {
          "unit": "cd {{repo}} && npm test",
          "e2e": "cd {{repo}} && npx playwright test"
        }
      }
    }
  }
}
```

8. Confirm:

```markdown
## Project Added: my-app

**Path:** /home/user/projects/my-app
**Type:** fullstack

**Repositories:**
- backend: /home/user/projects/my-app/backend
- frontend: /home/user/projects/my-app/frontend

**Testing:**
- Backend API: curl at http://localhost:8000
- Frontend UI: Playwright at http://localhost:3000

**Serena:** registered as 'my-app'

To switch to it, exit and run: `./start.sh my-app`
```

---

### Command: `info [name]`

1. If name not provided, use active project
2. Read projects.json to get project metadata
3. Read project's `.claude/CLAUDE.md` if exists
4. If Serena project, list available memories
5. Display comprehensive info:

```markdown
## Project: my-frontend

**Path:** /home/user/projects/my-frontend
**Type:** typescript
**Serena Project:** my-frontend
**Created:** 2025-01-20
**Tags:** electron, desktop

### Description
Electron-based desktop application...

### Docker
- Start: `make dc.up-d`
- Stop: `make dc.down`

### Serena Memories
- architecture.md
- conventions.md

### Recent Activity
[If tasks.json exists in project]
```

---

### Command: `remove <name>`

1. Read projects.json
2. Find and remove the project entry
3. If it was the active project, set active to null
4. Save projects.json
5. Note: This only removes from registry, doesn't delete files

```markdown
## Removed: old-project

Project removed from registry. Files were not deleted.
```

---

### Command: `agents`

Generate project-specific agents for the active project. Analyzes the codebase and creates customized agent files in `<project>/.claude/agents/`.

**Step 1: Get active project**

1. Read `.claude/data/projects.json` — get `active` project, its `path` and `type`
2. If no active project, show error and stop

**Step 2: Check existing agents**

1. Check if `<project_path>/.claude/agents/` already exists
2. If it does and contains `.md` files, show what exists and ask:

```
AskUserQuestion:
  question: "Project already has agents. What to do?"
  options:
    - label: "Regenerate all"
      description: "Delete existing and create from scratch"
    - label: "Add missing"
      description: "Only create agents that don't exist yet"
    - label: "Cancel"
      description: "Keep existing agents"
```

**Step 3: Analyze the project**

Gather information from these sources (read only what exists):

1. **Project config** — `<project_path>/.claude/CLAUDE.md`, `<project_path>/.claude/patterns.md`
2. **Dependencies** — `package.json`, `composer.json`, `Cargo.toml`, `go.mod`, `requirements.txt`
3. **Directory structure** — `ls` of project root and key directories (`src/`, `app/`, `lib/`, `tests/`, `test/`)
4. **Serena memories** — if Serena project is active, read all available memories (overview, conventions, decisions)
5. **Sample code** — read 2-3 representative files of each type found in the project:
   - Entry points (controllers, providers, processors, route handlers, API endpoints)
   - Business logic (services, handlers, use cases, commands, queries)
   - Data access (repositories, DAOs, models, entities)
   - Tests (pick one unit and one integration/functional test)
   - Frontend components (if fullstack project)
6. **Git history** — `git -C <project_path> log --oneline -20` for commit style
7. **Test infrastructure** — how tests run (npm test, phpunit, docker exec, etc.)

Compile a project profile:

```
Stack: [languages, frameworks, versions]
Architecture: [DDD, MVC, Clean Architecture, Hexagonal, ...]
Patterns: [CQRS, Event Sourcing, Repository, State, ...]
Testing: [framework, test style, docker/local, helpers]
API Style: [REST, GraphQL, API Platform, ...]
Code Style: [naming conventions, formatting, typing]
```

Display the profile and ask for confirmation before generating:

```
AskUserQuestion:
  question: "Profile correct? Proceed with agent generation?"
  options:
    - label: "Yes, generate"
      description: "Create agents based on this profile"
    - label: "Adjust"
      description: "I'll correct the profile first"
```

**Step 4: Determine which agents to create**

Based on the profile, decide which agents are needed:

| Condition | Agent File | When to create |
|-----------|-----------|----------------|
| PHP project (single language) | `developer.md` | Always |
| JS/TS project (single language) | `developer.md` | Always |
| Fullstack (PHP + JS) | `php-developer.md` + `js-developer.md` | Always (both) |
| Non-standard test infrastructure | `tester.md` | Custom TestCase, InMemory repos, docker tests, special fixtures/builders |
| Strict layered architecture | `architecture-guardian.md` | DDD, Clean Architecture, explicit layer boundaries, import rules |
| Domain-specific review rules | `reviewer.md` | Specific security patterns, mandatory annotations, forbidden cross-module deps |

**Minimum** — always create at least `developer.md` (or language-specific variants for fullstack).
Others — only if the analysis reveals project-specific rules beyond what universal templates already cover.

**Step 5: Generate agent files**

Read the universal templates first to know what NOT to duplicate:
- `.claude/agents/templates/developer.template.md`
- `.claude/agents/templates/tester.template.md` (if creating tester)
- `.claude/agents/templates/architecture-guardian.template.md` (if creating guardian)
- `.claude/agents/templates/reviewer.template.md` (if creating reviewer)

**Generation rules:**

1. **Concrete, not abstract** — use real code examples from the project, not generic patterns
2. **Patterns, not documentation** — show HOW to write code, not WHAT the system does
3. **CORRECT vs WRONG** — for critical rules, always show the anti-pattern
4. **Compact** — max 150 lines per agent. Cut the obvious
5. **Don't duplicate templates** — test quality rules, OWASP checklist, AAA pattern are already in templates
6. **Use captivia agent as structural reference** — follow the same section structure:

```markdown
# <Project> <Language> Developer

You are a <language> developer specialized in this project. Follow these patterns precisely.

## Stack
- Concrete versions: language, framework, ORM, database, tooling

## Architecture: <pattern name>
- Directory tree structure
- Layer rules (what depends on what, what's forbidden)

## <Key Pattern 1> (e.g., CQRS, Repository, State Machine)
- CONCRETE code example from the project (or matching its style)
- Correct annotations, naming, structure

## <Key Pattern 2> (e.g., Event Bus, Message Queue)
- CRITICAL rules highlighted with **CRITICAL** marker
- CORRECT vs WRONG examples

## Naming Conventions
- Table: Type | Pattern | Example
- Real examples from the project

## Code Style
- Only project-specific rules (not standard language conventions)

## Testing
- Test runner command
- Test patterns (base TestCase, helpers, mocking approach)
- Special infrastructure (InMemory repos, builders, fixtures)

## <Domain-specific rules>
- Migration rules, validation rules, etc. — only if project has specifics
```

**Step 6: Write files**

1. Create `<project_path>/.claude/agents/` directory if it doesn't exist (use `mkdir -p`)
2. Write each agent file
3. Verify each agent is resolvable:

```bash
./scripts/resolve-agent.sh "<project_path>" "<agent_type>"
```

Run this for each created agent to confirm `resolve-agent.sh` finds it.

**Step 7: Display summary**

```markdown
## Project Agents Created

**Project:** <name>
**Path:** <project_path>/.claude/agents/

| Agent | File | Lines | Key Focus |
|-------|------|-------|-----------|
| PHP Developer | developer.md | 120 | Symfony DDD, CQRS, API Platform |
| Tester | tester.md | 80 | FunctionalTestCase, InMemory repos |

**Skipped** (covered by universal templates):
- Architecture Guardian — no project-specific rules beyond patterns.md
- Reviewer — no domain-specific review rules

These agents will be automatically loaded by `/develop`, `/fix`, and `/refactor` when working on this project.
```

---

## Data File Location

**Registry:** `.claude/data/projects.json`

Structure (v2.0):
```json
{
  "version": "2.0",
  "projects": {
    "project-name": {
      "path": "/absolute/path",
      "type": "fullstack|single",
      "description": "Project description",
      "serena_project": "serena-name or null",
      "created": "YYYY-MM-DD",
      "tags": ["tag1", "tag2"],
      "docker": {
        "start": "make -C /path/to/project dc.up-d",
        "stop": "make -C /path/to/project dc.down"
      },
      "repositories": {
        "main": "/path/to/single-repo",
        "backend": "/path/to/backend",
        "frontend": "/path/to/frontend"
      },
      "testing": { ... }
    }
  },
  "active": "project-name or null"
}
```

---

## Error Handling

**Project not found:**
```markdown
## Project not found: foo

Did you mean one of these?
- foo-bar
- foobar

Or add a new project: `/project add /path/to/foo`
```

**Path doesn't exist:**
```markdown
## Path not found

The path `/home/user/projects/nonexistent` doesn't exist.
Please check the path and try again.
```

---

## Examples

### Register a new project
```
User: /project add /home/user/projects/my-frontend
Bot: Project Added: my-frontend (fullstack)
     To switch: exit and run ./start.sh my-frontend
```

### List all projects
```
User: /project list
Bot: Registered Projects

     | Name | Type | Active |
     |------|------|--------|
     | my-frontend | fullstack | |
     | my-app | fullstack | * |
     | my-api | fullstack | |
```

### Get detailed info
```
User: /project info
Bot: Project: my-app

     Path: /home/user/projects/acme/my-app
     Type: fullstack
     ...
```
