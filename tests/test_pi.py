import json
import os
import sys
from pathlib import Path

import pytest

from devflow import cli, documents, pi, workflow
from devflow.documents import WorkflowError, context
from devflow.storage import connect

CTX = {'project': 'demo', 'cwd': '/p', 'vault': '/v'}
ACTIVE = {'project': 'demo', 'vault': '/v', 'tz': [], 'research': [],
          'plans': [{'name': 'df-11-pi', 'status': 'running', 'route': {'phase': 'implement'}}]}
HANDOFF = {'path': '/v/notes/handoff-df-11.md', 'body': '# Передача\n\nГде остановились.\n'}


def test_preamble_has_markers_json_handoff_and_rules():
    text = pi.preamble(CTX, ACTIVE, HANDOFF)
    assert text.startswith('PROJECT_RESTORE\n{')
    assert 'OBSIDIAN_CONTEXT\n{' in text
    assert json.dumps(ACTIVE, ensure_ascii=False, indent=2) in text
    assert 'HANDOFF /v/notes/handoff-df-11.md\n# Передача' in text
    assert 'DEVFLOW_RULES' in text and '`claude`' in text and 'approve' in text
    assert text == pi.preamble(CTX, ACTIVE, HANDOFF)


def test_preamble_without_handoff_has_no_handoff_section():
    assert 'HANDOFF' not in pi.preamble(CTX, ACTIVE, None)


def test_preamble_rules_cover_interrupted_run():
    text = pi.preamble(CTX, ACTIVE, None)
    assert '`running`' in text
    assert 'git status' in text and 'changelog' in text
    assert 'finish' in text and 'resume' in text and 'interrupt' in text
    assert 'phase run … implement` для того же шага не запускай' in text


def test_task_key_prefers_most_advanced_active_task():
    active = {'tz': [{'name': 'DF-18-evals', 'status': 'approval_required'}],
              'research': [{'name': 'df-7-old', 'status': 'migration_required'}],
              'plans': [{'name': 'df-11-pi', 'status': 'running'}]}
    assert pi.task_key(active) == 'DF-11'
    assert pi.task_key({'tz': [{'name': 'DF-18-evals', 'status': 'approval_required'}]}) == 'DF-18'
    assert pi.task_key({'plans': [{'name': 'no-key-here', 'status': 'ready'}]}) is None
    assert pi.task_key({'plans': [{'name': 'df-1-x', 'status': 'invalid'}]}) is None


def test_model_arg():
    assert pi.model_arg({}, None) is None
    assert pi.model_arg({'PI_PROVIDER': 'openai-codex'}, None) is None
    assert pi.model_arg({'PI_PROVIDER': 'openai-codex', 'PI_MODEL': 'gpt-6-astra'}, None) == 'openai-codex/gpt-6-astra'
    env = {'PI_PROVIDER': 'openai-codex', 'PI_MODEL': 'gpt-6-astra', 'PI_REASONING_LEVEL': 'low'}
    assert pi.model_arg(env, None) == 'openai-codex/gpt-6-astra:low'
    assert pi.model_arg(env, 'anthropic/x') == 'anthropic/x'


@pytest.mark.parametrize('model,settings,expected', [
    ('claude-bridge/claude-opus-5-5', None, True),
    ('openai-codex/gpt-6-astra', '{"defaultProvider": "claude-bridge"}', False),
    (None, '{"defaultProvider": "claude-bridge"}', True),
    (None, '{"defaultProvider": "openai-codex"}', False),
    (None, None, False),
    (None, '{not json', False),
])
def test_warns_claude_bridge(tmp_path, model, settings, expected):
    path = tmp_path / 'settings.json'
    if settings is not None:
        path.write_text(settings)
    assert pi.warns_claude_bridge(model, path) is expected


