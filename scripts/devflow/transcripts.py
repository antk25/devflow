import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterator, NamedTuple

PROJECTS_ROOT = Path.home() / ".claude" / "projects"
LEDGER = Path.home() / ".claude" / "devflow" / "task-ledger.jsonl"
NO_TASK = "(без задачи)"


class Msg(NamedTuple):
    ts: datetime
    cwd: str
    session: str
    text: str


def project_of(cwd):
    if not cwd:
        return "?"
    home = str(Path.home())
    for base in (f"{home}/projects/", f"{home}/"):
        if cwd.startswith(base):
            return cwd[len(base):] or "?"
    return cwd


def parse_ts(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def user_text(message):
    """Текст, который набрал пользователь. Без tool_result и системных напоминаний."""
    content = message.get("content")
    if isinstance(content, str):
        chunks = [content]
    elif isinstance(content, list):
        chunks = [b.get("text", "") for b in content
                  if isinstance(b, dict) and b.get("type") == "text"]
    else:
        return ""
    text = " ".join(chunks)
    return re.sub(r"<system-reminder>.*?</system-reminder>", " ", text, flags=re.S)


def load_ledger():
    by_session = defaultdict(list)
    if not LEDGER.exists():
        return by_session
    for line in LEDGER.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        sid, task = entry.get("session"), entry.get("task")
        if sid and task:
            by_session[sid].append((parse_ts(entry.get("ts")), task.upper()))
    return by_session


def assign_tasks(msgs, marks):
    """Задача сообщения — последний ключ, упомянутый до него; голова сессии заполняется первым."""
    dated = sorted([m for m in marks if m[0]], key=lambda m: m[0])
    if not dated:
        fallback = marks[0][1] if marks else NO_TASK
        for m in msgs:
            m["task"] = fallback
        return
    first = dated[0][1]
    for m in msgs:
        current = first
        if m["ts"]:
            for ts, task in dated:
                if ts <= m["ts"]:
                    current = task
                else:
                    break
        m["task"] = current


def human_messages(root: Path, since: datetime, until: datetime) -> Iterator[Msg]:
    for path in sorted(root.glob("*/*.jsonl")):
        for line in path.open(encoding="utf-8", errors="ignore"):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("type") != "user" or entry.get("isSidechain"):
                continue
            ts = parse_ts(entry.get("timestamp"))
            if not ts or not since <= ts < until:
                continue
            text = user_text(entry.get("message", {})).strip()
            if text:
                yield Msg(ts, entry.get("cwd") or "", entry.get("sessionId") or path.stem, text)
