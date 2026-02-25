---
name: queue
description: Batch task queue for current project
user_invocable: true
arguments:
  - name: command
    description: "Command: add, list, run, remove, clear, status"
    required: true
  - name: args
    description: "Arguments for the command (task spec, item IDs, flags)"
    required: false
---

# /queue - Batch Task Queue

Plan a batch of tasks for the current project and execute them sequentially. Tasks are stored in `queue.json` and executed one by one. Each item invokes an existing skill (`/develop`, `/fix`, `/refactor`, etc.).

All tasks run within the **current active project** (set via `./start.sh` before launching Claude Code).

## Usage

```
/queue add develop Add dark mode
/queue add fix Login timeout
/queue list
/queue list --all
/queue run
/queue run 3                              # resume from item #3
/queue remove 2
/queue remove 2 3 5
/queue clear
/queue clear --all
/queue status
```

## Instructions

You are the batch task queue manager. Follow the steps for each command below.

---

### Command: `add`

Add a task to the queue.

**Syntax:**
```
/queue add <skill> <description>
```

**Steps:**

1. Read `.claude/data/queue.json` (create with empty schema if missing):
   ```json
   {
     "version": "1.0",
     "queue": [],
     "last_run": null,
     "next_id": 1
   }
   ```

2. Read `.claude/data/projects.json` to get the active project name.

3. Parse the arguments:
   - Format: `<skill> <description>` — uses active project

4. Validate:
   - **Skill** must be one of: `develop`, `fix`, `refactor`, `investigate`, `review`, `plan`, `implement`. If not found:
     ```
     ## Unknown skill: deploy

     Valid skills: develop, fix, refactor, investigate, review, plan, implement
     ```

5. Create queue item:
   ```json
   {
     "id": "<next_id>",
     "project": "<active_project>",
     "skill": "<skill>",
     "args": "<description>",
     "status": "pending",
     "added_at": "<ISO 8601 timestamp>",
     "started_at": null,
     "completed_at": null,
     "result": null,
     "branch": null,
     "error": null
   }
   ```

6. Increment `next_id` and write `queue.json`.

7. Display confirmation:
   ```
   Added #N: /skill description
   ```

---

### Command: `list`

Show the queue.

**Syntax:**
```
/queue list              # pending only
/queue list --all        # include completed/failed/skipped
```

**Steps:**

1. Read `.claude/data/queue.json`
2. Group items into attention zones:
   - **Needs Attention** — `failed` items needing human decision
   - **Ready** — `pending` items
   - **Running** — `running` items (visible during `/queue run` only)
   - **Done** — `completed` and `skipped` items (hidden by default, shown with `--all`)
3. Display zone-based table:

```markdown
## Task Queue

### Needs Attention (1)
| # | Skill | Description | Error |
|---|-------|-------------|-------|
| 3 | /refactor | Auth service | Architecture validation timeout |

### Ready (2)
| # | Skill | Description |
|---|-------|-------------|
| 1 | /develop | Add dark mode |
| 4 | /fix | Login timeout |

### Done (4)
_Use `/queue list --all` to expand_
```

With `--all`, expand the Done zone to show all completed/skipped items with their branches.

If queue is empty:
```
Queue is empty. Add tasks with `/queue add`
```

---

### Command: `run`

Execute all pending tasks sequentially.

**Syntax:**
```
/queue run               # run all pending
/queue run <id>          # resume from specific item
```

**Steps:**

1. Read `.claude/data/queue.json`

2. **Reset stale items:** Any items with `status: "running"` (left over from interrupted run) — reset to `status: "pending"`.

3. Filter pending items, ordered by `id`. If a specific ID is given, start from that ID (skip earlier items).

4. If no pending items:
   ```
   No pending tasks in queue.
   ```
   Exit.

5. Display start message:
   ```
   ## Running queue: N tasks

   | # | Skill | Description |
   |---|-------|-------------|
   | 1 | /develop | Add dark mode |
   | 2 | /fix | Login timeout |

   Starting...
   ```

6. **For each pending item** (ordered by id):

   a. Display: `### Running #N: /skill description`

   b. **Update status:**
      - Set `item.status = "running"`, `item.started_at = <now>`
      - Write `queue.json`

   c. **Execute skill:**
      - Use the `Skill` tool: `Skill(skill: item.skill, args: item.args)`
      - This delegates the entire execution to the existing skill's workflow

   d. **On success:**
      - Set `item.status = "completed"`, `item.completed_at = <now>`
      - Set `item.result = "completed"` (or a brief summary if available)
      - Try to detect branch name from the skill output and store in `item.branch`
      - Write `queue.json`
      - Display: `#N completed`

   e. **On failure/error:**
      - Set `item.status = "failed"`, `item.completed_at = <now>`
      - Set `item.error = <error description>`
      - Write `queue.json`
      - Display: `#N failed: <error>`
      - **Continue to next item** — failed items do NOT block the queue