FAKE_PI = '''#!/usr/bin/env bash
printf '%s\\n' "$@" > "$FAKE_PI_LOG"
[ "$(readlink /proc/$$/fd/0)" = /dev/null ] && echo closed > "$FAKE_PI_STDIN" || echo open > "$FAKE_PI_STDIN"
echo "отчёт фазы"
exit "${FAKE_PI_EXIT:-0}"
'''


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv('DEVFLOW_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(tmp_path / 'no-policy.json'))
    vault, cwd = tmp_path / 'vault', tmp_path / 'proj'
    for d in ('tz', 'plans', 'research', 'changelog'):
        (vault / d).mkdir(parents=True)
    cwd.mkdir()
    (cwd / 'AGENTS.md').write_text(f'---\nproject: p\nvault: {vault}\n---\n')
    (vault / 'tz/x.md').write_text('# ТЗ\n')
    ctx = context(cwd)
    db = connect(ctx, create=True)
    yield {'ctx': ctx, 'db': db, 'cwd': cwd, 'vault': vault}
    db.close()


def approve_research(proj):
    (proj['vault'] / 'research/x.md').write_text('# r\n')
    rev = documents.document(proj['vault'] / 'research/x.md')['revision']
    workflow.approve(proj['ctx'], proj['db'], 'x', 'research', rev)
    return rev


@pytest.fixture
def fake_pi(tmp_path):
    exe = tmp_path / 'bin' / 'pi'
    exe.parent.mkdir()
    exe.write_text(FAKE_PI)
    exe.chmod(0o755)
    log, stdin = tmp_path / 'argv', tmp_path / 'stdin'
    env = {k: v for k, v in os.environ.items() if not k.startswith('PI_')}
    env.update({'PATH': f"{exe.parent}:{os.environ['PATH']}", 'FAKE_PI_LOG': str(log), 'FAKE_PI_STDIN': str(stdin)})

    def argv():
        return log.read_text().splitlines()

    return {'env': env, 'argv': argv, 'stdin': stdin, 'log': log}


def test_agent_body_strips_frontmatter_and_maps_tools():
    body, tools = pi.agent_body('plan')
    assert not body.startswith('---')
    assert 'name: plan' not in body and 'effort: low' not in body
    assert body.startswith('# plan')
    assert tools == ['read', 'grep', 'find', 'ls', 'bash', 'write']
    assert '~/.claude/skills/devflow/devflow' not in body and 'devflow route' in body
    with pytest.raises(WorkflowError):
        pi.agent_body('nope')


def test_build_command_without_model_and_without_claude():
    cmd = pi.build_command('/tmp/body.md', ['read', 'bash'], None, 'задание')
    assert cmd == ['pi', '-p', '--no-session', '--append-system-prompt', '/tmp/body.md', '--tools', 'read,bash', 'задание']
    assert '--model' not in cmd
    assert '--model' in pi.build_command('/tmp/b', ['read'], 'openai-codex/gpt-6-astra', 'm')
    assert not any('claude' in part for part in cmd)


def test_task_message_carries_note_and_tz(proj):
    state = {'slug': 'x', 'research_revision': 'r1', 'plan_revision': None}
    text = pi.task_message('plan', proj['ctx'], state, note='  учти лимиты  ')
    assert 'slug: x' in text and 'research_revision: r1' in text and 'plan_revision' not in text
    assert f"tz: {proj['vault'] / 'tz/x.md'}" in text
    assert 'Замечание пользователя:\nучти лимиты' in text
    assert 'Замечание' not in pi.task_message('plan', proj['ctx'], state)


def test_run_phase_refuses_wrong_state(proj, fake_pi):
    with pytest.raises(WorkflowError, match='state research'):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'plan', env=fake_pi['env'])
    approve_research(proj)
    with pytest.raises(WorkflowError, match='state plan'):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', env=fake_pi['env'])
    assert not fake_pi['log'].exists()


def test_run_phase_launches_fake_pi_with_model_from_env(proj, fake_pi):
    approve_research(proj)
    env = {**fake_pi['env'], 'PI_PROVIDER': 'openai-codex', 'PI_MODEL': 'gpt-6-astra', 'PI_REASONING_LEVEL': 'low'}
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'plan', note='коротко', env=env)
    argv = fake_pi['argv']()
    for flag in ('-p', '--no-session', '--append-system-prompt', '--tools'):
        assert flag in argv
    assert argv[argv.index('--model') + 1] == 'openai-codex/gpt-6-astra:low'
    assert argv[argv.index('--tools') + 1] == 'read,grep,find,ls,bash,write'
    assert 'Замечание пользователя:\nкоротко' in fake_pi['log'].read_text()
    assert not any('claude' in a for a in argv)
    assert fake_pi['stdin'].read_text().strip() == 'closed'
    assert out['exit_code'] == 0 and out['report'].strip() == 'отчёт фазы'
    assert out['model'] == 'openai-codex/gpt-6-astra:low' and out['phase'] == 'plan'
    assert out['model_source'] == 'env'
    assert out['route']['state'] == 'plan'
    assert not Path(argv[argv.index('--append-system-prompt') + 1]).exists()


def test_run_phase_nonzero_exit_is_reported_not_raised(proj, fake_pi):
    approve_research(proj)
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'plan', env={**fake_pi['env'], 'FAKE_PI_EXIT': '3'})
    assert out['exit_code'] == 3
    assert '--model' not in fake_pi['argv']()
    assert out['model_source'] == 'default'


