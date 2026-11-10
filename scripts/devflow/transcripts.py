import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, NamedTuple

PROJECTS_ROOT = Path.home() / ".claude" / "projects"
PI_ROOT = Path.home() / ".pi" / "agent" / "sessions"
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


def mark_session(session, slug, now=None, phase=None):
    """Pin a non-interactive session to its task: the ledger is what /tokens attributes by."""
    m = re.match(r"([a-z]+-\d+)", slug.lower())
    entry = {"ts": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"), "session": session,
             "task": (m[1] if m else slug).upper()}
    if phase:
        entry["phase"] = phase
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


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


def load_phases():
    """Phase of each `claude -p` session: its transcript has no attributionAgent."""
    phases = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("session") and entry.get("phase"):
                phases[entry["session"]] = entry["phase"]
    return phases


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


def tag_messages(msgs, ledger: dict, since: datetime, key_re: re.Pattern,
                 project_fn: Callable[[str], str | None]) -> list:
    """(ts, project, key) по сообщениям с ts >= since; более ранние дают только метки задач."""
    by_session = defaultdict(list)
    for m in msgs:
        by_session[m.session].append(m)
    out = []
    for sid, items in by_session.items():
        marks = list(ledger.get(sid, []))
        marks += [(m.ts, k.group(0).upper()) for m in items for k in key_re.finditer(m.text[:8000])]
        rows = [{"ts": m.ts, "cwd": m.cwd} for m in items]
        assign_tasks(rows, marks)
        for r in rows:
            project = project_fn(r["cwd"])
            if project and r["ts"] >= since:
                out.append((r["ts"], project, "" if r["task"] == NO_TASK else r["task"]))
    return out


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


def pi_messages(root: Path, since: datetime, until: datetime) -> Iterator[Msg]:
    for path in sorted(root.glob("*/*.jsonl")):
        cwd, session = "", path.stem
        for line in path.open(encoding="utf-8", errors="ignore"):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == "session":
                cwd, session = entry.get("cwd") or "", entry.get("id") or session
                continue
            message = entry.get("message")
            if entry.get("type") != "message" or not isinstance(message, dict) or message.get("role") != "user":
                continue
            ts = parse_ts(entry.get("timestamp"))
            if not ts or not since <= ts < until:
                continue
            text = user_text(message).strip()
            if text:
                yield Msg(ts, cwd, session, text)
