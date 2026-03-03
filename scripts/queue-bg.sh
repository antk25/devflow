#!/bin/bash
# queue-bg.sh — Background queue execution via tmux
#
# Usage: ./scripts/queue-bg.sh <subcommand> [args]
#
# Subcommands:
#   start "<claude_prompt>"  — Launch queue in detached tmux session
#   stop                     — Kill active background run
#   status                   — Show current background run status and queue summary
#
# Requirements:
#   - tmux must be installed
#   - .claude/data/queue.json must exist
#
# tmux session name: devflow-queue (hardcoded)
#
# Exit codes:
#   0 = success
#   1 = error (missing args, tmux not found, no pending items, etc.)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$SCRIPT_DIR")"
QUEUE_FILE="$DEVFLOW_DIR/.claude/data/queue.json"
TMUX_SESSION="devflow-queue"

SUBCOMMAND="${1:-}"

if [ -z "$SUBCOMMAND" ]; then
    echo "ERROR: Subcommand required: start, stop, status" >&2
    echo "HINT: Usage: ./scripts/queue-bg.sh <start|stop|status> [args]" >&2
    exit 1
fi

if [ ! -f "$QUEUE_FILE" ]; then
    echo "ERROR: queue.json not found at $QUEUE_FILE" >&2
    echo "HINT: Initialize queue first via /queue command" >&2
    exit 1
fi

# ─── start ────────────────────────────────────────────────────────────────────

