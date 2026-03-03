---
name: queue
description: Batch task queue for current project
user_invocable: true
arguments:
  - name: command
    description: "Command: add, list, run, run --background, stop, remove, clear, status, report"
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
/queue run --background                   # run in detached tmux session
/queue stop                               # stop background run
/queue status                             # show progress + background info
/queue report                             # show last morning report
/queue report --save                      # save report to Obsidian
/queue report --last                      # show last saved report from Obsidian
/queue remove 2
/queue remove 2 3 5
/queue clear
/queue clear --all
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
     "background_run": null,
     "last_report": null,
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
/queue run               # run all pending (foreground)
/queue run <id>          # resume from specific item
/queue run --background  # run in detached tmux session
```

**If `--background` flag is present:** jump to the [run --background](#command-run---background) section below.

**Steps (foreground):**

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
      - **Notify:** `./scripts/notify.sh "Queue: #N done" "/skill description" normal`

   e. **On failure/error:**
      - Set `item.status = "failed"`, `item.completed_at = <now>`
      - Set `item.error = <error description>`
      - Write `queue.json`
      - Display: `#N failed: <error>`
      - **Notify:** `./scripts/notify.sh "Queue: #N FAILED" "/skill description: <error>" critical`
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

8. **Final desktop notification:**
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

10. **Generate morning report:**
    ```bash
    ./scripts/queue-report.sh
    ```
    Display the report output inline after the summary.

    If `background_run.status == "running"` in `queue.json` (this is a background session), also auto-save:
    ```bash
    ./scripts/queue-report.sh --save
    ```
    After auto-save, update `background_run.status = "completed"` in `queue.json`.

---

### Command: `run --background`

Run the queue in a detached tmux session. The queue executes autonomously while you continue working.

**Syntax:**
```
/queue run --background
```

**Steps:**

1. Read `.claude/data/queue.json`

2. **Check for active background run:**
   - Read `background_run` from `queue.json`
   - If `background_run.status == "running"`:
     - Verify tmux session exists: `tmux has-session -t devflow-queue 2>/dev/null`
     - If exists: display error:
       ```
       Background run already active (started <started_at>).

       Options:
         tmux attach -t devflow-queue    # watch progress
         /queue status                    # check progress
         /queue stop                      # stop the run
       ```
       Exit.
     - If tmux session dead: orphan cleanup — update `background_run.status = "stopped"`, continue

3. Count pending items. If zero:
   ```
   No pending tasks in queue.
   ```
   Exit.

4. **Launch background session:**
   ```bash
   ./scripts/queue-bg.sh start "Run /queue run. After completion, the morning report will be auto-generated."
   ```

5. **Display confirmation:**
   ```markdown
   ## Queue launched in background (N tasks)

   **Monitoring:**
   - `tmux attach -t devflow-queue` — watch live progress
   - `/queue status` — check current progress
   - `/queue stop` — stop the run

   Notifications will appear after each task.
   Morning report will be auto-saved on completion.
   ```

**Note:** The background Claude session inherits the user's permission settings from `~/.claude/settings.json`. If permissions are not pre-configured for autonomous operation, the session may block waiting for approval. Ensure your settings allow the required tool permissions before launching a background run.

---

### Command: `stop`

Stop an active background queue run.

**Syntax:**
```
/queue stop
```

**Steps:**

1. Read `.claude/data/queue.json`

2. Check `background_run.status`:
   - If not `"running"`: display `No active background run.` and exit.

3. **Stop the background session:**
   ```bash
   ./scripts/queue-bg.sh stop
   ```

4. **Display confirmation:**
   ```
   Background run stopped.

   Current task (if running) was interrupted.
   Remaining pending tasks are unchanged — run `/queue run` to resume.
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

Show the last run results, background run info, and current queue state.

**Syntax:**
```
/queue status
```

**Steps:**

1. Read `.claude/data/queue.json`

2. **Check for active background run:**
   - If `background_run.status == "running"`:
     - Verify tmux session alive: `tmux has-session -t devflow-queue 2>/dev/null`
     - If alive, display background info zone:
       ```markdown
       ### Background Run (active)
       - **Session:** devflow-queue (`tmux attach -t devflow-queue`)
       - **Started:** <started_at>
       - **Progress:** X completed, Y failed, Z pending (N total)
       ```
       Count items by status from `queue` array to compute progress.
     - If tmux dead: orphan cleanup — update `background_run.status = "stopped"`, show warning:
       ```
       Background run ended (tmux session no longer active).
       ```

3. Display `last_run` info (if exists):
   ```markdown
   ### Last Run
   - **Started:** 2026-01-30 08:00
   - **Completed:** 2026-01-30 09:45
   - **Results:** 4 completed, 1 failed, 0 skipped (5 total)
   ```

4. Display current queue in zone-based format:
   ```markdown
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

### Command: `report`

Show or save the morning report from the last queue run.

**Syntax:**
```
/queue report              # show last generated report
/queue report --save       # generate and save to Obsidian vault
```

**Steps:**

1. **`/queue report` (no flags):**
   ```bash
   ./scripts/queue-report.sh
   ```
   Display the script output. If no `last_run` data exists, the script will report an error.

2. **`/queue report --save`:**
   ```bash
   ./scripts/queue-report.sh --save
   ```
   The script saves to `<obsidian_vault>/projects/<active_project>/reports/queue-report-YYYY-MM-DD-HHMM.md`.
   Display the save confirmation path.

   If Obsidian vault is not configured in `projects.json`, the script exits with a warning (non-fatal).

3. **`/queue report --last`:**
   ```bash
   ./scripts/queue-report.sh --last
   ```
   Display the last saved report (from `last_report.saved_to` in `queue.json`).

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
  "background_run": {
    "tmux_session": "devflow-queue",
    "started_at": "2026-01-30T02:00:00Z",
    "status": "running",
    "stopped_at": null
  },
  "last_report": {
    "generated_at": "2026-01-30T10:30:00Z",
    "saved_to": "/path/to/obsidian/projects/my-app/reports/queue-report-2026-01-30-0800.md"
  },
  "next_id": 2
}
```

**Status transitions:** `pending` → `running` → `completed` | `failed` | `skipped`

**Background run status:** `running` → `completed` | `stopped`

---

## Edge Cases

| Case | Behavior |
|------|----------|
| Invalid skill name | Error message + list valid skills |
| Empty queue on `run` | Display message, exit |
| Failed item during `run` | Mark failed, notify (critical), continue to next |
| Interrupted run | Items left as `running` reset to `pending` on next `run` |
| `queue.json` missing | Create empty file on first `add` or `list` |
| Duplicate tasks | Allowed — user can dedup via `list` + `remove` |
| Run with specific ID | Start from that ID, skip earlier pending items |
| tmux not installed | `queue-bg.sh` exits with error: "tmux is required..." |
| Background run already active | Error with hints (attach/status/stop) |
| tmux session died (orphan) | `status` and `run --background` detect and cleanup stale state |
| Obsidian vault not configured | `report --save` warns and exits 0 (non-fatal) |
| No last_run data | `report` shows error, suggests running queue first |
| `report` during active run | Shows partial results based on current queue.json state |

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

### Run overnight
```
/queue run --background
# ... next morning:
/queue report
```

### Monitor background run
```
/queue status                        # quick check
tmux attach -t devflow-queue         # watch live
/queue stop                          # cancel if needed
```

### Check results
```
/queue status
/queue report
/queue report --save                 # persist to Obsidian
/queue list --all
```

### Clean up
```
/queue remove 3 5          # remove specific items
/queue clear               # clear pending
/queue clear --all         # clear everything
```
