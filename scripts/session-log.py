#!/usr/bin/env python3
"""
Session Logger for DevFlow.
Parses Claude Code JSONL transcripts and creates structured summaries.

Usage:
  session-log.py summarize <transcript_path> <session_id> [--project <name>]
  session-log.py snapshot <transcript_path> <session_id>
  session-log.py search <query> [--project <name>] [--limit <n>]
  session-log.py list [--project <name>] [--days <n>]
"""

import json
import sys
import os
import re
import subprocess
import shutil
from datetime import datetime, timezone
from pathlib import Path
from argparse import ArgumentParser

SESSIONS_LOG_DIR = Path.home() / ".claude" / "sessions-log"


def get_project_name(cwd: str) -> str:
    """Extract project name from cwd or git remote."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return Path(result.stdout.strip()).name
    except Exception:
        pass
    return Path(cwd).name


def parse_transcript(transcript_path: str) -> dict:
    """Parse JSONL transcript into structured conversation data."""
    messages = []
    tools_used = set()
    files_changed = set()
    session_id = None
    cwd = None
    git_branch = None
    start_time = None
    end_time = None

    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not session_id and obj.get("sessionId"):
                session_id = obj["sessionId"]
            if not cwd and obj.get("cwd"):
                cwd = obj["cwd"]
            if not git_branch and obj.get("gitBranch"):
                git_branch = obj["gitBranch"]

            msg_type = obj.get("type")
            timestamp = obj.get("timestamp")

            if timestamp:
                ts = timestamp
                if not start_time:
                    start_time = ts
                end_time = ts

            if msg_type == "user":
                content = obj.get("message", {}).get("content", "")
                if isinstance(content, str) and content.strip():
                    messages.append({"role": "user", "text": content.strip()[:500]})
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            messages.append({"role": "user", "text": c["text"].strip()[:500]})
                            break

            elif msg_type == "assistant":
                content = obj.get("message", {}).get("content", [])
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip():
                            messages.append({"role": "assistant", "text": c["text"].strip()[:500]})
                            break
                        elif isinstance(c, dict) and c.get("type") == "tool_use":
                            tool_name = c.get("name", "")
                            tools_used.add(tool_name)
                            tool_input = c.get("input", {})
                            # Track file changes
                            if tool_name in ("Write", "Edit"):
                                fp = tool_input.get("file_path", "")
                                if fp:
                                    files_changed.add(fp)
                            elif tool_name == "Bash":
                                cmd = tool_input.get("command", "")
                                if "git commit" in cmd:
                                    tools_used.add("git_commit")

    return {
        "session_id": session_id,
        "cwd": cwd or "",
        "git_branch": git_branch or "",
        "messages": messages,
        "tools_used": sorted(tools_used),
        "files_changed": sorted(files_changed),
        "start_time": start_time,
        "end_time": end_time,
        "message_count": len(messages),
    }


def build_conversation_text(data: dict) -> str:
    """Build a condensed conversation text for summarization."""
    lines = []
    lines.append(f"Project: {get_project_name(data['cwd'])}")
    lines.append(f"Branch: {data['git_branch']}")
    lines.append(f"Tools used: {', '.join(data['tools_used'][:20])}")
    if data["files_changed"]:
        lines.append(f"Files changed: {', '.join(data['files_changed'][:30])}")
    lines.append("")
    lines.append("=== Conversation ===")
    for msg in data["messages"]:
        role = "USER" if msg["role"] == "user" else "CLAUDE"
        lines.append(f"\n{role}: {msg['text']}")

    text = "\n".join(lines)
    # Limit to ~30k chars to fit in haiku context
    if len(text) > 30000:
        text = text[:30000] + "\n\n[... truncated ...]"
    return text


def get_summarization_prompt(conversation_text: str) -> str:
    """Build the summarization prompt."""
    return f"""Summarize this Claude Code session in a structured markdown format.
Write in the SAME language the user used (Russian if they wrote in Russian, English if English).

Format:
```
# Session: <date> — <short title describing main task>
## Status: <completed|in-progress|interrupted>
## Summary
<2-3 sentences about what was done>
## Key decisions
- <decision 1>
- <decision 2>
## Files changed
- <file1> (<new|modified|deleted>)
## Problems encountered
- <problem and how it was resolved>
## Next steps
- <what remains to be done, if anything>
```

If the session was trivial (just a greeting or simple question), write a one-line summary instead.

