import json
import time

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
    assert out['launch']['claude'] == {'id': 'claude-opus-5-5', 'effort': 'medium', 'model': None, 'agent': 'plan'}
    assert isinstance(out['policy_stale'], list)
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


def test_route_high_complexity_picks_high_agent(proj, monkeypatch):
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(EXAMPLE))
    workflow.complexity(proj['ctx'], proj['db'], 'x', value='high', gate='research', shadow=False)
    out = workflow.route(proj['ctx'], proj['db'], 'x')
    assert out['state'] == 'plan'
    assert out['launch']['claude']['agent'] == 'plan-high'
    assert out['launch']['claude']['effort'] == 'high'


def test_route_reports_stale_agents(proj, monkeypatch, tmp_path):
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(EXAMPLE))
    monkeypatch.setenv('DEVFLOW_CLAUDE_DIR', str(tmp_path / 'claude'))
    assert workflow.route(proj['ctx'], proj['db'], 'x')['policy_stale'] == policy.agent_names(policy.load(EXAMPLE))
    list(policy.write_agents(policy.load(EXAMPLE), tmp_path / 'claude/agents'))
    assert workflow.route(proj['ctx'], proj['db'], 'x')['policy_stale'] == []


def test_agent_names_skip_high_equal_to_default(example):
    assert policy.agent_names(example) == ['research', 'research-high', 'plan', 'plan-high', 'implement']
    example['claude']['plan']['high'] = dict(example['claude']['plan']['default'])
    assert policy.agent_names(example) == ['research', 'research-high', 'plan', 'implement']


def test_render_agent_replaces_frontmatter_and_keeps_body(example):
    source = (policy.SOURCE_DIR / 'research.md').read_text()
    body = source.split('---\n', 2)[2]
    out = policy.render_agent(example, 'research-high')
    front, rendered_body = out.split('---\n', 2)[1:]
    assert 'name: research-high\n' in front
    assert 'model: claude-opus-5-5\n' in front
    assert 'effort: high\n' in front
    assert 'model: inherit' not in front
    assert 'description:' in front and 'tools:' in front
    assert rendered_body == policy.MARKER.format(phase='research') + '\n' + body


def test_render_agent_default_column(example):
    out = policy.render_agent(example, 'implement')
    assert 'name: implement\n' in out and 'model: claude-fable-5-1\n' in out and 'effort: low\n' in out


def test_render_agent_implement_keeps_skill_tool(example):
    for name in policy.agent_names(example):
        if not name.startswith('implement'):
            continue
        front = policy.render_agent(example, name).split('---\n', 2)[1]
        tools = next(line for line in front.splitlines() if line.startswith('tools:'))
        assert 'Skill' in tools, name


def test_installed_stale_missing_and_effort_drift(example, tmp_path):
    d = tmp_path / 'agents'
    assert policy.installed_stale(example, d) == policy.agent_names(example)
    list(policy.write_agents(example, d))
    assert policy.installed_stale(example, d) == []
    example['claude']['implement']['default']['effort'] = 'medium'
    assert policy.installed_stale(example, d) == ['implement', 'implement-fallback']
    (d / 'plan.md').write_text((d / 'plan.md').read_text() + '\nextra body line\n')
    assert policy.installed_stale(example, d) == ['plan', 'implement', 'implement-fallback']


def test_write_agents_is_atomic_and_replaces_symlink(example, tmp_path):
    d = tmp_path / 'agents'
    d.mkdir()
    (d / 'research.md').symlink_to(policy.SOURCE_DIR / 'research.md')
    actions = dict(policy.write_agents(example, d))
    assert actions['research'] == 'generate' and not (d / 'research.md').is_symlink()
    assert not list(d.glob('*.tmp'))
    assert dict(policy.write_agents(example, d)) == {n: 'ok' for n in policy.agent_names(example)}


def limits_file(path, now, five=(97, 3600), seven=(40, 86400), at=None):
    path.write_text(json.dumps({'five_hour': {'used_percentage': five[0], 'resets_at': now + five[1]},
                                'seven_day': {'used_percentage': seven[0], 'resets_at': now + seven[1]},
                                'model': 'claude-fable-5-1', 'at': now if at is None else at}))
    return path


def test_limits_missing_stale_or_broken(tmp_path):
    now = 1_700_000_000
    assert policy.limits(tmp_path / 'none.json', 95, 10, now) is None
    assert policy.limits(limits_file(tmp_path / 'old.json', now, at=now - 601), 95, 10, now) is None
    assert policy.limits(limits_file(tmp_path / 'fresh.json', now, at=now - 599), 95, 10, now)['exhausted'] is True
    (tmp_path / 'bad.json').write_text('{')
    assert policy.limits(tmp_path / 'bad.json', 95, 10, now) is None