cmd_start() {
    local PROMPT="${1:-}"

    if [ -z "$PROMPT" ]; then
        echo "ERROR: Prompt argument is required for 'start'" >&2
        echo "HINT: Usage: ./scripts/queue-bg.sh start \"<claude_prompt>\"" >&2
        exit 1
    fi

    # 1. Check tmux is available
    if ! command -v tmux &>/dev/null; then
        echo "ERROR: tmux is required for background queue execution. Install: sudo apt install tmux" >&2
        exit 1
    fi

    # 2. Check if a background run is already active
    python3 - "$QUEUE_FILE" "$TMUX_SESSION" <<'PYEOF'
import json, sys

queue_file = sys.argv[1]
tmux_session = sys.argv[2]

with open(queue_file) as f:
    data = json.load(f)

bg = data.get("background_run", {})
status = bg.get("status", "")

if status == "running":
    print(f'ERROR: Background run already active (started {bg.get("started_at", "unknown")}). Use \'/queue stop\' to cancel or \'/queue status\' to check progress.')
    sys.exit(1)
PYEOF

    # Also verify no live tmux session exists
    if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
        echo "ERROR: Background run already active. Use '/queue stop' to cancel or '/queue status' to check progress." >&2
        exit 1
    fi

    # 3. Count pending items
    PENDING_COUNT=$(python3 - "$QUEUE_FILE" <<'PYEOF'
import json, sys

with open(sys.argv[1]) as f:
    data = json.load(f)

pending = [item for item in data.get("queue", []) if item.get("status") == "pending"]
print(len(pending))
PYEOF
)

    if [ "$PENDING_COUNT" -eq 0 ]; then
        echo "ERROR: No pending tasks in queue." >&2
        exit 1
    fi

    # 4. Create detached tmux session
    #    Use printf %q for safe shell escaping of the prompt
    #    Launch claude in interactive mode with initial prompt (-p is print mode)
    #    Set working directory to DEVFLOW_DIR for correct project context
    ESCAPED_PROMPT=$(printf '%q' "$PROMPT")
    tmux new-session -d -s "$TMUX_SESSION" -c "$DEVFLOW_DIR" \
        "claude $ESCAPED_PROMPT"

    # 5. Update queue.json with background_run metadata
    python3 - "$QUEUE_FILE" "$TMUX_SESSION" <<'PYEOF'
import json, sys
from datetime import datetime, timezone

queue_file = sys.argv[1]
tmux_session = sys.argv[2]

with open(queue_file) as f:
    data = json.load(f)

data["background_run"] = {
    "tmux_session": tmux_session,
    "started_at": datetime.now(timezone.utc).isoformat(),
    "status": "running"
}

with open(queue_file, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
PYEOF

    echo "Background queue started."
    echo "  Session : $TMUX_SESSION"
    echo "  Pending : $PENDING_COUNT task(s)"
    echo "  Attach  : tmux attach -t $TMUX_SESSION"
    echo "  Monitor : ./scripts/queue-bg.sh status"
}

# ─── stop ─────────────────────────────────────────────────────────────────────

cmd_stop() {
    # 1. Check queue.json for active run (use || true to prevent set -e from killing script)
    if ! python3 - "$QUEUE_FILE" <<'PYEOF'
import json, sys

with open(sys.argv[1]) as f:
    data = json.load(f)

bg = data.get("background_run", {})
if bg.get("status") != "running":
    print("No active background run.")
    sys.exit(1)
PYEOF
    then
        exit 0
    fi

    # 2. Kill tmux session (best-effort)
    tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true

    # 3. Update queue.json: mark stopped + reset any running items to pending
    python3 - "$QUEUE_FILE" <<'PYEOF'
import json, sys
from datetime import datetime, timezone

with open(sys.argv[1]) as f:
    data = json.load(f)

bg = data.get("background_run", {})
bg["status"] = "stopped"
bg["stopped_at"] = datetime.now(timezone.utc).isoformat()
data["background_run"] = bg

# Reset any running queue items to pending (they were interrupted)
for item in data.get("queue", []):
    if item.get("status") == "running":
        item["status"] = "pending"
        item["started_at"] = None

with open(sys.argv[1], "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
PYEOF

    echo "Background run stopped."
    echo "  Session '$TMUX_SESSION' has been terminated."
    echo "  Any running tasks reset to pending."
}

# ─── status ───────────────────────────────────────────────────────────────────

cmd_status() {
    python3 - "$QUEUE_FILE" "$TMUX_SESSION" <<'PYEOF'
import json, sys, subprocess
from datetime import datetime, timezone

queue_file = sys.argv[1]
tmux_session = sys.argv[2]

with open(queue_file) as f:
    data = json.load(f)

bg = data.get("background_run", {})
status = bg.get("status", "")

if not bg or status not in ("running", "stopped", "completed"):
    print("No background run recorded.")
    sys.exit(0)

if status == "completed":
    print(f"Last background run: completed at {bg.get('stopped_at', bg.get('started_at', 'unknown'))}")
    sys.exit(0)

if status == "stopped":
    print(f"No active background run. (Last run: stopped at {bg.get('stopped_at', 'unknown')})")
    sys.exit(0)

# status == "running" — verify tmux session is actually alive
tmux_alive = subprocess.run(
    ["tmux", "has-session", "-t", tmux_session],
    capture_output=True
).returncode == 0

if not tmux_alive:
    # Orphan cleanup: session died but status still says running
    bg["status"] = "stopped"
    bg["stopped_at"] = datetime.now(timezone.utc).isoformat()
    data["background_run"] = bg
    with open(queue_file, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("WARNING: tmux session no longer exists (process may have finished or crashed).")
    print("  Status updated to: stopped")
    sys.exit(0)

# Count items by status
queue = data.get("queue", [])
counts = {}
for item in queue:
    s = item.get("status", "unknown")
    counts[s] = counts.get(s, 0) + 1

started_at = bg.get("started_at", "unknown")

print("Background run: ACTIVE")
print(f"  Session  : {tmux_session}")
print(f"  Started  : {started_at}")
print(f"  Attach   : tmux attach -t {tmux_session}")
print("")
print("Queue summary:")
for label, key in [("Pending", "pending"), ("Running", "running"), ("Completed", "completed"), ("Failed", "failed"), ("Skipped", "skipped")]:
    n = counts.get(key, 0)
    if n > 0:
        print(f"  {label:<12}: {n}")
total = len(queue)
print(f"  {'Total':<12}: {total}")
PYEOF
}

# ─── dispatch ─────────────────────────────────────────────────────────────────

case "$SUBCOMMAND" in
    start)
        shift
        cmd_start "${1:-}"
        ;;
    stop)
        cmd_stop
        ;;
    status)
        cmd_status
        ;;
    *)
        echo "ERROR: Unknown subcommand: $SUBCOMMAND" >&2
        echo "HINT: Valid subcommands: start, stop, status" >&2
        exit 1
        ;;
esac
