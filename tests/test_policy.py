import json

import pytest

from devflow import documents, policy, workflow
from devflow.documents import WorkflowError, context
from devflow.storage import connect

EXAMPLE = documents.Path(__file__).resolve().parents[1] / 'model-policy.example.json'


@pytest.fixture
def example():
    return policy.load(EXAMPLE)


@pytest.mark.parametrize('host, phase, complexity, exhausted, expected', [
    ('claude', 'research', 'high', False, ('claude-opus-5-5', 'high', 'high')),
    ('claude', 'plan', None, False, ('claude-opus-5-5', 'medium', 'default')),
    ('claude', 'plan', 'low', False, ('claude-opus-5-5', 'medium', 'default')),
    ('claude', 'implement', 'high', False, ('claude-fable-5-1', 'low', 'default')),
    ('claude', 'implement', None, True, ('claude-opus-5-5', 'low', 'fallback')),
    ('claude', 'research', None, True, ('claude-opus-5-5', 'medium', 'default')),
    ('pi', 'research', 'high', False, ('openai-codex/gpt-6-astra', 'high', 'high')),
    ('pi', 'plan', None, False, ('openai-codex/gpt-6-astra', 'medium', 'default')),
    ('pi', 'implement', 'high', True, ('openai-codex/gpt-6-astra', 'low', 'default')),
])
def test_resolve_follows_tz_table(example, host, phase, complexity, exhausted, expected):
    got = policy.resolve(example, host, phase, complexity, exhausted)
    assert (got['model'], got['effort'], got['column']) == expected


def test_resolve_requires_default(example):
    del example['claude']['plan']['default']
    with pytest.raises(WorkflowError, match='default'):
        policy.resolve(example, 'claude', 'plan')
    with pytest.raises(WorkflowError, match='claude/review'):
        policy.resolve(example, 'claude', 'review')


def test_load_missing_returns_none(tmp_path):
    assert policy.load(tmp_path / 'none.json') is None


def test_load_broken_json_raises(tmp_path):
    p = tmp_path / 'p.json'
    p.write_text('{"claude": ')
    with pytest.raises(WorkflowError, match='not valid JSON'):
        policy.load(p)


def test_load_requires_keys(tmp_path):
    p = tmp_path / 'p.json'
    p.write_text(json.dumps({'claude': {}}))
    with pytest.raises(WorkflowError, match='pi, limits'):
        policy.load(p)


def test_alias_and_pi_model():
    assert policy.alias('claude-opus-5-5') == 'opus'
    assert policy.alias('claude-fable-5-1') == 'fable'
    assert policy.alias('gpt-6-astra') is None
    assert policy.pi_model({'model': 'openai-codex/gpt-6-astra', 'effort': 'medium'}) == 'openai-codex/gpt-6-astra:medium'
    assert policy.pi_model({'model': 'openai-codex/gpt-6-astra'}) == 'openai-codex/gpt-6-astra'


def test_policy_path_env(monkeypatch, tmp_path):
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(tmp_path / 'x.json'))
    assert policy.policy_path() == tmp_path / 'x.json'
    monkeypatch.delenv('DEVFLOW_MODEL_POLICY')
    assert policy.policy_path().name == 'model-policy.json'


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv('DEVFLOW_STATE_DIR', str(tmp_path / 'state'))
    vault, cwd = tmp_path / 'vault', tmp_path / 'proj'
    for d in ('plans', 'research', 'changelog'):
        (vault / d).mkdir(parents=True)
    cwd.mkdir()
    (cwd / 'AGENTS.md').write_text(f'---\nproject: p\nvault: {vault}\n---\n')
    (vault / 'research/x.md').write_text('# r\n')
    ctx = context(cwd)
    db = connect(ctx, create=True)
    workflow.approve(ctx, db, 'x', 'research', documents.document(vault / 'research/x.md')['revision'])
    yield {'ctx': ctx, 'db': db, 'vault': vault}
    db.close()


def test_route_adds_launch_from_policy(proj, monkeypatch):
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(EXAMPLE))
    out = workflow.route(proj['ctx'], proj['db'], 'x')
    assert out['state'] == 'plan'
    assert out['policy'] == str(EXAMPLE)
    assert out['launch']['claude'] == {'id': 'claude-opus-5-5', 'effort': 'medium', 'model': None}
    assert out['launch']['pi'] == {'model': 'openai-codex/gpt-6-astra:medium'}


def test_route_without_policy_file(proj, monkeypatch, tmp_path):
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(tmp_path / 'absent.json'))
    out = workflow.route(proj['ctx'], proj['db'], 'x')
    assert out['policy'] is None and 'launch' not in out


def test_route_resolves_for_phase_of_state(proj, monkeypatch):
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(EXAMPLE))
    (proj['vault'] / 'research/x.md').write_text('# changed\n')
    out = workflow.route(proj['ctx'], proj['db'], 'x')
    assert out['state'] == 'approval_required' and out['phase'] == 'research'
    assert 'launch' in out
