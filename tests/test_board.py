import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from devflow import board, documents
from devflow.transcripts import NO_TASK, Msg
from devflow.documents import context
from devflow.storage import connect, db_path, event

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)

PLAN = '''---
schema: 1
research_revision: {rev}
steps:
  - {{id: one, n: 1, blocked_by: []}}
  - {{id: two, n: 2, blocked_by: [one]}}
  - {{id: three, n: 3, blocked_by: [two]}}
  - {{id: four, n: 4, blocked_by: [three]}}
  - {{id: five, n: 5, blocked_by: [four]}}
---

# Задача X — Plan

## Steps

### one: Первый
- **Acceptance:** а

### two: Второй
- **Acceptance:** б

### three: Третий
- **Acceptance:** в

### four: Четвёртый
- **Acceptance:** г

### five: Пятый
- **Acceptance:** д
'''


def make_project(root: Path, name: str, slug: str, approve_plan=True, done=()):
    vault, cwd = root / f'{name}-vault', root / name
    for d in ('tz', 'plans', 'research', 'changelog'):
        (vault / d).mkdir(parents=True)
    cwd.mkdir()
    (cwd / 'AGENTS.md').write_text(f'---\nproject: {name}\nvault: {vault}\n---\n')
    (vault / f'research/{slug}.md').write_text(f'# {slug.upper()} Задача\n')
    rev = documents.document(vault / f'research/{slug}.md')['revision']
    (vault / f'plans/{slug}.md').write_text(PLAN.format(rev=rev))
    ctx = context(cwd)
    db = connect(ctx, create=True)
    db.execute("INSERT INTO approvals VALUES (?,?,?,?)", (slug, 'research', rev, '2026-09-01T00:00:00+00:00'))
    if approve_plan:
        prev = documents.document(vault / f'plans/{slug}.md')['revision']
        db.execute("INSERT INTO approvals VALUES (?,?,?,?)", (slug, 'plan', prev, '2026-09-01T00:00:00+00:00'))
    for step in documents.plan_steps(documents.document(vault / f'plans/{slug}.md')):
        if step['id'] in done:
            db.execute("INSERT INTO steps VALUES (?,?,?,?,?)", (slug, step['id'], step['revision'], 'done', 'run'))
    db.commit()
    db.close()
    return ctx


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv('DEVFLOW_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(board, 'pull_requests', lambda run=None: [])  # no live gh in tests
    monkeypatch.setattr(board, 'messages', lambda since, until: ([], {}))  # no real transcripts in tests
    monkeypatch.setattr(board, 'token_records', lambda key_re: [])
    return tmp_path


def test_task_key_from_slug_prefix():
    assert board.task_key('df-24-attention-queue') == 'DF-24'
    assert board.task_key('SE-2039-content-access') == 'SE-2039'
    assert board.task_key('neovim-setup-plan') is None


def test_stage_approval_required_is_wait_with_days():
    since = NOW - timedelta(days=2, hours=3)
    st = board.stage({'state': 'approval_required', 'phase': 'research'}, since, NOW)
    assert st == {'label': '⏸ гейт research · 2 д', 'group': 'wait', 'since': since.isoformat(timespec='seconds')}
    assert board.stage({'state': 'plan_outdated', 'phase': 'plan'}, None, NOW)['group'] == 'wait'


def test_stage_ready_shows_step_of_total():
    st = board.stage({'state': 'ready', 'phase': 'implement', 'n': 2, 'total': 5}, None, NOW)
    assert st == {'label': 'implement 2/5', 'group': 'work', 'since': None}
    assert board.stage({'state': 'research', 'phase': 'research'}, None, NOW)['label'] == 'research'
    assert board.stage({'state': 'completed'}, None, NOW) == {'label': 'готово', 'group': 'done', 'since': None}


def task(slug, group, since=None, project='p'):
    return {'slug': slug, 'project': project, 'stage': {'group': group, 'since': since and since.isoformat(timespec='seconds')}}


def test_order_wait_first_oldest_on_top_then_work_then_fresh_done():
    tasks = [task('work-1', 'work'), task('done-old', 'done', NOW - timedelta(days=8)),
             task('done-new', 'done', NOW - timedelta(days=1)), task('done-older', 'done', NOW - timedelta(days=3)),
             task('wait-new', 'wait', NOW - timedelta(days=1)), task('wait-old', 'wait', NOW - timedelta(days=30))]
    assert [t['slug'] for t in board.order(tasks, NOW)] == ['wait-old', 'wait-new', 'work-1', 'done-new', 'done-older']


def test_project_tasks_reads_stage_without_touching_the_database(root):
    ctx = make_project(root, 'p', 'ab-1-task', done=('one',))
    db = connect(ctx)
    db.execute('BEGIN IMMEDIATE')
    event(db, 'finish', 'xx-9-old', status='done')
    db.execute("UPDATE events SET at=?", ((NOW - timedelta(days=1)).isoformat(timespec='seconds'),))
    db.execute('COMMIT')
    rows = db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
    db.close()
    path = db_path(ctx)[0]
    before = path.stat().st_mtime_ns
    time.sleep(0.01)

    tasks, error = board.project_tasks('p', ctx['cwd'], NOW)

    assert error is None
    assert [(t['key'], t['stage']) for t in tasks] == [('AB-1', {'label': 'implement 2/5', 'group': 'work', 'since': None})]
    assert tasks[0]['links']['plan'].endswith('plans/ab-1-task.md')
    db = connect(ctx)
    assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == rows
    db.close()
    assert path.stat().st_mtime_ns == before


def test_project_tasks_wait_days_from_gate_artifact_mtime(root):
    ctx = make_project(root, 'p', 'ab-2-task', approve_plan=False)
    plan = ctx['vault'] / 'plans/ab-2-task.md'
    stamp = (NOW - timedelta(days=4)).timestamp()
    os.utime(plan, (stamp, stamp))
    tasks, _ = board.project_tasks('p', ctx['cwd'], NOW)
    assert tasks[0]['stage']['label'] == '⏸ гейт plan · 4 д'
    assert tasks[0]['stage']['group'] == 'wait'


def test_project_tasks_lists_tasks_finished_within_seven_days(root):
    ctx = make_project(root, 'p', 'ab-3-task', done=('one', 'two', 'three', 'four', 'five'))
    db = connect(ctx)
    db.execute('BEGIN IMMEDIATE')
    event(db, 'finish', 'ab-3-task', status='done')
    db.execute("UPDATE events SET at=?", ((NOW - timedelta(days=2)).isoformat(timespec='seconds'),))
    db.execute('COMMIT')
    db.close()
    tasks, _ = board.project_tasks('p', ctx['cwd'], NOW)
    assert [(t['key'], t['stage']['label'], t['stage']['group']) for t in tasks] == [('AB-3', 'готово', 'done')]
    assert tasks[0]['stage']['since'] == (NOW - timedelta(days=2)).isoformat(timespec='seconds')


def test_collect_tasks_reports_broken_project_and_keeps_the_rest(root):
    ctx = make_project(root, 'ok', 'ab-1-task')
    broken = root / 'broken'
    broken.mkdir()
    (broken / 'AGENTS.md').write_text(f'---\nproject: broken\nvault: {root}/missing-vault\n---\n')
    (root / 'noinit').mkdir()
    registry = {'projects': {'ok': {'path': str(ctx['cwd'])}, 'broken': {'path': str(broken)},
                             'noinit': {'path': str(root / 'noinit')}}}
    result = board.collect_tasks(registry, NOW)
    assert [t['slug'] for t in result['tasks']] == ['ab-1-task']
    assert len(result['errors']) == 2
    assert result['errors'][0].startswith('broken: ')
    assert 'noinit' in result['errors'][1]


def test_build_writes_snapshot_and_load_reads_it_back(root):
    ctx = make_project(root, 'p', 'ab-1-task')
    set_events(ctx, 'ab-1-task', stamp(timedelta(days=1)))
    state = root / 'board'
    snap = board.build(state, NOW, sources={'registry': {'projects': {'p': {'path': str(ctx['cwd'])}}}})
    assert snap['generated'] == NOW.isoformat(timespec='seconds')
    assert snap['tasks'][0]['key'] == 'AB-1'
    assert board.load(state) == snap
    assert json.loads((state / 'snapshot.json').read_text())['errors'] == []
    assert board.load(root / 'nowhere') is None


def stamp(delta):
    return (NOW - delta).isoformat(timespec='seconds')


def set_events(ctx, slug, at, action='approve', **data):
    db = connect(ctx)
    db.execute('BEGIN IMMEDIATE')
    event(db, action, slug, **(data or {'phase': 'research'}))
    db.execute("UPDATE events SET at=? WHERE slug=? AND at>?", (at, slug, at))
    db.execute('COMMIT')
    db.close()


def test_project_tasks_moved_at_is_the_last_event_of_the_slug(root):
    ctx = make_project(root, 'p', 'ab-1-task')
    set_events(ctx, 'ab-1-task', stamp(timedelta(days=3)))
    tasks, _ = board.project_tasks('p', ctx['cwd'], NOW)
    assert tasks[0]['moved_at'] == stamp(timedelta(days=3))
    assert tasks[0]['open_pr'] is False


def test_project_tasks_moved_at_skips_complexity_backfill(root):
    ctx = make_project(root, 'p', 'ab-1-task')
    set_events(ctx, 'ab-1-task', stamp(timedelta(days=15)))
    set_events(ctx, 'ab-1-task', stamp(timedelta(days=2)), 'complexity', value='low', gate='backfill', source='jev')
    tasks, _ = board.project_tasks('p', ctx['cwd'], NOW)
    assert tasks[0]['moved_at'] == stamp(timedelta(days=15))
    assert board.fold(tasks, NOW)[0] == []
    set_events(ctx, 'ab-1-task', stamp(timedelta(days=1)), 'complexity', value='low', gate='research', source='user')
    assert board.project_tasks('p', ctx['cwd'], NOW)[0][0]['moved_at'] == stamp(timedelta(days=1))


def test_project_tasks_hides_tz_with_status_obsolete_or_done(root):
    ctx = make_project(root, 'p', 'ab-1-task')
    (ctx['vault'] / 'tz/ab-1-task.md').write_text('---\nstatus: obsolete\n---\n# Старое\n')
    assert board.project_tasks('p', ctx['cwd'], NOW)[0] == []
    (ctx['vault'] / 'tz/ab-1-task.md').write_text('---\nstatus: done\n---\n# Сделано\n')
    assert board.project_tasks('p', ctx['cwd'], NOW)[0] == []
    (ctx['vault'] / 'tz/ab-1-task.md').write_text('---\nstatus: active\n---\n# Живое\n')
    assert [t['slug'] for t in board.project_tasks('p', ctx['cwd'], NOW)[0]] == ['ab-1-task']


def moving(slug, group='work', moved_at=None, open_pr=False, since=None):
    return dict(task(slug, group, since), moved_at=moved_at, open_pr=open_pr)


def test_fold_by_events_open_pr_and_fresh_done():
    tasks = [moving('fresh', moved_at=stamp(timedelta(days=3))),
             moving('stale', moved_at=stamp(timedelta(days=15))),
             moving('never'),
             moving('pr-only', open_pr=True),
             moving('done-new', 'done', since=NOW - timedelta(days=3)),
             moving('done-old', 'done', since=NOW - timedelta(days=10))]
    shown, folded = board.fold(tasks, NOW)
    assert [t['slug'] for t in shown] == ['fresh', 'pr-only', 'done-new']
    assert [t['slug'] for t in folded] == ['never', 'stale']


def test_fold_ignores_fresh_mtime_of_artifacts(root):
    ctx = make_project(root, 'p', 'ab-1-task')
    set_events(ctx, 'ab-1-task', stamp(timedelta(days=20)))
    for f in ('research/ab-1-task.md', 'plans/ab-1-task.md'):
        os.utime(ctx['vault'] / f, None)
    (ctx['vault'] / 'tz/ab-1-task.md').write_text('# ТЗ\n')
    tasks, _ = board.project_tasks('p', ctx['cwd'], NOW)
    shown, folded = board.fold(tasks, NOW)
    assert shown == [] and [t['slug'] for t in folded] == ['ab-1-task']


def test_build_snapshot_has_folded_count_for_the_page(root):
    ctx = make_project(root, 'p', 'ab-1-task')
    set_events(ctx, 'ab-1-task', stamp(timedelta(days=15)))
    snap = board.build(root / 'board', NOW, sources={'registry': {'projects': {'p': {'path': str(ctx['cwd'])}}}})
    assert snap['tasks'] == []
    assert len(snap['folded']) == 1 and snap['folded'][0]['slug'] == 'ab-1-task'


GH_STATUS = '''github.com
  ✓ Logged in to github.com account antk25 (/home/x/hosts.yml)
  - Active account: true
  ✓ Logged in to github.com account antonResolventa (/home/x/hosts.yml)
  - Active account: false
'''


class FakeRun:
    def __init__(self, prs_by_login):
        self.prs_by_login, self.calls = prs_by_login, []

    def __call__(self, cmd, capture_output=True, text=True, env=None):
        self.calls.append((cmd, env))
        out = ''
        if cmd[:3] == ['gh', 'auth', 'status']:
            out = GH_STATUS
        elif cmd[:3] == ['gh', 'auth', 'token']:
            out = f'tok-{cmd[4]}\n'
        elif cmd[:3] == ['gh', 'search', 'prs']:
            login = env['GH_TOKEN'].removeprefix('tok-')
            out = json.dumps(self.prs_by_login[login])
        return type('P', (), {'returncode': 0, 'stdout': out, 'stderr': ''})()


def pr(number, title, state, repo='MeshNordicAI/meshnordic-search', days=1):
    return {'number': number, 'title': title, 'state': state, 'url': f'https://github.com/{repo}/pull/{number}',
            'repository': {'name': repo.split('/')[-1], 'nameWithOwner': repo},
            'updatedAt': (NOW - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')}


def test_gh_accounts_parses_both_logins():
    assert board.gh_accounts(FakeRun({})) == ['antk25', 'antonResolventa']


def test_pull_requests_passes_token_per_account_and_keeps_merged_state():
    run = FakeRun({'antk25': [pr(12, 'DF-20: reader', 'merged', 'antk25/devflow'), pr(1, 'Release', 'merged')],
                   'antonResolventa': [pr(2111, 'SE-2148 Repoint variants', 'open'), pr(12, 'DF-20: reader', 'merged', 'antk25/devflow')]})
    prs = board.pull_requests(run)
    searches = [(cmd, env) for cmd, env in run.calls if cmd[1] == 'search']
    assert [env['GH_TOKEN'] for _, env in searches] == ['tok-antk25', 'tok-antonResolventa']
    assert {(p['key'], p['state']) for p in prs} == {('DF-20', 'merged'), (None, 'merged'), ('SE-2148', 'open')}
    assert len([p for p in prs if p['number'] == 12]) == 1
    assert next(p for p in prs if p['key'] == 'SE-2148')['repo'] == 'MeshNordicAI/meshnordic-search'


def test_pull_requests_reports_gh_failure():
    def failing(cmd, **kw):
        return type('P', (), {'returncode': 1, 'stdout': '', 'stderr': 'You are not logged into any GitHub hosts\n'})()
    with pytest.raises(RuntimeError, match='нет залогиненных'):
        board.pull_requests(failing)


def test_merge_prs_merged_pr_moves_waiting_task_to_done_and_release_adds_no_row():
    tasks = [moving('df-20-reader', 'wait', since=NOW - timedelta(days=5)) | {'key': 'DF-20'},
             moving('df-16-ts', 'work') | {'key': 'DF-16'}]
    tasks[0]['stage']['label'] = '⏸ гейт research · 5 д'
    prs = [{'key': None, 'number': 1, 'title': 'Release', 'state': 'merged', 'repo': 'o/r', 'url': 'u1', 'updated': stamp(timedelta(days=1))},
           {'key': 'DF-20', 'number': 12, 'title': 'DF-20: reader', 'state': 'merged', 'repo': 'o/r', 'url': 'u2', 'updated': '2026-09-29T10:00:00Z'},
           {'key': 'DF-16', 'number': 7, 'title': 'DF-16 ts', 'state': 'merged', 'repo': 'o/r', 'url': 'u3', 'updated': stamp(timedelta(days=5))},
           {'key': 'DF-16', 'number': 6, 'title': 'DF-16 ts', 'state': 'closed', 'repo': 'o/r', 'url': 'u4', 'updated': stamp(timedelta(days=6))},
           {'key': 'SE-9', 'number': 3, 'title': 'SE-9 new', 'state': 'open', 'repo': 'o/green', 'url': 'u5', 'updated': stamp(timedelta(days=1))}]
    out = board.merge_prs(tasks, prs)
    assert out[0]['stage'] == {'label': 'готово', 'group': 'done', 'since': '2026-09-29T10:00:00+00:00'}
    assert out[1]['stage']['group'] == 'done' and [p['number'] for p in out[1]['prs']] == [7, 6]
    assert [(t['key'], t['stage']['label'], t['project'], t['open_pr']) for t in out[2:]] == [('SE-9', '—', 'green', True)]


def test_fold_after_merge_open_pr_shows_stale_task_closed_pr_does_not():
    tasks = [moving('aa-1-x', 'work') | {'key': 'AA-1'}, moving('aa-2-y', 'work') | {'key': 'AA-2'}]
    prs = [{'key': 'AA-1', 'number': 1, 'title': 'AA-1', 'state': 'open', 'repo': 'o/r', 'url': 'u1', 'updated': stamp(timedelta(days=1))},
           {'key': 'AA-2', 'number': 2, 'title': 'AA-2', 'state': 'closed', 'repo': 'o/r', 'url': 'u2', 'updated': stamp(timedelta(days=1))}]
    shown, folded = board.fold(board.merge_prs(tasks, prs), NOW)
    assert [t['slug'] for t in shown] == ['aa-1-x'] and [t['slug'] for t in folded] == ['aa-2-y']


def test_cached_skips_fetch_within_ttl_and_keeps_stale_value_on_error(root):
    calls = []
    fetch = lambda: calls.append(1) or ['pr']
    assert board.cached(root, 'prs', timedelta(minutes=10), fetch, NOW)['value'] == ['pr']
    later = board.cached(root, 'prs', timedelta(minutes=10), fetch, NOW + timedelta(minutes=9))
    assert later['value'] == ['pr'] and later['stale'] is None and len(calls) == 1
    def boom():
        raise RuntimeError('gh: нет сети')
    stale = board.cached(root, 'prs', timedelta(minutes=10), boom, NOW + timedelta(minutes=11))
    assert stale == {'value': ['pr'], 'at': NOW.isoformat(timespec='seconds'), 'stale': 'gh: нет сети'}
    with pytest.raises(RuntimeError):
        board.cached(root, 'other', timedelta(minutes=10), boom, NOW)


def test_build_puts_gh_error_in_snapshot_and_leaves_column_empty(root):
    ctx = make_project(root, 'p', 'ab-1-task')
    set_events(ctx, 'ab-1-task', stamp(timedelta(days=1)))
    def boom():
        raise RuntimeError('gh: нет аккаунта')
    snap = board.build(root / 'board', NOW, sources={'registry': {'projects': {'p': {'path': str(ctx['cwd'])}}}, 'pull_requests': boom})
    assert snap['prs_error'] == 'gh: нет аккаунта' and snap['tasks'][0]['prs'] == []


def issue(key, status, summary='x'):
    return {'key': key, 'fields': {'status': {'name': status}, 'summary': summary}}


class FakeJira:
    def __init__(self, fail_batch=(), fail_keys=()):
        self.calls, self.fail_batch, self.fail_keys = [], set(fail_batch), set(fail_keys)

    def __call__(self, script, _opt, account, jql, fields):
        self.calls.append((account, jql, fields))
        keys = [k.strip() for k in jql.split('(')[1].rstrip(')').split(',')] if 'in (' in jql else [jql.split('=')[1].strip()]
        if len(keys) > 1 and account in self.fail_batch:
            raise board.ts.JiraError('400 jql')
        if keys[0] in self.fail_keys:
            raise board.ts.JiraError('404 ' + keys[0])
        return [issue(k, 'In Progress') for k in keys]


ACCOUNTS = {'productsearch': 'SE', 'resolventa': 'GS CAP'}


def test_jira_statuses_one_call_per_account_and_skips_keys_without_account():
    call = FakeJira()
    out = board.jira_statuses({'SE-2039', 'SE-1', 'GS-7', 'DF-24'}, call, ACCOUNTS, lambda acc: f'https://{acc}.atlassian.net/')
    assert {(acc, jql) for acc, jql, _ in call.calls} == {('productsearch', 'key in (SE-1, SE-2039)'), ('resolventa', 'key in (GS-7)')}
    assert set(out) == {'SE-2039', 'SE-1', 'GS-7'}
    assert out['SE-2039'] == {'status': 'In Progress', 'summary': 'x', 'url': 'https://productsearch.atlassian.net/browse/SE-2039'}


def test_jira_statuses_without_known_prefixes_makes_no_call():
    call = FakeJira()
    assert board.jira_statuses({'DF-24', 'XX-1'}, call, ACCOUNTS, lambda acc: '') == {} and call.calls == []


def test_jira_statuses_batch_error_retries_per_key_and_marks_failed_key():
    call = FakeJira(fail_batch={'productsearch'}, fail_keys={'SE-2'})
    out = board.jira_statuses({'SE-1', 'SE-2'}, call, ACCOUNTS, lambda acc: 'https://j')
    assert [jql for _, jql, _ in call.calls] == ['key in (SE-1, SE-2)', 'key = SE-1', 'key = SE-2']
    assert out['SE-1']['status'] == 'In Progress' and out['SE-2'] == {'status': '?', 'summary': '', 'url': 'https://j/browse/SE-2'}


def test_build_jira_statuses_land_on_tasks_and_repeat_within_ten_minutes_uses_cache(root):
    ctx = make_project(root, 'p', 'se-1-task')
    set_events(ctx, 'se-1-task', stamp(timedelta(days=1)))
    calls = []
    def fetch(keys):
        calls.append(keys)
        return {'SE-1': {'status': 'Review', 'summary': 's', 'url': 'https://j/browse/SE-1'}}
    sources = {'registry': {'projects': {'p': {'path': str(ctx['cwd'])}}}, 'jira_statuses': fetch}
    snap = board.build(root / 'board', NOW, sources=sources)
    assert snap['tasks'][0]['jira']['status'] == 'Review' and snap['jira_error'] is None and calls == [{'SE-1'}]
    again = board.build(root / 'board', NOW + timedelta(minutes=9), sources=sources)
    assert again['tasks'][0]['jira']['status'] == 'Review' and len(calls) == 1


def test_build_puts_jira_error_in_snapshot(root):
    ctx = make_project(root, 'p', 'se-1-task')
    set_events(ctx, 'se-1-task', stamp(timedelta(days=1)))
    def boom(keys):
        raise board.ts.JiraError('401 Unauthorized')
    snap = board.build(root / 'board', NOW, sources={'registry': {'projects': {'p': {'path': str(ctx['cwd'])}}}, 'jira_statuses': boom})
    assert snap['jira_error'] == '401 Unauthorized' and snap['tasks'][0]['jira'] is None


def msg(delta, text, session='s1', cwd='/home/u/projects/green'):
    return Msg(NOW - delta, cwd, session, text)


def test_task_time_sums_gaps_with_tail_and_drops_messages_without_key():
    since = NOW - timedelta(days=90)
    msgs = [msg(timedelta(minutes=30), 'сделай AB-1'), msg(timedelta(minutes=20), 'дальше'),
            msg(timedelta(hours=3), 'без ключа', session='s2')]
    time = board.task_time(board.tag_messages(msgs, {}, since, board.re.compile(r'\bAB-\d+\b', board.re.I),
                                              board.project_of), since)
    assert time == {'AB-1': {'total': 600 + 450, 'recent': 1050, 'days': {'2026-10-02': 1050},
                             'last': stamp(timedelta(minutes=20))}}


def test_task_time_recent_counts_only_seconds_after_recent_since():
    since = NOW - timedelta(days=90)
    msgs = [msg(timedelta(days=20), 'AB-1 старое'), msg(timedelta(days=2), 'AB-1 свежее', session='s2')]
    tagged = board.tag_messages(msgs, {}, since, board.re.compile(r'\bAB-\d+\b', board.re.I), board.project_of)
    time = board.task_time(tagged, since, NOW - board.MOVE_DAYS)
    assert time['AB-1']['total'] == 900 and time['AB-1']['recent'] == 450


def test_build_activity_by_key_moves_task_and_folds_old_activity(root):
    ctx = make_project(root, 'p', 'ab-1-task')
    set_events(ctx, 'ab-1-task', stamp(timedelta(days=20)))
    reg = {'registry': {'projects': {'p': {'path': str(ctx['cwd'])}}}}
    fresh = lambda since, until: ([msg(timedelta(days=2), 'продолжаем AB-1')], {})
    snap = board.build(root / 'board', NOW, sources={**reg, 'messages': fresh})
    assert [t['slug'] for t in snap['tasks']] == ['ab-1-task']
    assert snap['tasks'][0]['time'] == {'total': 450, 'days': {'2026-09-30': 450}}
    assert snap['tasks'][0]['moved_at'] == stamp(timedelta(days=2))
    old = lambda since, until: ([msg(timedelta(days=20), 'продолжаем AB-1')], {})
    snap = board.build(root / 'board', NOW, sources={**reg, 'messages': old})
    assert snap['tasks'] == [] and [t['slug'] for t in snap['folded']] == ['ab-1-task']


def test_merge_time_shared_key_shows_sum_on_freshest_row_and_arrow_on_the_rest():
    tasks = [moving('se-2186-one', moved_at=stamp(timedelta(days=5))), moving('se-2186-two', moved_at=stamp(timedelta(days=1)))]
    for t in tasks:
        t['key'] = 'SE-2186'
    time = {'SE-2186': {'total': 900, 'days': {'2026-10-01': 900}, 'last': stamp(timedelta(days=1))}}
    out = board.merge_time(tasks, time, NOW)
    assert out[0]['time'] == {'shared': True}
    assert out[1]['time'] == {'total': 900, 'days': {'2026-10-01': 900}}


def test_merge_time_key_without_task_becomes_row_only_from_thirty_minutes_in_fourteen_days():
    time = {'ZZ-1': {'total': 3 * 3600, 'recent': 20 * 60, 'days': {}, 'last': stamp(timedelta(days=3))},
            'ZZ-2': {'total': 40 * 60, 'recent': 40 * 60, 'days': {}, 'last': stamp(timedelta(days=3))}}
    out = board.merge_time([], time, NOW)
    assert [t['key'] for t in out] == ['ZZ-2'] and out[0]['stage']['label'] == '—'


def _key_only_messages(minutes):
    return lambda since, until: ([msg(timedelta(days=3, minutes=minutes - i * 10), f'ZZ-7 шаг {i}')
                                  for i in range(minutes // 10 + 1)], {})


def test_build_key_without_task_needs_thirty_minutes_of_recent_activity(root):
    ctx = make_project(root, 'p', 'zz-1-task')
    reg = {'registry': {'projects': {'p': {'path': str(ctx['cwd'])}}}}
    snap = board.build(root / 'board', NOW, sources={**reg, 'messages': _key_only_messages(20)})
    assert 'ZZ-7' not in {t['key'] for t in snap['tasks'] + snap['folded']}
    snap = board.build(root / 'board', NOW, sources={**reg, 'messages': _key_only_messages(40)})
    row = next(t for t in snap['tasks'] if t['key'] == 'ZZ-7')
    assert row['stage']['label'] == '—' and row['time']['total'] == 40 * 60 + 450


def test_build_key_only_row_gets_merged_pr_and_jira_status(root):
    ctx = make_project(root, 'p', 'zz-1-task')
    prs = lambda: [{'key': 'ZZ-7', 'number': 4, 'title': 'ZZ-7 fix', 'state': 'merged', 'repo': 'o/r', 'url': 'u',
                    'updated': '2026-10-01T10:00:00Z'}]
    jira = lambda keys: {'ZZ-7': {'status': 'Done', 'summary': 's', 'url': 'https://j/browse/ZZ-7'}} if 'ZZ-7' in keys else {}
    snap = board.build(root / 'board', NOW, sources={'registry': {'projects': {'p': {'path': str(ctx['cwd'])}}},
                                                     'messages': _key_only_messages(40), 'pull_requests': prs, 'jira_statuses': jira})
    row = next(t for t in snap['tasks'] if t['key'] == 'ZZ-7')
    assert row['stage'] == {'label': 'готово', 'group': 'done', 'since': '2026-10-01T10:00:00+00:00'}
    assert row['jira']['status'] == 'Done' and [p['number'] for p in row['prs']] == [4]


def rec(task, day, cost, tokens=(10, 5, 0, 0)):
    i, o, cw, cr = tokens
    return {'task': task, 'day': day, 'cost': cost, 'input': i, 'output': o, 'cache_write': cw, 'cache_read': cr}


def test_task_tokens_three_keys_sums_match_and_old_days_count_only_in_totals():
    records = [rec('AB-1', '2026-10-01', 1.5, (100, 10, 20, 30)), rec('AB-1', '2026-09-01', 2.0, (1, 1, 1, 1)),
               rec('AB-2', '2026-09-30', 0.25), rec(NO_TASK, '2026-10-02', 0.75)]
    tokens = board.task_tokens(records, '2026-09-18')
    assert set(tokens) == {'AB-1', 'AB-2', NO_TASK}
    assert tokens['AB-1'] == {'cost': 3.5, 'tokens': 164, 'days': {'2026-10-01': 1.5}}
    assert tokens['AB-2']['cost'] == 0.25 and tokens[NO_TASK]['cost'] == 0.75
    assert sum(t['cost'] for t in tokens.values()) == sum(r['cost'] for r in records)


def test_merge_tokens_shared_key_shows_sum_on_freshest_row_and_arrow_on_the_rest():
    tasks = [moving('se-2186-one', moved_at=stamp(timedelta(days=5))), moving('se-2186-two', moved_at=stamp(timedelta(days=1)))]
    for t in tasks:
        t['key'] = 'SE-2186'
    out = board.merge_tokens(tasks, {'SE-2186': {'cost': 4.2, 'tokens': 3_100_000, 'days': {}}})
    assert out[0]['tokens'] == {'shared': True}
    assert out[1]['tokens'] == {'cost': 4.2, 'tokens': 3_100_000, 'days': {}}


def test_build_tokens_land_on_tasks_and_key_only_rows(root):
    ctx = make_project(root, 'p', 'zz-1-task')
    fetch = lambda key_re: [rec('ZZ-1', '2026-10-01', 1.0), rec('ZZ-7', '2026-10-01', 2.0), rec(NO_TASK, '2026-10-01', 3.0)]
    snap = board.build(root / 'board', NOW, sources={'registry': {'projects': {'p': {'path': str(ctx['cwd'])}}},
                                                     'messages': _key_only_messages(40), 'token_records': fetch})
    by_key = {t['key']: t for t in snap['tasks'] + snap['folded']}
    assert by_key['ZZ-1']['tokens']['cost'] == 1.0 and by_key['ZZ-7']['tokens']['cost'] == 2.0
    assert snap['tokens_error'] is None


def test_build_puts_tokens_error_in_snapshot(root):
    ctx = make_project(root, 'p', 'zz-1-task')
    def boom(key_re):
        raise RuntimeError('scan failed')
    snap = board.build(root / 'board', NOW, sources={'registry': {'projects': {'p': {'path': str(ctx['cwd'])}}}, 'token_records': boom})
    assert snap['tokens_error'] == 'scan failed' and all(t['tokens'] is None for t in snap['tasks'] + snap['folded'])
