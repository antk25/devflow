import io
import json
import sys

import pytest

from devflow import cli, documents, jev, policy, workflow
from devflow.documents import WorkflowError, context
from devflow.storage import connect

TZ = '# ТЗ X\n\nСделать выгрузку, ключ password=hunter2 в конфиге.\n'
RESEARCH = '# r\n\n## Problem\np\n\n## Requirements\n- Отчёт в CSV (ТЗ)\n- Токен token=s3cr3t-value (ТЗ)\n\n## Recommendation\nr\n'


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fail(*a, **k):
    raise AssertionError('urlopen не должен вызываться')


def answers(unclear=0.8, wide=0.7, choice='high', sent=None, extra=None):
    def ok(req, timeout):
        body = json.loads(req.data)
        if sent is not None:
            sent.append(body)
        level = {'type': 'choice', 'choice': choice, **(extra or {})}
        a = {'unclear': {'type': 'noul', 'noul': unclear}, 'wide': {'type': 'noul', 'noul': wide}, 'level': level}
        return Resp(json.dumps({'model': 'typesafe/jev-1.13-x', 'answers': a}).encode())
    return ok


EXAMPLE = documents.Path(__file__).resolve().parents[1] / 'model-policy.example.json'


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv('DEVFLOW_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(EXAMPLE))
    monkeypatch.setenv('OPENROUTER_API_KEY', 'dummy-key')
    monkeypatch.setattr(jev.urllib.request, 'urlopen', fail)
    vault, cwd = tmp_path / 'vault', tmp_path / 'proj'
    for d in ('plans', 'research', 'changelog'):
        (vault / d).mkdir(parents=True)
    cwd.mkdir()
    (cwd / 'AGENTS.md').write_text(f'---\nproject: p\nvault: {vault}\njev: true\n---\n')
    (vault / 'research/x.md').write_text(RESEARCH)
    (vault / 'tz').mkdir()
    (vault / 'tz/x.md').write_text(TZ)
    ctx = context(cwd)
    db = connect(ctx, create=True)
    workflow.approve(ctx, db, 'x', 'research', documents.document(vault / 'research/x.md')['revision'])
    yield {'ctx': ctx, 'db': db}
    db.close()


def events(db, slug):
    return [json.loads(r['data']) for r in db.execute("SELECT data FROM events WHERE slug=? AND action='complexity' ORDER BY id", (slug,))]


def test_show_without_events(proj):
    out = workflow.complexity(proj['ctx'], proj['db'], 'x')
    assert out['slug'] == 'x' and out['user'] is None and out['jev'] is None and out['facts']['runs'] == 0
    assert workflow.route(proj['ctx'], proj['db'], 'x')['complexity'] is None


def test_set_high_records_event_and_route_uses_it(proj, monkeypatch):
    monkeypatch.setattr(jev.urllib.request, 'urlopen', answers())
    out = workflow.complexity(proj['ctx'], proj['db'], 'x', 'high', 'research')
    assert out['user']['value'] == 'high' and out['user']['gate'] == 'research' and out['user']['at']
    assert out['jev']['choice'] == 'high' and out['jev']['applied'] is False
    assert events(proj['db'], 'x')[0] == {'value': 'high', 'gate': 'research', 'source': 'user', 'applied': True}
    route = workflow.route(proj['ctx'], proj['db'], 'x')
    assert route['state'] == 'plan'
    assert route['complexity']['value'] == 'high' and route['complexity']['gate'] == 'research'
    assert route['launch']['claude']['effort'] == 'high'


def test_second_set_appends_event(proj):
    workflow.complexity(proj['ctx'], proj['db'], 'x', 'high', 'research', shadow=False)
    out = workflow.complexity(proj['ctx'], proj['db'], 'x', 'medium', 'plan', shadow=False)
    assert out['user']['value'] == 'medium' and out['user']['gate'] == 'plan'
    assert [e['value'] for e in events(proj['db'], 'x')] == ['high', 'medium']
    assert workflow.route(proj['ctx'], proj['db'], 'x')['launch']['claude']['effort'] == 'medium'


def test_route_ignores_non_user_events(proj):
    from devflow.storage import event, transaction
    with transaction(proj['db']):
        event(proj['db'], 'complexity', 'x', value='high', gate='research', source='jev', applied=False)
    assert workflow.route(proj['ctx'], proj['db'], 'x')['complexity'] is None
    out = workflow.complexity(proj['ctx'], proj['db'], 'x')
    assert out['user'] is None and out['jev']['value'] == 'high'


def test_set_validates_value_and_gate(proj):
    with pytest.raises(WorkflowError, match='Complexity'):
        workflow.complexity(proj['ctx'], proj['db'], 'x', 'huge', 'research')
    with pytest.raises(WorkflowError, match='--gate'):
        workflow.complexity(proj['ctx'], proj['db'], 'x', 'high', None)
    assert events(proj['db'], 'x') == []


def test_shadow_writes_jev_event_and_masks_secrets(proj, monkeypatch):
    sent = []
    monkeypatch.setattr(jev.urllib.request, 'urlopen', answers(sent=sent, extra={'confidence': 0.61}))
    workflow.complexity(proj['ctx'], proj['db'], 'x', 'high', 'research')
    user, shadow = events(proj['db'], 'x')
    assert user['source'] == 'user' and user['applied'] is True
    assert shadow['source'] == 'jev' and shadow['applied'] is False and shadow['gate'] == 'research'
    assert shadow['noul'] == {'unclear': 0.8, 'wide': 0.7} and shadow['choice'] == 'high' and shadow['value'] == 'high'
    assert shadow['confidence'] == 0.61 and shadow['model'] == 'typesafe/jev-1.13-x' and shadow['error'] is None
    assert shadow['sources'] == ['tz', 'requirements'] and shadow['input_chars'] > 0 and shadow['latency_ms'] >= 0
    assert set(sent[0]['questions']) == {'unclear', 'wide', 'level'}
    assert sent[0]['questions']['level']['type'] == 'choice' and set(sent[0]['questions']['level']['criteria']) == {'high', 'medium', 'low'}
    raw = json.dumps(sent[0], ensure_ascii=False)
    assert 'hunter2' not in raw and 's3cr3t' not in raw
    assert set(sent[0]['state']) == {'tz', 'requirements'}
    assert 'Отчёт в CSV' in sent[0]['state']['requirements'] and 'Recommendation' not in sent[0]['state']['requirements']


def test_confidence_falls_back_to_probabilities(proj, monkeypatch):
    monkeypatch.setattr(jev.urllib.request, 'urlopen', answers(choice='low', extra={'probabilities': {'low': 0.55}}))
    out = workflow.complexity(proj['ctx'], proj['db'], 'x', 'low', 'plan')
    assert out['jev']['choice'] == 'low' and out['jev']['confidence'] == 0.55


def test_shadow_without_key_records_error(proj, monkeypatch, capsys):
    monkeypatch.delenv('OPENROUTER_API_KEY')
    monkeypatch.setattr(sys, 'argv', ['devflow', '--cwd', str(proj['ctx']['cwd']), 'complexity', 'x', '--set', 'high', '--gate', 'research'])
    assert cli.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out['user']['value'] == 'high'
    user, shadow = events(proj['db'], 'x')
    assert user['source'] == 'user'
    assert shadow['source'] == 'jev' and shadow['applied'] is False and shadow['error'] == 'OPENROUTER_API_KEY не задан'
    assert shadow['choice'] is None and shadow['noul'] == {'unclear': None, 'wide': None}


@pytest.mark.parametrize('case', ['no_jev', 'no_docs', 'http', 'over_limit'])
def test_shadow_skips_and_errors_still_write_event(proj, monkeypatch, case):
    vault = proj['ctx']['vault']
    if case == 'no_jev':
        agents = proj['ctx']['cwd'] / 'AGENTS.md'
        agents.write_text(agents.read_text().replace('jev: true\n', ''))
    elif case == 'no_docs':
        (vault / 'tz/x.md').unlink()
        (vault / 'research/x.md').write_text('# r\n')
    elif case == 'http':
        def boom(req, timeout):
            raise jev.urllib.error.HTTPError(jev.URL, 500, 'x', {}, None)
        monkeypatch.setattr(jev.urllib.request, 'urlopen', boom)
    else:
        (vault / 'tz/x.md').write_text(TZ + 'слово ' * 12000)
    out = workflow.complexity(proj['ctx'], proj['db'], 'x', 'medium', 'research')
    expected = {'no_jev': 'jev не включён в AGENTS.md', 'no_docs': 'нет ни ТЗ, ни требований', 'http': 'HTTP 500'}
    shadow = events(proj['db'], 'x')[1]
    assert shadow['source'] == 'jev' and shadow['choice'] is None and out['jev']['error'] == shadow['error']
    if case == 'over_limit':
        assert shadow['error'].startswith('вход больше лимита: ') and shadow['input_chars'] > workflow.PLAN_LIMIT
    else:
        assert shadow['error'] == expected[case]
    assert workflow.route(proj['ctx'], proj['db'], 'x')['complexity']['value'] == 'medium'


def test_no_shadow_flag_skips_jev(proj, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['devflow', '--cwd', str(proj['ctx']['cwd']), 'complexity', 'x', '--set', 'low', '--gate', 'plan', '--no-shadow'])
    assert cli.main() == 0
    assert [e['source'] for e in events(proj['db'], 'x')] == ['user']
    assert json.loads(capsys.readouterr().out)['jev'] is None


def test_route_launch_never_from_jev(proj, monkeypatch):
    monkeypatch.setattr(jev.urllib.request, 'urlopen', answers(choice='high'))
    workflow.complexity(proj['ctx'], proj['db'], 'x', 'low', 'research')
    route = workflow.route(proj['ctx'], proj['db'], 'x')
    assert route['complexity']['value'] == 'low' and route['launch']['claude']['effort'] != 'high'


PLAN = '''---
schema: 1
research_revision: {rev}
steps:
  - {{id: one, n: 1, blocked_by: []}}
  - {{id: two, n: 2, blocked_by: [one]}}
---

# X — Plan

## Steps

### one: Первый
- **Acceptance:** а

### two: Второй
- **Acceptance:** б
'''


@pytest.fixture
def done_run(proj):
    ctx, db, vault = proj['ctx'], proj['db'], proj['ctx']['vault']
    rev = documents.document(vault / 'research/x.md')['revision']
    (vault / 'plans/x.md').write_text(PLAN.format(rev=rev))
    plan = documents.document(vault / 'plans/x.md')
    workflow.approve(ctx, db, 'x', 'plan', plan['revision'])
    run = workflow.start(ctx, db, 'x', 'one', plan['revision'])['run_id']
    log = vault / 'changelog/2026-09-28-x.md'
    log.write_text(f'# X\n\n<!-- devflow-run: {run} -->\n## Шаг 1\n**Status:** done\nок\n')
    workflow.finish(ctx, db, run, 'done', str(log), None)
    return proj


def test_facts_without_plan(proj):
    assert workflow.complexity_facts(proj['ctx'], proj['db'], 'x') == {
        'steps': 0, 'runs': 0, 'statuses': {}, 'research_revisions': 1, 'plan_revisions': 0}


def test_facts_count_steps_runs_and_revisions(done_run):
    facts = workflow.complexity_facts(done_run['ctx'], done_run['db'], 'x')
    assert facts == {'steps': 2, 'runs': 1, 'statuses': {'done': 1}, 'research_revisions': 1, 'plan_revisions': 1}
    assert workflow.complexity(done_run['ctx'], done_run['db'], 'x')['facts'] == facts


def test_backfill_gate_writes_only_shadow(done_run, monkeypatch, capsys):
    ctx, db = done_run['ctx'], done_run['db']
    monkeypatch.setattr(jev.urllib.request, 'urlopen', answers(choice='medium'))
    monkeypatch.setattr(sys, 'argv', ['devflow', '--cwd', str(ctx['cwd']), 'complexity', 'x', '--gate', 'backfill'])
    assert cli.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out['user'] is None and out['jev']['choice'] == 'medium' and out['facts']['steps'] == 2
    shadow, = events(db, 'x')
    assert shadow['source'] == 'jev' and shadow['applied'] is False and shadow['gate'] == 'backfill'
    assert workflow.route(ctx, db, 'x')['complexity'] is None


def test_backfill_keeps_existing_user_value(proj, monkeypatch):
    workflow.complexity(proj['ctx'], proj['db'], 'x', 'high', 'research', shadow=False)
    monkeypatch.setattr(jev.urllib.request, 'urlopen', answers(choice='low'))
    out = workflow.complexity(proj['ctx'], proj['db'], 'x', None, 'backfill')
    assert out['user']['value'] == 'high' and out['jev']['choice'] == 'low'
    assert [e['source'] for e in events(proj['db'], 'x')] == ['user', 'jev']


def test_backfill_rejects_no_shadow(proj, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['devflow', '--cwd', str(proj['ctx']['cwd']), 'complexity', 'x', '--gate', 'backfill', '--no-shadow'])
    assert cli.main() != 0
    assert events(proj['db'], 'x') == []


def test_backfill_script_skips_tasks_without_plan(done_run, tmp_path, monkeypatch):
    import os
    import subprocess
    ctx, vault = done_run['ctx'], done_run['ctx']['vault']
    (vault / 'tz/y.md').write_text('# y\n')
    (vault / 'plans/x.md').rename(vault / 'plans/X.md')
    out = tmp_path / 'backfill.jsonl'
    root = documents.Path(__file__).resolve().parents[1]
    env = dict(os.environ, DEVFLOW_COMPLEXITY_BACKFILL=str(out), DEVFLOW_BIN=str(root / 'scripts/devflow-cli.sh'))
    env.pop('OPENROUTER_API_KEY', None)
    done_run['db'].close()
    res = subprocess.run([str(root / 'scripts/complexity-backfill.sh'), str(ctx['cwd'])], env=env, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert 'skip y: нет плана' in res.stdout and 'ok x' in res.stdout
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert [r['slug'] for r in rows] == ['x']
    assert rows[0]['facts']['steps'] == 2 and rows[0]['choice'] is None and rows[0]['error'] == 'OPENROUTER_API_KEY не задан'
    assert set(rows[0]) == {'slug', 'choice', 'noul', 'facts', 'error'}
