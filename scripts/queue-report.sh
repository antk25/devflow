#!/bin/bash
# queue-report.sh — Generates morning reports from queue run results
#
# Usage:
#   ./scripts/queue-report.sh              # Generate and display report from last run
#   ./scripts/queue-report.sh --save       # Generate and save to Obsidian vault
#   ./scripts/queue-report.sh --last       # Display last saved report
#
# Exit codes:
#   0 = success
#   1 = invalid arguments or missing data

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$SCRIPT_DIR")"
QUEUE_FILE="$DEVFLOW_DIR/.claude/data/queue.json"
PROJECTS_FILE="$DEVFLOW_DIR/.claude/data/projects.json"

MODE="${1:-}"

# Validate argument
if [ -n "$MODE" ] && [ "$MODE" != "--save" ] && [ "$MODE" != "--last" ]; then
    echo "ERROR: Unknown argument: $MODE" >&2
    echo "HINT: Usage: ./scripts/queue-report.sh [--save|--last]" >&2
    exit 1
fi

if [ ! -f "$QUEUE_FILE" ]; then
    echo "ERROR: queue.json not found at $QUEUE_FILE" >&2
    echo "HINT: Run a queue first with /queue" >&2
    exit 1
fi

# --last: display last saved report
if [ "$MODE" = "--last" ]; then
    python3 - "$QUEUE_FILE" <<'PYEOF'
import json, sys, os

with open(sys.argv[1]) as f:
    data = json.load(f)

last_report = data.get("last_report")
if not last_report:
    print("No saved reports found.")
    sys.exit(0)

saved_to = last_report.get("saved_to", "")
if not saved_to:
    print("No saved reports found.")
    sys.exit(0)

if not os.path.isfile(saved_to):
    print(f"Report file not found: {saved_to}")
    sys.exit(1)

with open(saved_to) as f:
    print(f.read(), end="")
PYEOF
    exit 0
fi

# Generate report (default or --save)
if [ ! -f "$PROJECTS_FILE" ]; then
    echo "ERROR: projects.json not found at $PROJECTS_FILE" >&2
    echo "HINT: Register a project first with /project add <path>" >&2
    exit 1
fi

python3 - "$QUEUE_FILE" "$PROJECTS_FILE" "$MODE" <<'PYEOF'
import json, sys, os
from datetime import datetime, timezone, timedelta

queue_file = sys.argv[1]
projects_file = sys.argv[2]
mode = sys.argv[3] if len(sys.argv) > 3 else ""

# --- Load data ---
with open(queue_file) as f:
    queue_data = json.load(f)

with open(projects_file) as f:
    projects_data = json.load(f)

last_run = queue_data.get("last_run")
if not last_run:
    print("ERROR: No last_run data found in queue.json", file=sys.stderr)
    print("HINT: Run a queue first with /queue", file=sys.stderr)
    sys.exit(1)

active_project = projects_data.get("active", "")
obsidian_vault = projects_data.get("obsidian_vault", "")

# --- Duration formatting ---
def format_duration(seconds):
    if seconds < 60:
        return "< 1m"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h {mins}m"

# --- Parse timestamps ---
def parse_ts(ts_str):
    if not ts_str:
        return None
    ts_str = ts_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return None

run_started = parse_ts(last_run.get("started_at"))
run_completed = parse_ts(last_run.get("completed_at"))

if not run_started or not run_completed:
    print("ERROR: last_run is missing started_at or completed_at", file=sys.stderr)
    sys.exit(1)

TOLERANCE = timedelta(minutes=1)
window_start = run_started - TOLERANCE
window_end = run_completed + TOLERANCE

# --- Identify items from last run ---
all_items = queue_data.get("queue", [])
run_items = []
for item in all_items:
    completed_at = parse_ts(item.get("completed_at"))
    if completed_at and window_start <= completed_at <= window_end:
        run_items.append(item)

# --- Categorise items ---
succeeded = [i for i in run_items if i.get("status") == "completed" and not i.get("error")]
failed = [i for i in run_items if i.get("status") == "failed" or i.get("error")]
skipped = [i for i in run_items if i.get("status") == "skipped"]

# --- Format dates for report header ---
report_dt = run_started.astimezone()
created_date = report_dt.strftime("%Y-%m-%d")
header_date = report_dt.strftime("%d %b %Y, %H:%M")
started_time = run_started.strftime("%H:%M")
completed_time = run_completed.strftime("%H:%M")

total_seconds = int((run_completed - run_started).total_seconds())
duration_str = format_duration(total_seconds)

