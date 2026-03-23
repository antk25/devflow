#!/usr/bin/env python3
"""
DevFlow Monitor — Analyzes session logs for problems and improvement opportunities.

Usage:
  monitor-check.py quick                              — lightweight check for SessionEnd hook
  monitor-check.py full [--period 7d] [--project X]   — detailed analysis for /monitor skill
  monitor-check.py trends [--period 30d]              — statistics and trends

Output: JSON array of findings to stdout. Notifications to stderr.
"""

import json
import sys
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from argparse import ArgumentParser
from collections import Counter, defaultdict

SESSIONS_LOG_DIR = Path.home() / ".claude" / "sessions-log"
MONITOR_DIR = SESSIONS_LOG_DIR / "monitor"
CHECKS_FILE = MONITOR_DIR / "checks.jsonl"

SCRIPT_DIR = Path(__file__).resolve().parent
DEVFLOW_DIR = SCRIPT_DIR.parent
SESSIONS_FILE = DEVFLOW_DIR / ".claude" / "data" / "sessions.json"
PROJECTS_FILE = DEVFLOW_DIR / ".claude" / "data" / "projects.json"


def parse_period(period_str: str) -> timedelta:
    """Parse period string like '7d', '30d', '2w' into timedelta."""
    match = re.match(r"(\d+)([dwh])", period_str)
    if not match:
        return timedelta(days=7)
    num = int(match.group(1))
    unit = match.group(2)
    if unit == "d":
        return timedelta(days=num)
    elif unit == "w":
        return timedelta(weeks=num)
    elif unit == "h":
        return timedelta(hours=num)
    return timedelta(days=7)


def load_sessions() -> dict:
    """Load sessions.json."""
    if not SESSIONS_FILE.exists():
        return {}
    with open(SESSIONS_FILE) as f:
        data = json.load(f)
    return data.get("sessions", {})


def load_projects() -> dict:
    """Load projects.json to get project paths."""
    if not PROJECTS_FILE.exists():
        return {}
    with open(PROJECTS_FILE) as f:
        return json.load(f)


