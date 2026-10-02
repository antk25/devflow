"""Read-only task board: stages of every registry project in one JSON snapshot."""
import argparse
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from . import policy
from . import timesheet as ts
from .documents import WorkflowError, artifact, context, plan_steps
from .project import ROOT, registry_path
from .registry import load as load_registry
from .storage import atomic_write, connect
from .transcripts import NO_TASK, PI_ROOT, PROJECTS_ROOT, human_messages, load_ledger, pi_messages, project_of, tag_messages
from .workflow import route

STATE_DIR = Path.home() / '.claude' / 'devflow' / 'board'
KEY_RE = re.compile(r'^[a-z][a-z0-9]+-\d+')
DONE_DAYS = timedelta(days=7)
MOVE_DAYS = timedelta(days=14)
HIDDEN_TZ = ('obsolete', 'done')
ACTIVE_LIMIT = 50
CACHE_TTL = timedelta(minutes=10)
HISTORY_DAYS = timedelta(days=90)
ROW_MIN_SECONDS = 30 * 60
TOKEN_STATS = ROOT / 'skills' / 'tokens' / 'token-stats.py'
PR_KEY_RE = re.compile(r'\b[A-Z][A-Z0-9]+-\d+\b')
PR_FIELDS = 'number,title,state,repository,url,updatedAt'
WAIT = {'approval_required': '⏸ гейт {phase}', 'review_required': '⏸ ревью плана', 'blocked': '⏸ blocked',
        'migration_required': '⏸ миграция плана', 'migration_pending': '⏸ миграция плана',
        'plan_outdated': '⏸ план устарел', 'legacy_review': '⏸ legacy'}
GROUPS = ('wait', 'work', 'done')
CHART_DAYS = 14
CHART_TOP = 5
OTHER = 'прочее'
LIMIT_WINDOWS = {'five_hour': '5 ч', 'seven_day': '7 дн'}
LIMITS_MAX_AGE_MIN = 10


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


