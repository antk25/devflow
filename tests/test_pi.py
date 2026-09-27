import json

import pytest

from devflow import pi

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