Session transcript:
{conversation_text}"""


def summarize_with_api(conversation_text: str) -> str | None:
    """Try to summarize using Anthropic API directly (no claude CLI needed)."""
    try:
        import anthropic
    except ImportError:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": get_summarization_prompt(conversation_text)}],
        )
        return response.content[0].text.strip()
    except Exception:
        return None


def summarize_with_claude(conversation_text: str) -> str:
    """Generate a structured summary using Claude. Tries API first, then CLI."""
    # Try API directly if ANTHROPIC_API_KEY is available
    result = summarize_with_api(conversation_text)
    if result:
        return result

    # Try claude CLI (works from SessionEnd hook where session is already closing)
    prompt = get_summarization_prompt(conversation_text)
    env = os.environ.copy()
    # Remove Claude Code session markers to allow nested invocation
    for var in ("CLAUDECODE", "CLAUDE_CODE_RUNNING", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(var, None)

    try:
        proc = subprocess.run(
            ["claude", "-p", "--model", "haiku", "--no-session-persistence",
             "--output-format", "text"],
            input=prompt, env=env,
            capture_output=True, text=True, timeout=120
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
        # CLI failed, use basic summary
        return generate_basic_summary(conversation_text)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return generate_basic_summary(conversation_text)


def generate_basic_summary(conversation_text: str) -> str:
    """Generate a basic summary without LLM, as fallback."""
    lines = conversation_text.split("\n")
    user_messages = [l for l in lines if l.startswith("USER: ")]
    first_user = user_messages[0][6:80] if user_messages else "Unknown task"
    return f"# Session summary\n## Task\n{first_user}\n## Messages\n{len(user_messages)} user messages"


def save_summary(project: str, session_id: str, summary: str, data: dict):
    """Save summary and update index."""
    project_dir = SESSIONS_LOG_DIR / project
    project_dir.mkdir(parents=True, exist_ok=True)

    # Parse start time for filename
    now = datetime.now()
    if data.get("start_time"):
        try:
            ts = data["start_time"]
            if isinstance(ts, str):
                now = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            elif isinstance(ts, (int, float)):
                now = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts, tz=timezone.utc)
        except Exception:
            pass

    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M")

    # Extract topic from summary title
    topic = "session"
    title_match = re.search(r"#\s*Session:.*?—\s*(.+)", summary)
    if title_match:
        topic = re.sub(r"[^\w\s-]", "", title_match.group(1)).strip()
        topic = re.sub(r"\s+", "-", topic)[:50].lower()

    # Day directory
    day_dir = project_dir / date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    # Save summary
    summary_file = day_dir / f"{time_str}_{topic}.md"
    counter = 1
    while summary_file.exists():
        summary_file = day_dir / f"{time_str}_{topic}_{counter}.md"
        counter += 1

    # Add metadata header
    meta = f"""<!--
session_id: {session_id}
project: {project}
branch: {data.get('git_branch', '')}
date: {now.isoformat()}
files_changed: {len(data.get('files_changed', []))}
message_count: {data.get('message_count', 0)}
-->

"""
    summary_file.write_text(meta + summary, encoding="utf-8")

    # Update index
    update_index(project_dir, date_str, time_str, topic, summary_file.name, summary, session_id)

    return str(summary_file)


def update_index(project_dir: Path, date_str: str, time_str: str, topic: str,
                 filename: str, summary: str, session_id: str):
    """Update the sessions index file."""
    index_file = project_dir / "INDEX.md"

    # Extract one-liner from summary
    one_liner = topic.replace("-", " ")
    status_match = re.search(r"##\s*Status:\s*(.+)", summary)
    status = status_match.group(1).strip() if status_match else "unknown"

    entry = f"| {date_str} {time_str.replace('-', ':')} | {one_liner} | {status} | [{filename}]({date_str}/{filename}) | `{session_id[:8]}` |\n"

    if index_file.exists():
        content = index_file.read_text(encoding="utf-8")
        # Insert new entry after table header
        table_header_end = content.find("|\n", content.find("| --- |"))
        if table_header_end >= 0:
            insert_pos = table_header_end + 2
            content = content[:insert_pos] + entry + content[insert_pos:]
        else:
            content += entry
        index_file.write_text(content, encoding="utf-8")
    else:
        header = f"""# Session Log — {project_dir.name}

