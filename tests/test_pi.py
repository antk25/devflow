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
    assert out['route']['state'] == 'plan'
    assert not Path(argv[argv.index('--append-system-prompt') + 1]).exists()


def test_run_phase_nonzero_exit_is_reported_not_raised(proj, fake_pi):
    approve_research(proj)
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'plan', env={**fake_pi['env'], 'FAKE_PI_EXIT': '3'})
    assert out['exit_code'] == 3
    assert '--model' not in fake_pi['argv']()


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
