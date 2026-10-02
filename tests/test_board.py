import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from devflow import board, documents
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
