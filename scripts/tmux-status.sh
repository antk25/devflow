#!/bin/bash
# tmux-status.sh — Compact one-line status for tmux status bar
#
# Output examples:
#   Active session:        ⏳ /develop Implement 47% [Q:2/5]
#   No session, queue:     [Q:2/5 ⏳]
#   No session, no queue:  DevFlow ✓
#   Session failed:        ❌ /fix Failed
#
# tmux integration:
#   set -g status-right '#(~/projects/devflow/scripts/tmux-status.sh) | %H:%M'
#   set -g status-interval 5
#
# No ANSI colors — tmux handles styling via #[fg=...].

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$SCRIPT_DIR")"
SESSIONS_FILE="$DEVFLOW_DIR/.claude/data/sessions.json"
QUEUE_FILE="$DEVFLOW_DIR/.claude/data/queue.json"

python3 - "$SESSIONS_FILE" "$QUEUE_FILE" <<'PYEOF'
import json
import sys

sessions_file = sys.argv[1]
queue_file = sys.argv[2]

PHASE_ORDER = [
    "phase_0_config", "phase_1_branch", "phase_1.5_trace",
    "phase_2_plan", "phase_2.5_contract", "phase_2.7_test_first",
    "phase_3_implement", "phase_3.5_test_isolation", "phase_4_validate",
    "phase_5_e2e", "phase_6_commit", "phase_6.5_test_reaction",
    "phase_7_review", "phase_8_fix", "phase_9_summary",
]

PHASE_LABELS = {
    "phase_0_config": "Config", "phase_1_branch": "Branch",
    "phase_1.5_trace": "Trace", "phase_2_plan": "Plan",
    "phase_2.5_contract": "Contract", "phase_2.7_test_first": "Test-First",
    "phase_3_implement": "Implement", "phase_3.5_test_isolation": "Test-Iso",
    "phase_4_validate": "Validate", "phase_5_e2e": "E2E",
    "phase_6_commit": "Commit", "phase_6.5_test_reaction": "Test-React",
    "phase_7_review": "Review", "phase_8_fix": "Fix",
    "phase_9_summary": "Summary", "phase_10_summary": "Summary",
}

def phase_label(phase):
    if phase in PHASE_LABELS:
        return PHASE_LABELS[phase]
    import re
    m = re.match(r"phase_[\d.]+_(.+)", phase)
    return m.group(1).capitalize() if m else phase

STATUS_ICONS = {
    "completed": "\u2705", "running": "\u23f3", "failed": "\u274c",
    "interrupted": "\u26a0\ufe0f", "review_ready": "\u2705",
}

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Load data
sessions_data = load_json(sessions_file)
queue_data = load_json(queue_file)

# Find active session
active = None
for key, sess in sessions_data.get("sessions", {}).items():
    if sess.get("status") == "running":
        active = sess
        break

# Queue summary
items = queue_data.get("queue", [])
q_total = len(items)
q_done = sum(1 for i in items if i.get("status") == "completed")
q_running = any(i.get("status") == "running" for i in items)
bg = queue_data.get("background_run")
bg_active = bg and bg.get("status") == "running"

parts = []

if active:
    status = active.get("status", "")
    icon = STATUS_ICONS.get(status, "\u2753")
    skill = active.get("skill", "?")
    current = active.get("current_phase", "")
    completed = active.get("completed_phases", [])

    plabel = phase_label(current)
    done_count = len([p for p in completed if p in PHASE_ORDER])
    pct = int(done_count / len(PHASE_ORDER) * 100) if PHASE_ORDER else 0

    if status == "failed":
        parts.append(f"{icon} /{skill} Failed")
    elif status == "interrupted":
        parts.append(f"{icon} /{skill} Interrupted")
    else:
        parts.append(f"{icon} /{skill} {plabel} {pct}%")

# Queue part
if q_total > 0:
    q_icon = " \u23f3" if (q_running or bg_active) else ""
    q_str = f"[Q:{q_done}/{q_total}{q_icon}]"
    parts.append(q_str)

if not parts:
    print("DevFlow \u2713")
else:
    print(" ".join(parts))
PYEOF