total = last_run.get("total", len(run_items))
n_completed = last_run.get("completed", len(succeeded))
n_failed = last_run.get("failed", len(failed))
n_skipped = last_run.get("skipped", len(skipped))

# --- Item duration helper ---
def item_duration(item):
    started = parse_ts(item.get("started_at"))
    completed = parse_ts(item.get("completed_at"))
    if started and completed:
        secs = int((completed - started).total_seconds())
        return format_duration(secs)
    return None

# --- Build report ---
lines = []
lines.append("---")
lines.append(f"created: {created_date}")
lines.append(f"project: {active_project}")
lines.append("type: queue-report")
lines.append("tags: [queue, report]")
lines.append("---")
lines.append("")
lines.append(f"# Queue Report — {header_date}")
lines.append("")
lines.append("## Summary")
lines.append("")
lines.append("| Metric | Value |")
lines.append("|--------|-------|")
lines.append(f"| Started | {started_time} |")
lines.append(f"| Completed | {completed_time} |")
lines.append(f"| Duration | {duration_str} |")
lines.append(f"| Total tasks | {total} |")
lines.append(f"| Succeeded | {n_completed} |")
lines.append(f"| Failed | {n_failed} |")
lines.append(f"| Skipped | {n_skipped} |")
lines.append("")
lines.append("## Results")

# --- Succeeded ---
lines.append("")
lines.append("### Succeeded")
if succeeded:
    for item in succeeded:
        item_id = item.get("id", "?")
        skill = item.get("skill", "?")
        args = item.get("args", "")
        desc = args.split("\n")[0][:80].strip()
        dur = item_duration(item)
        dur_str = f" ({dur})" if dur else ""
        lines.append("")
        lines.append(f"#### #{item_id} /{skill} — {desc}{dur_str}")
        branch = item.get("branch")
        if branch:
            lines.append(f"- **Branch:** `{branch}`")
        result = item.get("result")
        if result and result != "completed":
            lines.append(f"- **Result:** {result}")
else:
    lines.append("")
    lines.append("_No succeeded tasks._")

# --- Failed ---
lines.append("")
lines.append("### Failed")
if failed:
    for item in failed:
        item_id = item.get("id", "?")
        skill = item.get("skill", "?")
        args = item.get("args", "")
        desc = args.split("\n")[0][:80].strip()
        lines.append("")
        lines.append(f"#### #{item_id} /{skill} — {desc}")
        error = item.get("error") or item.get("result", "Unknown error")
        lines.append(f"- **Error:** {error}")
else:
    lines.append("")
    lines.append("_No failed tasks._")

# --- Skipped ---
lines.append("")
lines.append("### Skipped")
if skipped:
    for item in skipped:
        item_id = item.get("id", "?")
        skill = item.get("skill", "?")
        args = item.get("args", "")
        desc = args.split("\n")[0][:80].strip()
        lines.append("")
        lines.append(f"#### #{item_id} /{skill} — {desc}")
        reason = item.get("error") or item.get("result", "No reason provided")
        lines.append(f"- **Reason:** {reason}")
else:
    lines.append("")
    lines.append("_No skipped tasks._")

# --- Branches for review ---
branches = [(i.get("branch"), i.get("args", "").split("\n")[0][:60].strip())
            for i in succeeded if i.get("branch")]
if branches:
    lines.append("")
    lines.append("## Branches for Review")
    lines.append("")
    lines.append("```bash")
    for branch, desc in branches:
        lines.append(f"git checkout {branch}   # {desc}")
    lines.append("```")

report = "\n".join(lines) + "\n"

# --- Output / save ---
if mode == "--save":
    if not obsidian_vault:
        print("WARNING: Obsidian vault not configured in projects.json", file=sys.stderr)
        sys.exit(0)

    ts_suffix = run_started.strftime("%Y-%m-%d-%H%M")
    save_dir = os.path.join(obsidian_vault, "projects", active_project, "reports")
    save_path = os.path.join(save_dir, f"queue-report-{ts_suffix}.md")

    os.makedirs(save_dir, exist_ok=True)

    with open(save_path, "w", encoding="utf-8") as f:
        f.write(report)

    # Update queue.json last_report
    now_iso = datetime.now(timezone.utc).isoformat()
    queue_data["last_report"] = {
        "generated_at": now_iso,
        "saved_to": save_path,
    }
    with open(queue_file, "w", encoding="utf-8") as f:
        json.dump(queue_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Report saved to: {save_path}")
else:
    print(report, end="")
PYEOF