EXAMPLE_POLICY = Path(__file__).resolve().parents[1] / 'model-policy.example.json'


def test_run_phase_takes_model_from_policy_over_env(proj, fake_pi, monkeypatch):
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(EXAMPLE_POLICY))
    monkeypatch.setenv('DEVFLOW_RATE_LIMITS', str(proj['cwd'] / 'no-limits.json'))
    approve_research(proj)
    env = {**fake_pi['env'], 'PI_PROVIDER': 'anthropic', 'PI_MODEL': 'x', 'PI_REASONING_LEVEL': 'low'}
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'plan', env=env)
    argv = fake_pi['argv']()
    assert argv[argv.index('--model') + 1] == 'openai-codex/gpt-6-astra:medium'
    assert out['model'] == 'openai-codex/gpt-6-astra:medium' and out['model_source'] == 'policy'


def test_run_phase_model_override_beats_policy(proj, fake_pi, monkeypatch):
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(EXAMPLE_POLICY))
    monkeypatch.setenv('DEVFLOW_RATE_LIMITS', str(proj['cwd'] / 'no-limits.json'))
    approve_research(proj)
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'plan', model='x/y:z', env=fake_pi['env'])
    argv = fake_pi['argv']()
    assert argv[argv.index('--model') + 1] == 'x/y:z'
    assert out['model'] == 'x/y:z' and out['model_source'] == 'override'


@pytest.mark.parametrize('env_model,settings', [
    ({'PI_PROVIDER': 'claude-bridge', 'PI_MODEL': 'claude-opus-5-5'}, None),
    ({}, '{"defaultProvider": "claude-bridge"}'),
])
def test_run_phase_warns_about_claude_bridge_but_runs(proj, fake_pi, tmp_path, monkeypatch, capsys, env_model, settings):
    approve_research(proj)
    settings_path = tmp_path / 'settings.json'
    if settings:
        settings_path.write_text(settings)
    monkeypatch.setattr(pi, 'PI_SETTINGS', settings_path)
    pi.run_phase(proj['ctx'], proj['db'], 'x', 'plan', env={**fake_pi['env'], **env_model})
    assert 'claude-bridge' in capsys.readouterr().err
    assert fake_pi['log'].exists()


def test_cli_phase_run_exit_code_follows_pi(proj, fake_pi, monkeypatch, capsys):
    approve_research(proj)
    for key, value in {**fake_pi['env'], 'FAKE_PI_EXIT': '2'}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, 'argv', ['devflow', '--cwd', str(proj['cwd']), 'phase', 'run', 'x', 'plan'])
    assert cli.main() == 1
    assert json.loads(capsys.readouterr().out)['exit_code'] == 2


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
- **Acceptance:** критерий

