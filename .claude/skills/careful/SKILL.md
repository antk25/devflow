---
name: careful
description: Activate/deactivate careful mode — blocks destructive commands (rm -rf, DROP TABLE, docker rm, kubectl delete). Use when working near production or sensitive data.
user_invocable: true
arguments:
  - name: action
    description: "on (default) or off"
    required: false
---

# /careful - Dangerous Command Guard

Activates careful mode for the current project session. While active, the auto-approve hook blocks destructive commands and requires manual confirmation.

## Usage

```
/careful          # Activate careful mode (default: on)
/careful on       # Same as above
/careful off      # Deactivate careful mode
```

## What it blocks

When careful mode is active, these commands require manual approval instead of auto-approve:

- `rm -rf` — recursive forced deletion
- `rm -r` — recursive deletion
- `DROP TABLE`, `DROP DATABASE`, `TRUNCATE`, `DELETE FROM` — destructive SQL
- `kubectl delete` — Kubernetes resource deletion
- `docker rm`, `docker rmi`, `docker system prune` — Docker cleanup
- `git reset --hard` — discard uncommitted changes
- `git checkout -- .` — discard all file changes
- `git clean` — remove untracked files
- `chmod 777` — overly permissive permissions
- `kill -9` — force kill processes
- `:>` or `> file` — file truncation patterns

## How it works

1. `/careful on` creates `.claude/data/careful-mode.json` with blocked patterns
2. The existing `auto-approve.sh` hook checks for this file on every tool call
3. If a blocked pattern is matched, the hook exits without approving — Claude Code prompts the user
4. `/careful off` removes the flag file

No session restart needed — takes effect immediately on the next tool call.

## Instructions

Parse the action argument (default: "on").

### If action is "on":

1. Write the careful-mode flag file:

```bash
cat > "<project_path>/.claude/data/careful-mode.json" << 'EOF'
{
  "enabled": true,
  "activated_at": "<ISO8601 timestamp>",
  "blocked_patterns": [
    "rm -rf", "rm -r ",
    "DROP TABLE", "DROP DATABASE", "TRUNCATE ", "DELETE FROM",
    "kubectl delete",
    "docker rm", "docker rmi", "docker system prune",
    "git reset --hard", "git checkout -- ", "git clean",
    "chmod 777", "kill -9"
  ]
}
EOF
```

2. Output confirmation:
```
Careful mode ON

Blocked commands now require manual approval:
  rm -rf, DROP TABLE, kubectl delete, docker rm,
  git reset --hard, git clean, chmod 777, kill -9

Deactivate with: /careful off
```

### If action is "off":

1. Remove the flag file:
```bash
rm -f "<project_path>/.claude/data/careful-mode.json"
```

2. Output confirmation:
```
Careful mode OFF — all commands auto-approved as usual.
```