7. **Update `last_run`:**
   ```json
   {
     "started_at": "<timestamp>",
     "completed_at": "<timestamp>",
     "total": 5,
     "completed": 4,
     "failed": 1,
     "skipped": 0
   }
   ```
   Write `queue.json`.

8. **Desktop notification:**
   ```bash
   # If all succeeded:
   ./scripts/notify.sh "Queue Complete" "N/M tasks done"
   # If any failed:
   ./scripts/notify.sh "Queue Complete" "N/M done, F failed" critical
   ```

9. **Display summary:**
   ```markdown
   ## Queue Run Complete

   | # | Skill | Status | Branch |
   |---|-------|--------|--------|
   | 1 | /develop | completed | feature/dark-mode |
   | 2 | /fix | completed | fix/login-timeout |
   | 3 | /refactor | failed | - |

   **Results:** 2 completed, 1 failed, 0 skipped

   ### Failed Items
   - #3: Error description here
   ```

---

### Command: `remove`

Remove items from the queue.

**Syntax:**
```
/queue remove <id>
/queue remove <id1> <id2> <id3>
```

**Steps:**

1. Read `.claude/data/queue.json`
2. Parse IDs from arguments (space-separated numbers)
3. For each ID:
   - Find item in queue
   - If not found: warn `Item #N not found`
   - If found: remove from queue array
4. Write `queue.json`
5. Display: `Removed N item(s) from queue`

---

### Command: `clear`

Clear the queue.

**Syntax:**
```
/queue clear             # clear pending only
/queue clear --all       # clear everything
```

**Steps:**

1. Read `.claude/data/queue.json`
2. If `--all`: set `queue` to empty array `[]`
3. If no flag: remove only items with `status: "pending"`
4. Write `queue.json`
5. Display:
   ```
   Cleared N items from queue
   ```

---

### Command: `status`

Show the last run results and current queue state.

**Syntax:**
```
/queue status
```

**Steps:**

1. Read `.claude/data/queue.json`
2. Display `last_run` info (if exists), then current queue in zone-based format:

```markdown
## Queue Status

### Last Run
- **Started:** 2026-01-30 08:00
- **Completed:** 2026-01-30 09:45
- **Results:** 4 completed, 1 failed, 0 skipped (5 total)

### Current Queue

#### Needs Attention (1)
| # | Skill | Description | Error |
|---|-------|-------------|-------|
| 3 | /refactor | Auth service | Architecture validation timeout |

#### Ready (2)
| # | Skill | Description |
|---|-------|-------------|
| 6 | /develop | Add notifications |
| 7 | /fix | Cache invalidation |

#### Done (4)
_Use `/queue list --all` for details_
```

If no `last_run`:
```
No previous run recorded. Use `/queue run` to execute pending tasks.
```

---

## Data File

**Location:** `.claude/data/queue.json`

**Schema:**
```json
{
  "version": "1.0",
  "queue": [
    {
      "id": 1,
      "project": "my-app",
      "skill": "develop",
      "args": "Add dark mode support",
      "status": "pending",
      "added_at": "2026-01-30T08:00:00Z",
      "started_at": null,
      "completed_at": null,
      "result": null,
      "branch": null,
      "error": null
    }
  ],
  "last_run": {
    "started_at": "2026-01-30T08:00:00Z",
    "completed_at": "2026-01-30T09:45:00Z",
    "total": 5,
    "completed": 4,
    "failed": 1,
    "skipped": 0
  },
  "next_id": 2
}
```

**Status transitions:** `pending` → `running` → `completed` | `failed` | `skipped`

---

## Edge Cases

| Case | Behavior |
|------|----------|
| Invalid skill name | Error message + list valid skills |
| Empty queue on `run` | Display message, exit |
| Failed item during `run` | Mark failed, continue to next |
| Interrupted run | Items left as `running` reset to `pending` on next `run` |
| `queue.json` missing | Create empty file on first `add` or `list` |
| Duplicate tasks | Allowed — user can dedup via `list` + `remove` |
| Run with specific ID | Start from that ID, skip earlier pending items |

---

## Examples

### Plan a batch of work
```
/queue add develop Add dark mode support
/queue add fix Login form validation
/queue add refactor Auth service cleanup
/queue add develop Add export feature
/queue list
/queue run
```

### Check results
```
/queue status
/queue list --all
```

### Clean up
```
/queue remove 3 5          # remove specific items
/queue clear               # clear pending
/queue clear --all         # clear everything
```
