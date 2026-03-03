#!/bin/bash
# devflow-status.sh — CLI status display for DevFlow sessions and queue
#
# Usage: ./scripts/devflow-status.sh [subcommand] [args]
#
# Subcommands:
#   (none)       — Full dashboard (active session + queue + recent)
#   session      — Active session only
#   queue        — Queue only
#   recent [N]   — Last N completed sessions (default 5)
#
# Designed for use with: watch -n2 ./scripts/devflow-status.sh
#
# No external dependencies — bash + Python 3 standard library only.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$SCRIPT_DIR")"
SESSIONS_FILE="$DEVFLOW_DIR/.claude/data/sessions.json"
QUEUE_FILE="$DEVFLOW_DIR/.claude/data/queue.json"

SUBCOMMAND="${1:-all}"
ARG2="${2:-}"

python3 - "$SESSIONS_FILE" "$QUEUE_FILE" "$SUBCOMMAND" "$ARG2" <<'PYEOF'
import json
import sys
from datetime import datetime, timezone

sessions_file = sys.argv[1]
queue_file = sys.argv[2]
subcommand = sys.argv[3]
arg2 = sys.argv[4]

# ── ANSI colors ──────────────────────────────────────────────────────────────

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
CYAN = "\033[36m"

# ── Phase definitions (inlined from models.py) ───────────────────────────────

PHASE_ORDER = [
    "phase_0_config",
    "phase_1_branch",
    "phase_1.5_trace",
    "phase_2_plan",
    "phase_2.5_contract",
    "phase_2.7_test_first",
    "phase_3_implement",
    "phase_3.5_test_isolation",
    "phase_4_validate",
    "phase_5_e2e",
    "phase_6_commit",
    "phase_6.5_test_reaction",
    "phase_7_review",
    "phase_8_fix",
    "phase_9_summary",
]

DISPLAY_PHASES = [
    "phase_0_config",
    "phase_1_branch",
    "phase_1.5_trace",
    "phase_2_plan",
    "phase_2.5_contract",
    "phase_3_implement",
    "phase_4_validate",
    "phase_5_e2e",
    "phase_7_review",
    "phase_9_summary",
]

PHASE_LABELS = {
    "phase_0_config": "Config",
    "phase_1_branch": "Branch",
    "phase_1.5_trace": "Trace",
    "phase_2_plan": "Plan",
    "phase_2.5_contract": "Contract",
    "phase_2.7_test_first": "Test-First",
    "phase_3_implement": "Implement",
    "phase_3.5_test_isolation": "Test-Iso",
    "phase_4_validate": "Validate",
    "phase_5_e2e": "E2E",
    "phase_6_commit": "Commit",
    "phase_6.5_test_reaction": "Test-React",
    "phase_7_review": "Review",
    "phase_8_fix": "Fix",
    "phase_9_summary": "Summary",
    "phase_10_summary": "Summary",  # legacy alias
}


def phase_label(phase):
    """Get display label for a phase, stripping prefix for unknown phases."""
    if phase in PHASE_LABELS:
        return PHASE_LABELS[phase]
    # Strip phase_N_ prefix for unknown phases
    import re
    m = re.match(r"phase_[\d.]+_(.+)", phase)
    return m.group(1).capitalize() if m else phase

STATUS_ICONS = {
    "completed": "\u2705",
    "running": "\u23f3",
    "failed": "\u274c",
    "interrupted": "\u26a0\ufe0f",
    "pending": "\u2b1c",
    "review_ready": "\u2705",
    "skipped": "\u23e9",
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def parse_ts(value):
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def duration_display(started_at, updated_at):
    s = parse_ts(started_at)
    if not s:
        return "-"
    e = parse_ts(updated_at) or datetime.now(timezone.utc)
    secs = int((e - s).total_seconds())
    if secs < 60:
        return "< 1m"
    minutes = secs // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h {mins}m"


def progress_info(completed_phases, current_phase):
    done = len([p for p in completed_phases if p in PHASE_ORDER])
    total = len(PHASE_ORDER)
    # Find current phase index for display
    try:
        current_idx = PHASE_ORDER.index(current_phase) + 1
    except ValueError:
        current_idx = done
    pct = int(done / total * 100) if total > 0 else 0
    return current_idx, total, pct


def progress_bar(pct, width=15):
    filled = int(pct / 100 * width)
    return "\u2593" * filled + "\u2591" * (width - filled)


def phase_line(completed_phases, current_phase, phase_history):
    """Build compact phase status line using DISPLAY_PHASES."""
    skipped_phases = set()
    if phase_history:
        for entry in phase_history:
            if isinstance(entry, dict) and entry.get("result") == "skipped":
                skipped_phases.add(entry.get("phase", ""))

    parts = []
    for phase in DISPLAY_PHASES:
        label = phase_label(phase)
        if phase in completed_phases:
            if phase in skipped_phases:
                parts.append(f"{DIM}{label}{RESET}")
            else:
                parts.append(f"{GREEN}{label}{RESET}")
        elif phase == current_phase:
            parts.append(f"{YELLOW}{BOLD}{label} \u25b6{RESET}")
        else:
            parts.append(f"{DIM}{label}{RESET}")
    return " ".join(parts)


def loop_count(loops):
    if not loops or not isinstance(loops, dict):
        return 0
    total = 0
    for loop_data in loops.values():
        if isinstance(loop_data, dict):
            total += loop_data.get("attempt", 0)
    return total


def load_sessions():
    try:
        with open(sessions_file) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"sessions": {}}