def test_limits_exhausted_only_above_threshold_before_reset(tmp_path):
    now = 1_700_000_000
    got = policy.limits(limits_file(tmp_path / 'l.json', now), 95, 10, now)
    assert got == {'exhausted': True, 'window': 'five_hour', 'used_percentage': 97, 'resets_at': now + 3600, 'at': now}
    got = policy.limits(limits_file(tmp_path / 'l.json', now, five=(94, 3600)), 95, 10, now)
    assert got['exhausted'] is False and got['window'] == 'five_hour'
    got = policy.limits(limits_file(tmp_path / 'l.json', now, five=(97, -1)), 95, 10, now)
    assert got['exhausted'] is False
    got = policy.limits(limits_file(tmp_path / 'l.json', now, five=(10, 3600), seven=(96, 86400)), 95, 10, now)
    assert got['exhausted'] is True and got['window'] == 'seven_day'


@pytest.fixture
def ready(proj):
    plan = proj['vault'] / 'plans/x.md'
    rev = documents.document(proj['vault'] / 'research/x.md')['revision']
    plan.write_text(f'---\nschema: 1\nresearch_revision: {rev}\nsteps:\n  - {{id: s1, n: 1, blocked_by: []}}\n---\n'
                    '# p\n\n## Steps\n\n### s1: one\n- **Goal:** g\n')
    workflow.approve(proj['ctx'], proj['db'], 'x', 'plan', documents.document(plan)['revision'])
    return proj


def test_route_exhausted_limits_switch_implement_to_fallback(ready, monkeypatch, tmp_path):
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(EXAMPLE))
    monkeypatch.setenv('DEVFLOW_RATE_LIMITS', str(limits_file(tmp_path / 'rl.json', time.time())))
    out = workflow.route(ready['ctx'], ready['db'], 'x')
    assert out['state'] == 'ready' and out['phase'] == 'implement'
    assert out['limits']['exhausted'] is True
    assert out['launch']['claude'] == {'agent': 'implement', 'model': 'opus', 'id': 'claude-opus-5-5', 'effort': 'low'}


def test_route_without_limits_file_keeps_default(ready, monkeypatch, tmp_path):
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(EXAMPLE))
    monkeypatch.setenv('DEVFLOW_RATE_LIMITS', str(tmp_path / 'absent.json'))
    out = workflow.route(ready['ctx'], ready['db'], 'x')
    assert out['limits'] is None
    assert out['launch']['claude'] == {'agent': 'implement', 'model': None, 'id': 'claude-fable-5-1', 'effort': 'low'}


def test_route_stale_limits_do_not_fall_back(ready, monkeypatch, tmp_path):
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(EXAMPLE))
    monkeypatch.setenv('DEVFLOW_RATE_LIMITS', str(limits_file(tmp_path / 'rl.json', time.time(), at=time.time() - 3600)))
    out = workflow.route(ready['ctx'], ready['db'], 'x')
    assert out['limits'] is None and out['launch']['claude']['model'] is None


def test_paths_follow_claude_dir(monkeypatch, tmp_path):
    monkeypatch.delenv('DEVFLOW_MODEL_POLICY', raising=False)
    monkeypatch.delenv('DEVFLOW_RATE_LIMITS', raising=False)
    monkeypatch.setenv('DEVFLOW_CLAUDE_DIR', str(tmp_path))
    assert policy.policy_path() == tmp_path / 'devflow/model-policy.json'
    assert policy.limits_path() == tmp_path / 'devflow/rate-limits.json'
    assert policy.agents_dir() == tmp_path / 'agents'


@pytest.mark.parametrize('host, phase', [('claude', 'plan'), ('pi', 'implement')])
def test_load_rejects_policy_without_default_for_a_phase(tmp_path, example, host, phase):
    del example[host][phase]['default']
    path = tmp_path / 'p.json'
    path.write_text(json.dumps(example))
    with pytest.raises(WorkflowError, match=f'{host}/{phase}'):
        policy.load(path)


def test_fallback_with_unknown_prefix_passes_full_id(ready, monkeypatch, tmp_path, example):
    example['claude']['implement']['fallback']['model'] = 'opus'
    path = tmp_path / 'p.json'
    path.write_text(json.dumps(example))
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(path))
    monkeypatch.setenv('DEVFLOW_RATE_LIMITS', str(limits_file(tmp_path / 'rl.json', time.time())))
    out = workflow.route(ready['ctx'], ready['db'], 'x')
    assert out['launch']['claude']['model'] == 'opus'


def test_fallback_effort_differing_from_default_gets_its_own_agent(ready, monkeypatch, tmp_path, example):
    example['claude']['implement']['fallback']['effort'] = 'medium'
    assert policy.agent_names(example)[-2:] == ['implement', 'implement-fallback']
    front = policy.render_agent(example, 'implement-fallback').split('---\n', 2)[1]
    assert 'name: implement-fallback\n' in front and 'effort: medium\n' in front
    path = tmp_path / 'p.json'
    path.write_text(json.dumps(example))
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(path))
    monkeypatch.setenv('DEVFLOW_RATE_LIMITS', str(limits_file(tmp_path / 'rl.json', time.time())))
    out = workflow.route(ready['ctx'], ready['db'], 'x')
    assert out['launch']['claude']['agent'] == 'implement-fallback' and out['launch']['claude']['effort'] == 'medium'
