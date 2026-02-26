---
name: recall
description: Search and recall past session logs
user_invocable: true
arguments:
  - name: query
    description: Search query or "list" to show recent sessions
    required: true
---

# /recall - Session Memory Recall

Search through past session summaries to recall what was done, decisions made, and problems solved.

## Usage

```
/recall list                         # Show recent sessions
/recall фильтр отчётов               # Search for sessions about report filters
/recall authentication implementation # Find sessions about auth
/recall list --project captivia      # List sessions for specific project
```

## Instructions

You are the session memory recall assistant. Help the user find and review past session logs.

### Step 1: Determine the action

Parse the user's query:
- If query is `list` or starts with `list` → list recent sessions
- Otherwise → search through session summaries

### Step 2: Execute

**For listing:**

```bash
python3 "$CLAUDE_PROJECT_DIR/scripts/session-log.py" list [--project <name>]
```

**For searching:**

```bash
python3 "$CLAUDE_PROJECT_DIR/scripts/session-log.py" search "<query>" [--project <name>] [--limit 10]
```

### Step 3: Present results

After running the command, present the results to the user in a readable format.

If the user wants more details about a specific session:
1. Read the full summary file using the Read tool
2. If the user needs the raw transcript, check `~/.claude/sessions-log/<project>/raw/` for snapshots

### Step 4: Optional — load into context

If the user says "load this" or "use this context", read the full summary file and present it so Claude can use it in the current conversation.

## Examples

### List recent sessions
```
> /recall list
Recent sessions for devflow:
| 2026-02-25 14:30 | implement report filters | completed | ... |
| 2026-02-25 10:15 | fix login bug           | completed | ... |
```

### Search for context
```
> /recall authentication
Found 3 matching sessions:
1. 2026-02-20 — Implement JWT auth (relevance: 3)
2. 2026-02-18 — Fix token refresh (relevance: 2)
3. 2026-02-15 — Explore auth approaches (relevance: 1)
```

## Notes

- Session logs are stored at `~/.claude/sessions-log/<project>/`
- Summaries are auto-generated at session end via SessionEnd hook
- Raw transcripts are saved before compaction via PreCompact hook
- Summaries are created by Claude Haiku for cost efficiency