### two: Второй
- **Acceptance:** критерий
'''

FAKE_PI_FINISH = FAKE_PI.replace('echo "отчёт фазы"', '''grep -o 'run_id: [^ ]*' "$FAKE_PI_LOG" | cut -d' ' -f2 > "$FAKE_PI_LOG.run"
printf '# X — Changelog\\n\\n<!-- devflow-run: %s -->\\n## Шаг 1\\n\\n**Status:** done\\n' "$(cat "$FAKE_PI_LOG.run")" > "$FAKE_PI_CHANGELOG"
devflow --cwd "$PWD" finish "$(cat "$FAKE_PI_LOG.run")" --status done --changelog "$FAKE_PI_CHANGELOG" > /dev/null
echo "отчёт фазы"''')


def approve_plan(proj):
    rev = approve_research(proj)
    (proj['vault'] / 'plans/x.md').write_text(PLAN.format(rev=rev))
    plan_rev = documents.document(proj['vault'] / 'plans/x.md')['revision']
    workflow.approve(proj['ctx'], proj['db'], 'x', 'plan', plan_rev)
    return plan_rev


def runs(proj):
    return [dict(r) for r in proj['db'].execute('SELECT * FROM runs')]


def test_implement_refuses_when_not_ready_without_start(proj, fake_pi):
    approve_research(proj)
    with pytest.raises(WorkflowError, match='state plan'):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'implement', env=fake_pi['env'])
    assert runs(proj) == [] and not fake_pi['log'].exists()


def test_implement_refuses_foreign_step_without_start(proj, fake_pi):
    approve_plan(proj)
    with pytest.raises(WorkflowError, match='two is not on the frontier'):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'implement', step='two', env=fake_pi['env'])
    with pytest.raises(WorkflowError, match='nope is not on the frontier'):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'implement', step='nope', env=fake_pi['env'])
    assert runs(proj) == [] and not fake_pi['log'].exists()


def test_implement_starts_run_before_pi_and_warns_when_left_running(proj, fake_pi):
    plan_rev = approve_plan(proj)
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'implement', env=fake_pi['env'])
    started = runs(proj)
    assert len(started) == 1 and started[0]['step_id'] == 'one' and started[0]['status'] == 'running'
    message = fake_pi['log'].read_text()
    assert f"run_id: {started[0]['id']}" in message and 'step: one (n=1)' in message
    assert f'plan_revision: {plan_rev}' in message and 'DevFlow Phase — implement.' in message
    assert out['run_id'] == started[0]['id']
    assert out['route']['state'] == 'running' and out['route']['run_id'] == started[0]['id']
    assert 'finish' in out['warning'] and 'phase run implement again' in out['warning']


def test_implement_run_started_before_pi_is_launched(proj, fake_pi, tmp_path):
    approve_plan(proj)
    state = tmp_path / 'state'
    probe = FAKE_PI.replace('echo "отчёт фазы"',
                            f'devflow --cwd "$PWD" status x | grep -o \'"state": "[a-z]*"\' > "{tmp_path}/seen"')
    (tmp_path / 'bin/pi').write_text(probe)
    pi.run_phase(proj['ctx'], proj['db'], 'x', 'implement', env={**fake_pi['env'], 'DEVFLOW_STATE_DIR': str(state)})
    assert (tmp_path / 'seen').read_text().strip() == '"state": "running"'


def test_implement_finished_by_pi_has_no_warning_and_routes_to_next_step(proj, fake_pi, tmp_path):
    approve_plan(proj)
    (tmp_path / 'bin/pi').write_text(FAKE_PI_FINISH)
    env = {**fake_pi['env'], 'DEVFLOW_STATE_DIR': str(tmp_path / 'state'),
           'FAKE_PI_CHANGELOG': str(proj['vault'] / 'changelog/2026-01-01-x.md')}
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'implement', step='one', env=env)
    assert out['exit_code'] == 0, out['stderr']
    assert 'warning' not in out
    assert out['route']['state'] == 'ready' and out['route']['step'] == 'two' and out['route']['done'] == ['one']
    assert runs(proj)[0]['status'] == 'done'


def test_model_env_round_trips_model_arg():
    assert pi.model_env('openai-codex/gpt-6-astra:low') == {'PI_PROVIDER': 'openai-codex', 'PI_MODEL': 'gpt-6-astra',
                                                            'PI_REASONING_LEVEL': 'low'}
    assert pi.model_env('openrouter/openai/gpt-6-astra') == {'PI_PROVIDER': 'openrouter', 'PI_MODEL': 'openai/gpt-6-astra'}
    assert pi.model_env('gpt-6-astra') == {}
    assert pi.model_arg(pi.model_env('a/b:c')) == 'a/b:c'


def test_run_phase_accepts_own_gate_for_note(proj, fake_pi):
    (proj['vault'] / 'research/x.md').write_text('# r\n')
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', note='точнее', env=fake_pi['env'])
    assert out['exit_code'] == 0 and 'Замечание пользователя:' in fake_pi['log'].read_text()
    with pytest.raises(WorkflowError, match='state approval_required'):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'plan', env=fake_pi['env'])
    rev = approve_research(proj)
    (proj['vault'] / 'plans/x.md').write_text(PLAN.format(rev=rev))
    fake_pi['log'].unlink()
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'plan', note='ещё', env=fake_pi['env'])
    assert out['exit_code'] == 0 and 'ещё' in fake_pi['log'].read_text()


def test_implement_without_pi_in_path_does_not_start_a_run(proj, fake_pi):
    approve_plan(proj)
    env = dict(fake_pi['env'], PATH='/nonexistent')
    with pytest.raises(WorkflowError, match='pi CLI is missing'):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'implement', env=env)
    assert runs(proj) == []
    assert workflow.route(proj['ctx'], proj['db'], 'x')['state'] == 'ready'


def test_implement_launch_failure_interrupts_the_run(proj, fake_pi, monkeypatch):
    approve_plan(proj)

    def boom(*a, **k):
        raise OSError('exec failed')
    monkeypatch.setattr(pi.subprocess, 'run', boom)
    with pytest.raises(WorkflowError, match='failed to launch'):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'implement', env=fake_pi['env'])
    assert [r['status'] for r in runs(proj)] == ['blocked']
    assert workflow.route(proj['ctx'], proj['db'], 'x')['state'] == 'blocked'