def load_queue():
    try:
        with open(queue_file) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"queue": []}


def header(title):
    line = "\u2500" * (50 - len(title) - 3)
    return f"{DIM}\u2500\u2500 {RESET}{BOLD}{title}{RESET} {DIM}{line}{RESET}"


# ── Renderers ────────────────────────────────────────────────────────────────

def render_session():
    data = load_sessions()
    sessions = data.get("sessions", {})

    print(header("Active Session"))

    # Find active (running) session
    active = None
    for key, sess in sessions.items():
        if sess.get("status") == "running":
            active = (key, sess)
            break

    if not active:
        print(f"  {DIM}No active session{RESET}")
        return

    key, sess = active
    icon = STATUS_ICONS.get(sess.get("status", ""), "\u2753")
    skill = sess.get("skill", "?")
    feature = sess.get("feature", key)
    completed = sess.get("completed_phases", [])
    current = sess.get("current_phase", "")
    dur = duration_display(sess.get("started_at"), sess.get("updated_at"))
    loops = loop_count(sess.get("loops"))
    branch = sess.get("branches", {}).get("work", key)
    phase_hist = sess.get("phase_history", [])

    idx, total, pct = progress_info(completed, current)
    current_label = phase_label(current)

    print(f"  {icon} /{skill}  {feature}")
    print(f"  Phase: {current_label} ({idx}/{total})  |  Duration: {dur}  |  Loops: {loops}")
    print(f"  Branch: {CYAN}{branch}{RESET}")
    print(f"  {progress_bar(pct)}  {pct}%")
    print(f"  {phase_line(completed, current, phase_hist)}")


def render_queue():
    data = load_queue()
    items = data.get("queue", [])

    print(header("Queue"))

    if not items:
        print(f"  {DIM}Queue is empty{RESET}")
        return

    total = len(items)
    completed = sum(1 for i in items if i.get("status") == "completed")
    failed = sum(1 for i in items if i.get("status") == "failed")

    # Progress bar
    bar_width = 30
    filled = int(completed / total * bar_width) if total > 0 else 0
    bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
    summary = f"{completed}/{total}"
    if failed:
        summary += f"  {RED}{failed} failed{RESET}"
    print(f"  {bar}  {summary}")

    # Background run status
    bg = data.get("background_run")
    if bg and bg.get("status") == "running":
        bg_dur = duration_display(bg.get("started_at"), None)
        print(f"  {YELLOW}Background run active{RESET} ({bg_dur})")

    # Items list
    for item in items:
        icon = STATUS_ICONS.get(item.get("status", ""), "\u2753")
        skill = item.get("skill", "?")
        desc = item.get("args", "").split("\n")[0][:40].strip()
        status = item.get("status", "pending")

        suffix = ""
        if status == "running":
            suffix = f" {YELLOW}\u25b6{RESET}"
        elif status == "failed":
            suffix = f" {RED}{item.get('error', '')[:30]}{RESET}"

        iid = item.get("id", "?")
        print(f"  {icon} #{iid:<3} /{skill:<10} {desc}{suffix}")


def render_recent(n=5):
    data = load_sessions()
    sessions = data.get("sessions", {})

    print(header("Recent Sessions"))

    # Collect non-running sessions, sort by updated_at descending
    recent = []
    for key, sess in sessions.items():
        if sess.get("status") in ("running",):
            continue
        updated = parse_ts(sess.get("updated_at"))
        recent.append((key, sess, updated))

    recent.sort(key=lambda x: x[2] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    recent = recent[:n]

    if not recent:
        print(f"  {DIM}No recent sessions{RESET}")
        return

    for key, sess, _ in recent:
        icon = STATUS_ICONS.get(sess.get("status", ""), "\u2753")
        skill = sess.get("skill", "?")
        feature = sess.get("feature", key)
        # Truncate feature
        if len(feature) > 45:
            feature = feature[:42] + "..."
        dur = duration_display(sess.get("started_at"), sess.get("updated_at"))
        branch = sess.get("branches", {}).get("work", key)
        print(f"  {icon} {branch:<16} /{skill:<10} {feature}  {DIM}{dur}{RESET}")


# ── Main ─────────────────────────────────────────────────────────────────────

if subcommand == "session":
    render_session()
elif subcommand == "queue":
    render_queue()
elif subcommand == "recent":
    n = int(arg2) if arg2 else 5
    render_recent(n)
else:
    # Full dashboard
    render_session()
    print()
    render_queue()
    print()
    render_recent()
PYEOF