| Date | Topic | Status | File | Session |
| --- | --- | --- | --- | --- |
{entry}"""
        index_file.write_text(header, encoding="utf-8")


def save_snapshot(transcript_path: str, session_id: str, project: str):
    """Save raw transcript snapshot (before compaction)."""
    project_dir = SESSIONS_LOG_DIR / project / "raw"
    project_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d_%H-%M")
    dest = project_dir / f"{date_str}_{session_id[:8]}.jsonl"

    shutil.copy2(transcript_path, str(dest))
    return str(dest)


def search_summaries(query: str, project: str = None, limit: int = 10):
    """Search through session summaries."""
    results = []
    search_dirs = []

    if project:
        search_dirs.append(SESSIONS_LOG_DIR / project)
    else:
        if SESSIONS_LOG_DIR.exists():
            search_dirs = [d for d in SESSIONS_LOG_DIR.iterdir() if d.is_dir()]

    query_lower = query.lower()
    query_words = query_lower.split()

    for proj_dir in search_dirs:
        for md_file in sorted(proj_dir.rglob("*.md"), reverse=True):
            if md_file.name == "INDEX.md":
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
                content_lower = content.lower()
                # Score based on word matches
                score = sum(1 for w in query_words if w in content_lower)
                if score > 0:
                    results.append((score, md_file, content))
            except Exception:
                continue

    results.sort(key=lambda x: -x[0])
    return results[:limit]


def list_sessions(project: str = None, days: int = 7):
    """List recent sessions."""
    if project:
        index_file = SESSIONS_LOG_DIR / project / "INDEX.md"
        if index_file.exists():
            content = index_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            # Print header + last N entries
            header = lines[:3]
            entries = [l for l in lines[3:] if l.strip().startswith("|")]
            print("\n".join(header))
            for entry in entries[:days * 5]:  # ~5 sessions per day max
                print(entry)
        else:
            print(f"No sessions found for project: {project}")
    else:
        if not SESSIONS_LOG_DIR.exists():
            print("No session logs found.")
            return
        for proj_dir in sorted(SESSIONS_LOG_DIR.iterdir()):
            if proj_dir.is_dir() and proj_dir.name != "raw":
                count = sum(1 for _ in proj_dir.rglob("*.md") if _.name != "INDEX.md")
                print(f"  {proj_dir.name}: {count} sessions")


def cmd_summarize(args):
    transcript_path = args.transcript_path
    session_id = args.session_id

    if not os.path.exists(transcript_path):
        print(f"Transcript not found: {transcript_path}", file=sys.stderr)
        sys.exit(1)

    data = parse_transcript(transcript_path)

    # Skip trivial sessions (< 2 messages)
    if data["message_count"] < 2:
        print("Session too short, skipping summarization.", file=sys.stderr)
        sys.exit(0)

    project = args.project or get_project_name(data["cwd"])
    conversation_text = build_conversation_text(data)
    summary = summarize_with_claude(conversation_text)
    summary_path = save_summary(project, session_id, summary, data)
    print(f"Summary saved: {summary_path}")


def cmd_snapshot(args):
    transcript_path = args.transcript_path
    session_id = args.session_id

    if not os.path.exists(transcript_path):
        print(f"Transcript not found: {transcript_path}", file=sys.stderr)
        sys.exit(1)

    data = parse_transcript(transcript_path)
    project = get_project_name(data["cwd"]) if data["cwd"] else "unknown"
    snapshot_path = save_snapshot(transcript_path, session_id, project)
    print(f"Snapshot saved: {snapshot_path}")


def cmd_search(args):
    results = search_summaries(args.query, project=args.project, limit=args.limit)
    if not results:
        print("No matching sessions found.")
        return
    for score, path, content in results:
        rel = path.relative_to(SESSIONS_LOG_DIR)
        print(f"\n{'='*60}")
        print(f"📄 {rel} (relevance: {score})")
        print(f"{'='*60}")
        # Print first 30 lines of content (skip metadata)
        lines = content.split("\n")
        in_meta = False
        printed = 0
        for line in lines:
            if line.strip() == "<!--":
                in_meta = True
                continue
            if line.strip() == "-->":
                in_meta = False
                continue
            if not in_meta:
                print(line)
                printed += 1
                if printed >= 30:
                    print("  [...]")
                    break


def cmd_list(args):
    list_sessions(project=args.project, days=args.days)


def main():
    parser = ArgumentParser(description="DevFlow Session Logger")
    subparsers = parser.add_subparsers(dest="command")

    # summarize
    p_sum = subparsers.add_parser("summarize", help="Summarize a session transcript")
    p_sum.add_argument("transcript_path")
    p_sum.add_argument("session_id")
    p_sum.add_argument("--project", default=None)
    p_sum.set_defaults(func=cmd_summarize)

    # snapshot
    p_snap = subparsers.add_parser("snapshot", help="Save raw transcript snapshot")
    p_snap.add_argument("transcript_path")
    p_snap.add_argument("session_id")
    p_snap.set_defaults(func=cmd_snapshot)

    # search
    p_search = subparsers.add_parser("search", help="Search session summaries")
    p_search.add_argument("query")
    p_search.add_argument("--project", default=None)
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    # list
    p_list = subparsers.add_parser("list", help="List recent sessions")
    p_list.add_argument("--project", default=None)
    p_list.add_argument("--days", type=int, default=7)
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