def _task(ctx, name: str, rt: dict, since: datetime | None, now: datetime, moved_at: str | None) -> dict | None:
    slug = rt['slug']
    tz = artifact(ctx['vault'], 'tz', slug)
    if tz and tz['meta'].get('status') in HIDDEN_TZ:
        return None
    if rt['state'] == 'running' and rt.get('plan_path'):
        steps = plan_steps(artifact(ctx['vault'], 'plans', slug))
        rt = dict(rt, total=len(steps), n=next((s['n'] for s in steps if s['id'] == rt.get('step')), None))
    return {'slug': slug, 'key': task_key(slug), 'project': name, 'title': _title(ctx, slug),
            'stage': stage(rt, since, now), 'state': rt['state'], 'moved_at': moved_at, 'open_pr': False,
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
        last = dict(db.execute(
            "SELECT slug, MAX(at) FROM events WHERE NOT (action='complexity' AND json_extract(data, '$.gate')='backfill') GROUP BY slug"
        ).fetchall())
        listed = active(ctx, db, ACTIVE_LIMIT)
        for folder in ('tz', 'research', 'plans'):
            for item in listed[folder]:
                rt = item.get('route')
                if not rt or rt['slug'] in seen:
                    continue
                seen.add(rt['slug'])
                since = _mtime(rt.get('artifact') or rt.get('plan_path') or rt.get('research_path')) \
                    if stage(rt, None, now)['group'] == 'wait' else None
                tasks.append(_task(ctx, name, rt, since, now, last.get(rt['slug'])))
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
                tasks.append(_task(ctx, name, rt, datetime.fromisoformat(at), now, last.get(slug)))
    finally:
        db.close()
    return [t for t in tasks if t], None


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


def moved(task: dict, now: datetime) -> bool:
    if task.get('open_pr'):
        return True
    at = task.get('moved_at')
    return bool(at) and datetime.fromisoformat(at) >= now - MOVE_DAYS


def fold(tasks: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    shown = [t for t in tasks if t['stage']['group'] == 'done' or moved(t, now)]
    folded = [t for t in tasks if t['stage']['group'] != 'done' and not moved(t, now)]
    return order(shown, now), order(folded, now)


def cached(state: Path, name: str, ttl: timedelta, fetch: Callable[[], Any], now: datetime,
           fits: Callable[[Any], bool] = lambda value: True) -> dict:
    """{'value', 'at', 'stale'}: cache younger than ttl that fits, else fetch; a failed fetch keeps the old value with the error in 'stale'."""
    path = Path(state) / f'{name}.json'
    old = None
    try:
        old = json.loads(path.read_text(encoding='utf-8'))
        if datetime.fromisoformat(old['at']) >= now - ttl and fits(old['value']):
            return {'value': old['value'], 'at': old['at'], 'stale': None}
    except (OSError, ValueError, KeyError, TypeError):
        old = None
    try:
        value = fetch()
    except Exception as exc:
        if old is None:
            raise
        return {'value': old['value'], 'at': old['at'], 'stale': str(exc) or exc.__class__.__name__}
    record = {'value': value, 'at': now.isoformat(timespec='seconds')}
    atomic_write(path, json.dumps(record, ensure_ascii=False) + '\n')
    return {**record, 'stale': None}


def _gh(run, args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    try:
        proc = run(['gh', *args], capture_output=True, text=True, env=env)
    except OSError as exc:
        raise RuntimeError(f'gh: {exc}') from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or '').strip().splitlines()
        raise RuntimeError(f'gh {args[0]} {args[1]}: {err[0] if err else proc.returncode}')
    return proc


def gh_accounts(run=subprocess.run) -> list[str]:
    try:
        proc = run(['gh', 'auth', 'status'], capture_output=True, text=True)
    except OSError as exc:
        raise RuntimeError(f'gh: {exc}') from exc
    text = (proc.stdout or '') + '\n' + (proc.stderr or '')
    logins = re.findall(r'Logged in to github\.com account (\S+)', text)
    if not logins:
        raise RuntimeError('gh: нет залогиненных аккаунтов github.com')
    return list(dict.fromkeys(logins))


def pull_requests(run=subprocess.run) -> list[dict]:
    found = {}
    for login in gh_accounts(run):
        token = _gh(run, ['auth', 'token', '--user', login]).stdout.strip()
        env = {**os.environ, 'GH_TOKEN': token}
        proc = _gh(run, ['search', 'prs', '--author=@me', '--limit', '100', '--json', PR_FIELDS], env=env)
        for item in json.loads(proc.stdout or '[]'):
            m = PR_KEY_RE.search(item.get('title') or '')
            repo = item.get('repository') or {}
            found.setdefault(item['url'], {
                'key': m[0] if m else None, 'number': item['number'], 'title': item.get('title') or '',
                'repo': repo.get('nameWithOwner') or repo.get('name') or '', 'url': item['url'],
                'state': item.get('state') or '', 'updated': item.get('updatedAt') or ''})
    return sorted(found.values(), key=lambda p: p['updated'], reverse=True)


def merge_prs(tasks: list[dict], prs: list[dict]) -> list[dict]:
    by_key: dict[str, list[dict]] = {}
    for pr in prs:
        if pr['key']:
            by_key.setdefault(pr['key'], []).append(pr)
    known = set()
    for t in tasks:
        own = by_key.get(t.get('key') or '', [])
        t['prs'] = own
        if not own:
            continue
        known.add(t['key'])
        if any(p['state'] == 'open' for p in own):
            t['open_pr'] = True
        else:
            merged = next((p for p in own if p['state'] == 'merged'), None)
            if merged and t['stage']['group'] != 'done':
                since = merged['updated'] and datetime.fromisoformat(merged['updated'].replace('Z', '+00:00'))
                t['stage'] = {'label': 'готово', 'group': 'done',
                              'since': since.isoformat(timespec='seconds') if since else None}
    for key, own in by_key.items():
        if key in known:
            continue
        opened = next((p for p in own if p['state'] == 'open'), None)
        if opened:
            tasks.append({'slug': key.lower(), 'key': key, 'project': opened['repo'].split('/')[-1],
                          'title': opened['title'], 'stage': {'label': '—', 'group': 'work', 'since': None},
                          'state': None, 'moved_at': None, 'open_pr': True, 'prs': own, 'time': None,
                          'links': {'tz': None, 'research': None, 'plan': None}})
    return tasks


def _external(state: Path, name: str, now: datetime, fetch: Callable[[], Any], empty: Any,
              fits: Callable[[Any], bool] = lambda value: True) -> tuple[Any, str | None]:
    try:
        got = cached(state, name, CACHE_TTL, fetch, now, fits)
    except Exception as exc:
        return empty, str(exc) or exc.__class__.__name__
    return got['value'], got['stale']


def jira_accounts() -> dict[str, str]:
    """{account: 'SE GS …'} — the PROJECTS field of every configured Jira account."""
    out = {}
    for acc in sorted(ts.accounts_available()):
        proc = subprocess.run(['bash', '-c', f'source "{ts.INTEGRATIONS}/jira-accounts.sh"; jira_accounts_load; '
                               f'jira_account_field "$1" PROJECTS', '_', acc], capture_output=True, text=True)
        out[acc] = proc.stdout.strip()
    return out


def _issue(issue: dict, url: str) -> dict:
    fields = issue.get('fields') or {}
    return {'status': (fields.get('status') or {}).get('name') or '?', 'summary': fields.get('summary') or '',
            'url': f'{url}/browse/{issue["key"]}'}


def jira_statuses(keys: set[str], call=ts.jira, accounts: dict[str, str] | None = None,
                  base_url: Callable[[str], str] = ts.account_base_url) -> dict[str, dict]:
    accounts = jira_accounts() if accounts is None else accounts
    by_prefix = {prefix: acc for acc, projects in accounts.items() for prefix in projects.split()}
    grouped: dict[str, list[str]] = {}
    for key in sorted(keys):
        acc = by_prefix.get(key.split('-')[0])
        if acc:
            grouped.setdefault(acc, []).append(key)
    out = {}
    for acc, own in grouped.items():
        url = base_url(acc).rstrip('/')
        try:
            issues = call('jira-jql.sh', '--account', acc, f'key in ({", ".join(own)})', 'status,summary')
        except ts.JiraError:
            issues, failed = [], 0
            for key in own:
                try:
                    issues += call('jira-jql.sh', '--account', acc, f'key = {key}', 'status,summary')
                except ts.JiraError:
                    failed += 1
                    if failed == len(own):
                        raise
                    out[key] = {'status': '?', 'summary': '', 'url': f'{url}/browse/{key}'}
        for issue in issues:
            if issue.get('key') in own:
                out[issue['key']] = _issue(issue, url)
    return out


def merge_jira(tasks: list[dict], statuses: dict[str, dict]) -> list[dict]:
    for t in tasks:
        t['jira'] = statuses.get(t.get('key') or '')
    return tasks


def messages(since: datetime, until: datetime) -> tuple[list, dict]:
    """Все свои сообщения Claude Code и pi за период и журнал задач драйвера."""
    return [*human_messages(PROJECTS_ROOT, since, until), *pi_messages(PI_ROOT, since, until)], load_ledger()


def task_time(msgs: list, since: datetime, recent_since: datetime | None = None) -> dict:
    """{key: {total, recent, days: {date: sec}, last}} по правилу интервалов табеля; день по МСК, без переноса выходных.

    recent — секунды с recent_since: по ним ключ без задачи в vault получает строку «—» или остаётся упоминанием."""
    out: dict[str, dict] = {}
    for when, _project, key, seconds in ts.spans([m for m in msgs if m[0] >= since]):
        if not key:
            continue
        rec = out.setdefault(key, {'total': 0, 'recent': 0, 'days': {}, 'last': None})
        day = when.astimezone(ts.MSK).date().isoformat()
        rec['total'] += seconds
        if recent_since is None or when >= recent_since:
            rec['recent'] += seconds
        rec['days'][day] = rec['days'].get(day, 0) + seconds
        rec['last'] = max(rec['last'] or '', when.isoformat(timespec='seconds'))
    return out


def key_pattern(tasks: list[dict]) -> re.Pattern | None:
    prefixes = sorted({t['key'].split('-')[0] for t in tasks if t.get('key')})
    return re.compile(rf"\b(?:{'|'.join(prefixes)})-\d{{1,5}}\b", re.I) if prefixes else None


def collect_time(tasks: list[dict], now: datetime, fetch=messages) -> dict:
    key_re = key_pattern(tasks)
    if key_re is None:
        return {}
    since = now - HISTORY_DAYS
    msgs, ledger = fetch(since, now)
    return task_time(tag_messages(msgs, ledger, since, key_re, project_of), since, now - MOVE_DAYS)


def merge_time(tasks: list[dict], time: dict, now: datetime) -> list[dict]:
    """Сумма по ключу — у строки с самым свежим moved_at, у остальных строк ключа «↑» (shared).

    Ключ без задачи в vault — строка «—», если за MOVE_DAYS по нему не меньше ROW_MIN_SECONDS; иначе это упоминание."""
    by_key = _by_key(tasks, 'time')
    for key, rec in time.items():
        own = by_key.get(key)
        if not own:
            if rec['recent'] >= ROW_MIN_SECONDS:
                tasks.append({'slug': key.lower(), 'key': key, 'project': '—', 'title': key,
                              'stage': {'label': '—', 'group': 'work', 'since': None}, 'state': None,
                              'moved_at': rec['last'], 'open_pr': False, 'prs': [], 'jira': None,
                              'time': {'total': rec['total'], 'days': rec['days']},
                              'links': {'tz': None, 'research': None, 'plan': None}})
            continue
        _share(own, 'time', {'total': rec['total'], 'days': rec['days']})
        for t in own:
            t['moved_at'] = max(t.get('moved_at') or '', rec['last'])
    return tasks


def _by_key(tasks: list[dict], field: str) -> dict[str, list[dict]]:
    by_key: dict[str, list[dict]] = {}
    for t in tasks:
        t[field] = None
        if t.get('key'):
            by_key.setdefault(t['key'], []).append(t)
    return by_key


def _share(rows: list[dict], field: str, value: dict) -> None:
    """Значение — у строки с самым свежим moved_at, у остальных строк того же ключа «↑» (shared)."""
    owner = max(rows, key=lambda t: t.get('moved_at') or '')
    for t in rows:
        t[field] = value if t is owner else {'shared': True}


def token_records(key_re: re.Pattern) -> list[dict]:
    """Записи token-stats.py по всем транскриптам; скилл загружается по пути, пакетом он не является."""
    spec = importlib.util.spec_from_file_location('token_stats', TOKEN_STATS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.scan(PROJECTS_ROOT, key_re, load_ledger())


def task_tokens(records: list[dict], since_day: str) -> dict:
    """{key: {cost, tokens, days: {day: cost}, day_tokens: {day: tokens}}}; по дням — только с since_day, cost и tokens — за всё время."""
    out: dict[str, dict] = {}
    for r in records:
        rec = out.setdefault(r['task'], {'cost': 0.0, 'tokens': 0, 'days': {}, 'day_tokens': {}})
        spent = r['input'] + r['output'] + r['cache_write'] + r['cache_read']
        rec['cost'] += r['cost']
        rec['tokens'] += spent
        if r['day'] >= since_day:
            rec['days'][r['day']] = rec['days'].get(r['day'], 0.0) + r['cost']
            rec['day_tokens'][r['day']] = rec['day_tokens'].get(r['day'], 0) + spent
    return out


def collect_tokens(tasks: list[dict], now: datetime, fetch=token_records) -> dict:
    key_re = key_pattern(tasks)
    if key_re is None:
        return {}
    return task_tokens(fetch(key_re), (now - MOVE_DAYS).strftime('%Y-%m-%d'))


def merge_tokens(tasks: list[dict], tokens: dict) -> list[dict]:
    by_key = _by_key(tasks, 'tokens')
    for key, rec in tokens.items():
        if key in by_key:
            _share(by_key[key], 'tokens', rec)
    return tasks


def _day_range(now: datetime, count: int, end_offset: int = 0) -> list[str]:
    last = now - timedelta(days=end_offset)
    return [(last - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(count - 1, -1, -1)]


def _cost(rec: dict, days: list[str]) -> float:
    return sum(rec['days'].get(d, 0.0) for d in days)


def chart(tokens: dict, now: datetime) -> dict:
    """14 дней × ряды {name, values ($), tokens}: CHART_TOP самых дорогих задач за период, «прочее» при остатке,
    «без задачи» всегда последним."""
    days = _day_range(now, CHART_DAYS)
    tasks = sorted(((k, r) for k, r in tokens.items() if k != NO_TASK), key=lambda kr: -_cost(kr[1], days))

    def series(name: str, recs: list[dict]) -> dict:
        return {'name': name, 'values': [round(sum(r['days'].get(d, 0.0) for r in recs), 4) for d in days],
                'tokens': [sum(r.get('day_tokens', {}).get(d, 0) for r in recs) for d in days]}

    out = [series(k, [r]) for k, r in tasks[:CHART_TOP]]
    if tasks[CHART_TOP:]:
        out.append(series(OTHER, [r for _, r in tasks[CHART_TOP:]]))
    out.append(series(NO_TASK, [tokens.get(NO_TASK, {'days': {}})]))
    return {'days': days, 'series': out}


def facts(tokens: dict, now: datetime) -> dict:
    """{week, prev_week, no_task_pct, week_tokens}: $ за 7 дней, за 7 дней до того, доля «без задачи» и токены за неделю."""
    week, prev = _day_range(now, 7), _day_range(now, 7, 7)
    total = sum(_cost(r, week) for r in tokens.values())
    none = _cost(tokens.get(NO_TASK, {'days': {}}), week)
    return {'week': round(total, 2), 'prev_week': round(sum(_cost(r, prev) for r in tokens.values()), 2),
            'no_task_pct': round(none / total * 100) if total else 0,
            'week_tokens': sum(r.get('day_tokens', {}).get(d, 0) for r in tokens.values() for d in week)}


def limits(now: datetime, path: Path | None = None) -> list[dict]:
    """Окна rate-limits.json → [{window, label, used, cells, resets_at}]; файл отсутствует или устарел → []."""
    path = Path(path or policy.limits_path())
    if policy.limits(path, 100, LIMITS_MAX_AGE_MIN, now.timestamp()) is None:
        return []
    data = json.loads(path.read_text())
    return [{'window': name, 'label': label, 'used': w['used_percentage'], 'cells': round(w['used_percentage'] / 10, 1),
             'resets_at': w.get('resets_at')}
            for name, label in LIMIT_WINDOWS.items()
            if isinstance(w := data.get(name), dict) and isinstance(w.get('used_percentage'), (int, float))]


def build(state: Path, now: datetime | None = None, sources: dict | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    sources = sources or {}
    registry = sources.get('registry') or load_registry(registry_path(ROOT))
    collected = collect_tasks(registry, now)
    try:
        time, time_error = collect_time(collected['tasks'], now, sources.get('messages') or messages), None
    except Exception as exc:
        time, time_error = {}, str(exc) or exc.__class__.__name__
    tasks = merge_time(collected['tasks'], time, now)
    try:
        tokens, tokens_error = collect_tokens(tasks, now, sources.get('token_records') or token_records), None
    except Exception as exc:
        tokens, tokens_error = {}, str(exc) or exc.__class__.__name__
    tasks = merge_tokens(tasks, tokens)
    prs, prs_error = _external(state, 'prs', now, sources.get('pull_requests') or pull_requests, [])
    tasks = merge_prs(tasks, prs)
    keys = {t['key'] for t in tasks if t.get('key')}
    fetch_jira = sources.get('jira_statuses') or jira_statuses
    # Keys are stored with the statuses: a key that appeared after the cache was written forces a new fetch.
    got, jira_error = _external(state, 'jira', now, lambda: {'keys': sorted(keys), 'statuses': fetch_jira(keys)},
                                {}, fits=lambda value: keys <= set(value.get('keys') or []))
    statuses = got.get('statuses') or {}
    shown, folded = fold(merge_jira(tasks, statuses), now)
    snapshot = {'generated': now.isoformat(timespec='seconds'), 'tasks': shown, 'folded': folded,
                'errors': collected['errors'], 'prs_error': prs_error, 'jira_error': jira_error, 'time_error': time_error,
                'tokens_error': tokens_error, 'chart': chart(tokens, now), 'facts': facts(tokens, now), 'limits': limits(now)}
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
