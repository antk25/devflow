import os
import sqlite3
import time

import pytest

from devflow import pi, storage
from devflow.documents import WorkflowError, context
from devflow.storage import connect
from test_pi import approve_research, fake_pi, proj, shared_rules  # noqa: F401

WRITE_RESEARCH = '''#!/usr/bin/env bash
printf '%s\\n' "$@" > "$FAKE_PI_LOG"
[ -n "$FAKE_WRITE" ] && printf '%b' "$FAKE_WRITE" > "$FAKE_TARGET"
echo "отчёт фазы"
exit "${FAKE_PI_EXIT:-0}"
'''


@pytest.fixture
def writer(fake_pi, proj):
    exe = os.path.join(fake_pi['env']['PATH'].split(':')[0], 'pi')
    with open(exe, 'w') as fh:
        fh.write(WRITE_RESEARCH)
    return {**fake_pi['env'], 'FAKE_TARGET': str(proj['vault'] / 'research/x.md')}


def outcomes(db):
    return [dict(r) for r in db.execute('SELECT * FROM outcomes ORDER BY id')]


def test_complete_research_is_ok_and_recorded(proj, writer):
    env = {**writer, 'FAKE_WRITE': '# r\\n\\n## Problem\\nп\\n\\n## Recommendation\\nр\\n'}
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', env=env)
    assert out['status'] == 'ok' and out['artifact'].endswith('research/x.md')
    assert out['route']['state'] == 'approval_required'
    rows = outcomes(proj['db'])
    assert len(rows) == 1 and rows[0]['status'] == 'ok' and rows[0]['harness'] == 'pi' and rows[0]['phase'] == 'research'


def test_torn_research_is_failed_and_recorded(proj, writer):
    env = {**writer, 'FAKE_WRITE': '# r\\n\\n## Problem\\nоборвано', 'FAKE_PI_EXIT': '1'}
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', env=env)
    assert out['status'] == 'failed' and 'Recommendation' in out['reason']
    assert [r['status'] for r in outcomes(proj['db'])] == ['failed']


def test_untouched_or_missing_artifact_is_failed(proj, writer):
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', env=writer)
    assert out['status'] == 'failed' and out['reason'] == 'артефакт не найден'
    path = proj['vault'] / 'research/x.md'
    path.write_text('## Problem\n## Recommendation\n')
    os.utime(path, (time.time() - 100, time.time() - 100))
    assert pi.check_artifact(path, time.time(), ('## Problem',)).startswith('артефакт не изменён')
    assert pi.check_artifact(path, 0, ('## Problem', '## Recommendation')) == 'ok'


def test_every_run_adds_exactly_one_row(proj, writer, monkeypatch):
    pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', env=writer)
    pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', env={**writer, 'FAKE_PI_EXIT': '2'})

    def boom(*a, **k):
        raise OSError('no exec')
    monkeypatch.setattr(pi.subprocess, 'Popen', boom)
    with pytest.raises(WorkflowError):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', env=writer)
    assert len(outcomes(proj['db'])) == 3


def test_unknown_host_is_refused_before_launch(proj, writer):
    with pytest.raises(WorkflowError, match='не подключён'):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', env=writer, host='bb')
    assert outcomes(proj['db']) == []


def test_stale_limits_warn(proj, writer, monkeypatch, tmp_path):
    limits = tmp_path / 'rate-limits.json'
    limits.write_text('{"at": 1}')
    monkeypatch.setattr(pi, 'limits_path', lambda: limits)
    monkeypatch.setattr(pi, 'route', lambda ctx, db, slug: {'state': 'research', 'slug': 'x', 'policy': '/p', 'limits': None})
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', env=writer)
    assert 'limits stale' in out['warning']


def test_version_one_database_is_migrated(proj):
    proj['db'].execute('DROP TABLE outcomes')
    proj['db'].execute('UPDATE project SET schema_version=1')
    db = connect(proj['ctx'])
    try:
        assert db.execute('SELECT schema_version FROM project').fetchone()[0] == storage.SCHEMA_VERSION
        storage.record_outcome(db, 'x', 'plan', 'pi', None, None, 'ok', None, None, None)
        assert len(outcomes(db)) == 1
    finally:
        db.close()


def test_version_two_database_gets_per_task_running_index(proj):
    proj['db'].execute('DROP INDEX single_running_task')
    proj['db'].execute("CREATE UNIQUE INDEX single_running ON runs(status) WHERE status='running'")
    proj['db'].execute('UPDATE project SET schema_version=2')
    db = connect(proj['ctx'])
    try:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert 'single_running_task' in names and 'single_running' not in names
        for slug in ('a-1', 'b-2'):
            db.execute("INSERT INTO runs(id,slug,step_id,step_revision,plan_revision,research_revision,status) "
                       "VALUES (?,?,'s','r','p','q','running')", (slug, slug))
    finally:
        db.close()