def parse_iso(ts: str) -> datetime | None:
    """Parse ISO timestamp string."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def finding(category: str, severity: str, description: str,
            evidence: str = "", suggestion: str = "", project: str = "") -> dict:
    """Create a finding dict."""
    return {
        "category": category,
        "severity": severity,
        "description": description,
        "evidence": evidence,
        "suggestion": suggestion,
        "project": project,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# === Checks ===

def check_failed_sessions(sessions: dict, period: timedelta | None = None) -> list[dict]:
    """Find sessions with failed status."""
    findings = []
    now = datetime.now(timezone.utc)
    for key, s in sessions.items():
        if s.get("status") != "failed":
            continue
        updated = parse_iso(s.get("updated_at", ""))
        if period and updated and (now - updated) > period:
            continue
        findings.append(finding(
            category="session_failure",
            severity="high",
            description=f"Session '{key}' failed at phase {s.get('current_phase', '?')}",
            evidence=f"skill={s.get('skill')}, project={s.get('project')}, "
                     f"completed_phases={len(s.get('completed_phases', []))}",
            suggestion="Check session logs for error details. Consider if the failure pattern is recurring.",
            project=s.get("project", ""),
        ))
    return findings


def check_stuck_sessions(sessions: dict, stale_hours: int = 2) -> list[dict]:
    """Find sessions stuck in 'running' status."""
    findings = []
    now = datetime.now(timezone.utc)
    for key, s in sessions.items():
        if s.get("status") != "running":
            continue
        updated = parse_iso(s.get("updated_at", ""))
        if not updated:
            continue
        age_hours = (now - updated).total_seconds() / 3600
        if age_hours < stale_hours:
            continue
        findings.append(finding(
            category="stuck_session",
            severity="medium",
            description=f"Session '{key}' stuck in 'running' for {age_hours:.0f}h",
            evidence=f"phase={s.get('current_phase')}, updated_at={s.get('updated_at')}",
            suggestion="Likely abandoned. Mark as interrupted or investigate why it didn't complete.",
            project=s.get("project", ""),
        ))
    return findings


def check_loop_events(sessions: dict, period: timedelta | None = None) -> list[dict]:
    """Find sessions where retry loops fired."""
    findings = []
    now = datetime.now(timezone.utc)
    for key, s in sessions.items():
        updated = parse_iso(s.get("updated_at", ""))
        if period and updated and (now - updated) > period:
            continue
        loops = s.get("loops", {})
        for loop_name, loop_data in loops.items():
            attempt = loop_data.get("attempt", 0)
            max_attempts = loop_data.get("max_attempts", 3)
            if attempt == 0:
                continue
            sev = "high" if attempt >= max_attempts else "medium"
            desc = (f"Loop '{loop_name}' fired {attempt}/{max_attempts} times in session '{key}'"
                    if attempt < max_attempts else
                    f"Loop '{loop_name}' reached max attempts ({max_attempts}) in session '{key}' — GIVE_UP")
            failures = loop_data.get("failures", [])
            evidence = "; ".join(failures[:3]) if failures else "no failure details recorded"
            findings.append(finding(
                category="loop_detection",
                severity=sev,
                description=desc,
                evidence=evidence,
                suggestion=f"Review the {loop_name} loop pattern. If recurring, adjust validation rules or agent prompts.",
                project=s.get("project", ""),
            ))
    return findings


def check_empty_sessions(sessions: dict, period: timedelta | None = None) -> list[dict]:
    """Find sessions with 0 completed phases (never got past config)."""
    findings = []
    now = datetime.now(timezone.utc)
    for key, s in sessions.items():
        if s.get("status") in ("running",):
            continue  # might still be active
        updated = parse_iso(s.get("updated_at", ""))
        if period and updated and (now - updated) > period:
            continue
        completed = s.get("completed_phases", [])
        if len(completed) <= 1 and s.get("status") in ("interrupted", "failed"):
            findings.append(finding(
                category="empty_session",
                severity="low",
                description=f"Session '{key}' completed only {len(completed)} phase(s) before {s.get('status')}",
                evidence=f"skill={s.get('skill')}, current_phase={s.get('current_phase')}",
                suggestion="Session failed early. Check if project config or branch creation has issues.",
                project=s.get("project", ""),
            ))
    return findings


def check_phase_history(sessions: dict, period: timedelta | None = None) -> list[dict]:
    """Find phases with failed/warning results in phase_history."""
    findings = []
    now = datetime.now(timezone.utc)
    for key, s in sessions.items():
        updated = parse_iso(s.get("updated_at", ""))
        if period and updated and (now - updated) > period:
            continue
        for phase in s.get("phase_history", []):
            result = phase.get("result", "")
            if result in ("failed", "warning"):
                findings.append(finding(
                    category="phase_failure",
                    severity="medium" if result == "warning" else "high",
                    description=f"Phase '{phase.get('phase', '?')}' {result} in session '{key}'",
                    evidence=f"reason={phase.get('reason', 'unknown')}, "
                             f"duration={phase.get('duration_seconds', '?')}s",
                    suggestion="Check if this phase fails consistently across sessions.",
                    project=s.get("project", ""),
                ))
    return findings


def check_session_summaries(project_filter: str | None = None,
                            period: timedelta | None = None) -> list[dict]:
    """Scan session summary markdown files for recurring 'Problems encountered' patterns."""
    findings = []
    now = datetime.now(timezone.utc)
    problems_by_project: dict[str, list[str]] = defaultdict(list)

    search_dirs = []
    if project_filter:
        p = SESSIONS_LOG_DIR / project_filter
        if p.exists():
            search_dirs.append((project_filter, p))
    else:
        if SESSIONS_LOG_DIR.exists():
            search_dirs = [(d.name, d) for d in SESSIONS_LOG_DIR.iterdir()
                           if d.is_dir() and d.name not in ("monitor", "raw")]

    for proj_name, proj_dir in search_dirs:
        for md_file in sorted(proj_dir.rglob("*.md"), reverse=True):
            if md_file.name == "INDEX.md":
                continue
            # Check period via directory name (YYYY-MM-DD)
            if period:
                try:
                    date_part = md_file.parent.name
                    file_date = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if (now - file_date) > period:
                        continue
                except ValueError:
                    continue

            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            # Extract "Problems encountered" section
            problems_match = re.search(
                r"##\s*Problems?\s*encountered\s*\n(.*?)(?=\n##|\Z)",
                content, re.DOTALL | re.IGNORECASE
            )
            if not problems_match:
                continue
            problems_text = problems_match.group(1).strip()
            if not problems_text or problems_text.lower() in ("none", "no problems", "-", "n/a"):
                continue

            # Extract individual problem lines
            for line in problems_text.split("\n"):
                line = line.strip().lstrip("- ").strip()
                if line and len(line) > 10:
                    problems_by_project[proj_name].append(line)

    # Find recurring problems (same or similar text appearing multiple times)
    for proj_name, problems in problems_by_project.items():
        if len(problems) < 2:
            continue
        # Simple frequency analysis: normalize and count
        normalized = Counter()
        originals: dict[str, str] = {}
        for p in problems:
            # Normalize: lowercase, remove punctuation, collapse whitespace
            norm = re.sub(r"[^\w\s]", "", p.lower())
            norm = re.sub(r"\s+", " ", norm).strip()
            # Use first 60 chars as key for grouping similar problems
            key = norm[:60]
            normalized[key] += 1
            if key not in originals:
                originals[key] = p

        for key, count in normalized.most_common(10):
            if count >= 2:
                findings.append(finding(
                    category="recurring_problem",
                    severity="high" if count >= 3 else "medium",
                    description=f"Problem appears {count} times in {proj_name} sessions: '{originals[key][:100]}'",
                    evidence=f"Found in {count} session summaries within the analysis period",
                    suggestion="This is a recurring issue. Consider creating a fix task or adjusting the workflow.",
                    project=proj_name,
                ))

        # Also report total problem count as a metric
        if len(problems) >= 5:
            findings.append(finding(
                category="problem_volume",
                severity="medium",
                description=f"Project '{proj_name}' had {len(problems)} problems across sessions",
                evidence="High problem volume may indicate systemic issues",
                suggestion="Review the most common problem types and prioritize structural fixes.",
                project=proj_name,
            ))

    return findings


def check_interrupted_ratio(project_filter: str | None = None,
                            period: timedelta | None = None) -> list[dict]:
    """Check ratio of interrupted/unknown sessions in INDEX files."""
    findings = []
    now = datetime.now(timezone.utc)

    search_dirs = []
    if project_filter:
        p = SESSIONS_LOG_DIR / project_filter
        if p.exists():
            search_dirs.append((project_filter, p))
    else:
        if SESSIONS_LOG_DIR.exists():
            search_dirs = [(d.name, d) for d in SESSIONS_LOG_DIR.iterdir()
                           if d.is_dir() and d.name not in ("monitor", "raw")]

    for proj_name, proj_dir in search_dirs:
        index_file = proj_dir / "INDEX.md"
        if not index_file.exists():
            continue

        total = 0
        interrupted = 0
        try:
            content = index_file.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if not line.startswith("|") or "---" in line or "Date" in line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 4:
                    continue
                # Check period
                date_str = parts[1].strip()[:10] if len(parts) > 1 else ""
                if period and date_str:
                    try:
                        entry_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        if (now - entry_date) > period:
                            continue
                    except ValueError:
                        pass
                total += 1
                status = parts[3].strip().lower() if len(parts) > 3 else ""
                if status in ("interrupted", "unknown"):
                    interrupted += 1
        except Exception:
            continue

        if total >= 5 and interrupted / total > 0.3:
            findings.append(finding(
                category="high_interruption_rate",
                severity="medium",
                description=f"Project '{proj_name}': {interrupted}/{total} sessions ({interrupted*100//total}%) interrupted/unknown",
                evidence=f"High interruption rate suggests workflow instability or frequent context switches",
                suggestion="Investigate common interruption causes. Consider session resilience improvements.",
                project=proj_name,
            ))

    return findings


def check_lessons_learned(project_filter: str | None = None) -> list[dict]:
    """Check lessons-learned files for recurring violations."""
    findings = []
    projects_data = load_projects()

    projects = projects_data.get("projects", {})
    for proj_name, proj_config in projects.items():
        if project_filter and proj_name != project_filter:
            continue
        proj_path = proj_config.get("path", "")
        if not proj_path:
            continue
        lessons_file = Path(proj_path) / ".claude" / "data" / "lessons-learned.md"
        if not lessons_file.exists():
            continue

        try:
            content = lessons_file.read_text(encoding="utf-8")
        except Exception:
            continue

        # Count violation patterns
        violation_count = content.lower().count("violation")
        issue_count = content.lower().count("issue")

        if violation_count >= 3:
            findings.append(finding(
                category="recurring_violations",
                severity="medium",
                description=f"Project '{proj_name}' has {violation_count} recorded violations in lessons-learned",
                evidence="Multiple architecture/pattern violations suggest patterns.md may need updating",
                suggestion="Review lessons-learned.md and update patterns.md or agent prompts accordingly.",
                project=proj_name,
            ))

    return findings


# === Trend Analysis ===

def compute_trends(sessions: dict, period: timedelta) -> dict:
    """Compute session statistics and trends."""
    now = datetime.now(timezone.utc)
    stats = {
        "total": 0,
        "completed": 0,
        "failed": 0,
        "interrupted": 0,
        "running": 0,
        "by_skill": Counter(),
        "by_project": Counter(),
        "by_status": Counter(),
        "loop_fires": 0,
        "avg_phases": 0,
        "phases_list": [],
        "agent_spawns": Counter(),
        "avg_duration_minutes": 0,
        "durations": [],
    }

    for key, s in sessions.items():
        updated = parse_iso(s.get("updated_at", ""))
        if updated and (now - updated) > period:
            continue
        stats["total"] += 1
        status = s.get("status", "unknown")
        stats["by_status"][status] += 1
        stats["by_skill"][s.get("skill", "unknown")] += 1
        stats["by_project"][s.get("project", "unknown")] += 1

        phases_count = len(s.get("completed_phases", []))
        stats["phases_list"].append(phases_count)

        for loop_data in s.get("loops", {}).values():
            if loop_data.get("attempt", 0) > 0:
                stats["loop_fires"] += 1

        # Track agent spawns from phase_history
        for phase in s.get("phase_history", []):
            phase_name = phase.get("phase", "")
            if "implement" in phase_name:
                stats["agent_spawns"]["developer"] += 1
            elif "validate" in phase_name or "guardian" in phase_name:
                stats["agent_spawns"]["guardian"] += 1
            elif "review" in phase_name:
                stats["agent_spawns"]["reviewer"] += 1
            elif "trace" in phase_name:
                stats["agent_spawns"]["tracer"] += 1
            elif "test" in phase_name or "e2e" in phase_name:
                stats["agent_spawns"]["tester"] += 1

        # Track session duration
        started = parse_iso(s.get("started_at", ""))
        if started and updated:
            duration_min = (updated - started).total_seconds() / 60
            if 0 < duration_min < 600:  # sanity: < 10 hours
                stats["durations"].append(duration_min)

    if stats["phases_list"]:
        stats["avg_phases"] = round(sum(stats["phases_list"]) / len(stats["phases_list"]), 1)

    if stats["durations"]:
        stats["avg_duration_minutes"] = round(sum(stats["durations"]) / len(stats["durations"]), 1)

    # Scan INDEX.md files for skill invocations not tracked in sessions.json
    # (e.g., /review, /explore, /investigate — these don't create sessions)
    skill_mentions = count_skill_mentions_in_logs(period)
    if skill_mentions:
        stats["skill_mentions_in_logs"] = dict(skill_mentions)

    # Convert Counters to dicts for JSON serialization
    stats["by_skill"] = dict(stats["by_skill"])
    stats["by_project"] = dict(stats["by_project"])
    stats["by_status"] = dict(stats["by_status"])
    stats["agent_spawns"] = dict(stats["agent_spawns"])
    del stats["phases_list"]
    del stats["durations"]

    return stats


def count_skill_mentions_in_logs(period: timedelta) -> Counter:
    """Scan session log summaries for skill/command mentions."""
    now = datetime.now(timezone.utc)
    skill_pattern = re.compile(r"/(develop|fix|refactor|explore|investigate|review|audit|finalize|resume|recall|monitor|careful|note|next|project)\b")
    counts = Counter()

    if not SESSIONS_LOG_DIR.exists():
        return counts

    for proj_dir in SESSIONS_LOG_DIR.iterdir():
        if not proj_dir.is_dir() or proj_dir.name in ("monitor", "raw"):
            continue
        for md_file in proj_dir.rglob("*.md"):
            if md_file.name == "INDEX.md":
                continue
            # Check period
            try:
                date_part = md_file.parent.name
                file_date = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if (now - file_date) > period:
                    continue
            except ValueError:
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")[:5000]
            except Exception:
                continue
            for match in skill_pattern.finditer(content):
                counts[match.group(1)] += 1

    return counts


# === Commands ===

def cmd_quick(args):
    """Lightweight check for SessionEnd hook. Only sessions.json, fast."""
    sessions = load_sessions()
    all_findings = []
    all_findings.extend(check_failed_sessions(sessions, period=timedelta(days=1)))
    all_findings.extend(check_stuck_sessions(sessions, stale_hours=2))
    all_findings.extend(check_loop_events(sessions, period=timedelta(days=1)))
    all_findings.extend(check_empty_sessions(sessions, period=timedelta(days=1)))

    # Output JSON
    print(json.dumps(all_findings, ensure_ascii=False))

    # Notifications to stderr for critical/high
    critical = [f for f in all_findings if f["severity"] in ("critical", "high")]
    if critical:
        lines = [f["description"] for f in critical[:3]]
        print("\n".join(lines), file=sys.stderr)

    return len(critical)


def cmd_full(args):
    """Full analysis for /monitor skill."""
    period = parse_period(args.period) if args.period else timedelta(days=7)
    project = args.project

    sessions = load_sessions()
    all_findings = []

    # Structured data checks
    all_findings.extend(check_failed_sessions(sessions, period))
    all_findings.extend(check_stuck_sessions(sessions))
    all_findings.extend(check_loop_events(sessions, period))
    all_findings.extend(check_empty_sessions(sessions, period))
    all_findings.extend(check_phase_history(sessions, period))

    # Summary-based checks
    all_findings.extend(check_session_summaries(project, period))
    all_findings.extend(check_interrupted_ratio(project, period))

    # Lessons learned
    all_findings.extend(check_lessons_learned(project))

    # Sort by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    all_findings.sort(key=lambda f: severity_order.get(f["severity"], 9))

    print(json.dumps(all_findings, ensure_ascii=False, indent=2))


def cmd_trends(args):
    """Statistics and trends."""
    period = parse_period(args.period) if args.period else timedelta(days=30)

    sessions = load_sessions()
    stats = compute_trends(sessions, period)

    # Also check recent monitor checks
    recent_checks = []
    if CHECKS_FILE.exists():
        now = datetime.now(timezone.utc)
        try:
            with open(CHECKS_FILE) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        check = json.loads(line)
                        check_time = parse_iso(check.get("timestamp", ""))
                        if check_time and (now - check_time) <= period:
                            recent_checks.append(check)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

    # Count finding categories across checks
    category_counts = Counter()
    for check in recent_checks:
        for f in check.get("findings", []):
            category_counts[f.get("category", "unknown")] += 1

    output = {
        "period": str(period),
        "session_stats": stats,
        "monitor_checks": len(recent_checks),
        "finding_categories": dict(category_counts),
        "skill_usage": {
            "tracked_sessions": stats.get("by_skill", {}),
            "log_mentions": stats.get("skill_mentions_in_logs", {}),
            "agent_spawns": stats.get("agent_spawns", {}),
        },
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


def main():
    parser = ArgumentParser(description="DevFlow Monitor")
    subparsers = parser.add_subparsers(dest="command")

    # quick
    p_quick = subparsers.add_parser("quick", help="Lightweight check for hook")
    p_quick.set_defaults(func=cmd_quick)

    # full
    p_full = subparsers.add_parser("full", help="Full analysis")
    p_full.add_argument("--period", default="7d", help="Analysis period (e.g., 7d, 30d, 2w)")
    p_full.add_argument("--project", default=None, help="Filter by project name")
    p_full.set_defaults(func=cmd_full)

    # trends
    p_trends = subparsers.add_parser("trends", help="Statistics and trends")
    p_trends.add_argument("--period", default="30d", help="Trend period (e.g., 30d, 90d)")
    p_trends.set_defaults(func=cmd_trends)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
