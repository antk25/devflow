---
name: project
description: Manage project registry (list, add, info, remove)
user_invocable: true
arguments:
  - name: command
    description: "Command: list, add, info, remove"
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
