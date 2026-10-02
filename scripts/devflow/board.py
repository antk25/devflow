"""Read-only task board: stages of every registry project in one JSON snapshot."""
import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .documents import WorkflowError, artifact, context, plan_steps
from .project import ROOT, registry_path
from .registry import load as load_registry
from .storage import atomic_write, connect
from .workflow import route

STATE_DIR = Path.home() / '.claude' / 'devflow' / 'board'
KEY_RE = re.compile(r'^[a-z][a-z0-9]+-\d+')
DONE_DAYS = timedelta(days=7)
ACTIVE_LIMIT = 50
WAIT = {'approval_required': '⏸ гейт {phase}', 'review_required': '⏸ ревью плана', 'blocked': '⏸ blocked',
        'migration_required': '⏸ миграция плана', 'migration_pending': '⏸ миграция плана',
        'plan_outdated': '⏸ план устарел', 'legacy_review': '⏸ legacy'}
GROUPS = ('wait', 'work', 'done')


def task_key(slug: str) -> str | None:
    m = KEY_RE.match(slug.lower())
    return m[0].upper() if m else None


def _days(since: datetime | None, now: datetime) -> str:
    return '' if since is None else f' · {max((now - since).days, 0)} д'


def stage(route: dict, gate_since: datetime | None, now: datetime) -> dict:
    state = route['state']
    since = gate_since.isoformat(timespec='seconds') if gate_since else None
    if state == 'completed':
        return {'label': 'готово', 'group': 'done', 'since': since}
    if state in WAIT:
        label = WAIT[state].format(phase=route.get('phase') or 'research') + _days(gate_since, now)
        return {'label': label, 'group': 'wait', 'since': since}
    if state in ('ready', 'running'):
        n, total = route.get('n'), route.get('total')
        label = f'implement {n}/{total}' if n and total else 'implement'
    else:
        label = route.get('phase') or state
    return {'label': label, 'group': 'work', 'since': since}


def _mtime(path: str | None) -> datetime | None:
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc) if path else None
    except OSError:
        return None


def _title(ctx, slug: str) -> str:
    for folder in ('tz', 'research', 'plans'):
        doc = artifact(ctx['vault'], folder, slug)
        if doc:
            m = re.search(r'^#\s+(.+?)\s*$', doc['body'], re.M)
            if m:
                return re.sub(r'\s+[—-]\s+(Research|Plan|ТЗ)$', '', m[1])
    return slug


def _task(ctx, name: str, rt: dict, since: datetime | None, now: datetime) -> dict:
    slug = rt['slug']
    if rt['state'] == 'running' and rt.get('plan_path'):
        steps = plan_steps(artifact(ctx['vault'], 'plans', slug))
        rt = dict(rt, total=len(steps), n=next((s['n'] for s in steps if s['id'] == rt.get('step')), None))
    tz = artifact(ctx['vault'], 'tz', slug)
    return {'slug': slug, 'key': task_key(slug), 'project': name, 'title': _title(ctx, slug),
            'stage': stage(rt, since, now), 'state': rt['state'],
            'links': {'tz': tz['path'] if tz else None, 'research': rt.get('research_path'), 'plan': rt.get('plan_path')}}


def project_tasks(name: str, path: Path, now: datetime) -> tuple[list[dict], str | None]:
    try:
        ctx = context(path)
        if not (ctx['cwd'] / '.devflow/project.json').exists():
            return [], f'{name}: проект не инициализирован (нет .devflow/project.json)'
        db = connect(ctx)
    except (WorkflowError, OSError, sqlite3.Error, yaml.YAMLError) as exc:
        return [], f'{name}: {exc}'
    from .cli import active  # local import: cli itself dispatches `devflow board` to this module
    tasks, seen = [], set()
    try:
        db.execute('BEGIN')
        listed = active(ctx, db, ACTIVE_LIMIT)
        for folder in ('tz', 'research', 'plans'):
            for item in listed[folder]:
                rt = item.get('route')
                if not rt or rt['slug'] in seen:
                    continue
                seen.add(rt['slug'])
                since = _mtime(rt.get('artifact') or rt.get('plan_path') or rt.get('research_path')) \
                    if stage(rt, None, now)['group'] == 'wait' else None
                tasks.append(_task(ctx, name, rt, since, now))
        cutoff = (now - DONE_DAYS).isoformat(timespec='seconds')
        finished = {}
        for row in db.execute("SELECT slug, at, data FROM events WHERE action='finish' AND at>=? ORDER BY at", (cutoff,)):
            if json.loads(row['data']).get('status') == 'done':
                finished[row['slug']] = row['at']
        for slug, at in finished.items():
            if slug in seen:
                continue
            try:
                rt = route(ctx, db, slug)
            except (WorkflowError, yaml.YAMLError, OSError, ValueError):
                continue
            if rt['state'] == 'completed':
                seen.add(slug)
                tasks.append(_task(ctx, name, rt, datetime.fromisoformat(at), now))
    finally:
        db.close()
    return tasks, None


def collect_tasks(registry: dict, now: datetime) -> dict:
    tasks, errors = [], []
    for name, entry in registry['projects'].items():
        try:
            found, error = project_tasks(name, Path(entry['path']), now)
        except Exception as exc:  # one broken project must not take the whole board down
            found, error = [], f'{name}: {exc}'
        tasks += found
        if error:
            errors.append(error)
    return {'tasks': tasks, 'errors': errors}


def order(tasks: list[dict], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    cutoff = (now - DONE_DAYS).isoformat(timespec='seconds')
    by = {g: [t for t in tasks if t['stage']['group'] == g] for g in GROUPS}
    since = lambda t: t['stage']['since'] or ''
    wait = sorted(by['wait'], key=lambda t: (not since(t), since(t)))
    work = sorted(by['work'], key=lambda t: (t['project'], t['slug']))
    done = sorted((t for t in by['done'] if since(t) >= cutoff), key=since, reverse=True)
    return wait + work + done


def build(state: Path, now: datetime | None = None, sources: dict | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    sources = sources or {}
    registry = sources.get('registry') or load_registry(registry_path(ROOT))
    collected = collect_tasks(registry, now)
    snapshot = {'generated': now.isoformat(timespec='seconds'), 'tasks': order(collected['tasks'], now),
                'errors': collected['errors']}
    atomic_write(Path(state) / 'snapshot.json', json.dumps(snapshot, ensure_ascii=False, indent=1) + '\n')
    return snapshot


def load(state: Path) -> dict | None:
    path = Path(state) / 'snapshot.json'
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except ValueError:
        return None


def snapshot(state: Path = STATE_DIR, refresh: bool = False) -> dict:
    return (None if refresh else load(state)) or build(state)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='devflow board')
    ap.add_argument('--refresh', action='store_true')
    args = ap.parse_args(argv)
    print(json.dumps(snapshot(refresh=args.refresh), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
