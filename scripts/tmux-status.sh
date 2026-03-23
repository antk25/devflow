#!/bin/bash
# tmux-status.sh — Compact one-line status for tmux status bar
#
# Output examples:
#   Active session:        ⏳ /develop Implement 47%
#   No session:            DevFlow ✓
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

python3 - "$SESSIONS_FILE" <<'PYEOF'
import json
import sys

sessions_file = sys.argv[1]

PHASE_ORDER = [
    "phase_0_config", "phase_1_branch", "phase_1.5_trace",
    "phase_2_plan", "phase_2.5_contract", "phase_2.7_test_first",
    "phase_3_implement", "phase_3.5_test_isolation", "phase_4_validate",
    "phase_5_e2e", "phase_6_commit",
    "phase_7_review", "phase_8_fix", "phase_9_summary",
]

PHASE_LABELS = {
    "phase_0_config": "Config", "phase_1_branch": "Branch",
    "phase_1.5_trace": "Trace", "phase_2_plan": "Plan",
    "phase_2.5_contract": "Contract", "phase_2.7_test_first": "Test-First",
    "phase_3_implement": "Implement", "phase_3.5_test_isolation": "Test-Iso",
    "phase_4_validate": "Validate", "phase_5_e2e": "E2E",
    "phase_6_commit": "Commit+Test",
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

# Find active session
active = None
for key, sess in sessions_data.get("sessions", {}).items():
    if sess.get("status") == "running":
        active = sess
        break

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
        print(f"{icon} /{skill} Failed")
    elif status == "interrupted":
        print(f"{icon} /{skill} Interrupted")
    else:
        print(f"{icon} /{skill} {plabel} {pct}%")
else:
    print("DevFlow \u2713")
PYEOF
