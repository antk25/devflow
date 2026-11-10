import json
import os

import pytest

from devflow import harness_codex, pi
from devflow.documents import WorkflowError
from test_pi import proj  # noqa: F401

EVENTS = '\n'.join(json.dumps(e) for e in (
    {'type': 'thread.started', 'thread_id': 't-1'},
    {'type': 'turn.started'},
    {'type': 'item.completed', 'item': {'id': 'i0', 'type': 'agent_message', 'text': 'готово'}},
    {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 50, 'output_tokens': 20,
                                         'reasoning_output_tokens': 5}}))
FAKE = '''#!/usr/bin/env bash
printf '%s\\n' "$@" > "$FAKE_LOG"
[ -n "$FAKE_WRITE" ] && printf '%b' "$FAKE_WRITE" > "$FAKE_TARGET"
printf '%s' "$FAKE_REPLY"
exit "${FAKE_EXIT:-0}"
'''


@pytest.fixture
def codex(tmp_path, proj):
    exe = tmp_path / 'bin' / 'codex'
    exe.parent.mkdir()
    exe.write_text(FAKE)
    exe.chmod(0o755)
    env = {**os.environ, 'PATH': f"{exe.parent}:{os.environ['PATH']}", 'FAKE_LOG': str(tmp_path / 'argv'),
           'FAKE_TARGET': str(proj['vault'] / 'research/x.md'), 'FAKE_REPLY': EVENTS}
    return {'env': env, 'argv': lambda: (tmp_path / 'argv').read_text()}


def test_command_line():
    cmd = harness_codex.build_command('gpt-6-sol', 'high', 'msg', '/p', ['/v'])
    assert cmd[:3] == ['codex', 'exec', '--json'] and cmd[cmd.index('-m') + 1] == 'gpt-6-sol'
    assert cmd[cmd.index('-s') + 1] == 'workspace-write' and cmd[cmd.index('-C') + 1] == '/p'
    assert cmd[cmd.index('--add-dir') + 1] == '/v' and 'model_reasoning_effort=high' in cmd
    assert cmd[-2:] == ['--', 'msg']
    assert '-c' not in harness_codex.build_command('m', None, 'x', '/p')
    with pytest.raises(ValueError):
        harness_codex.build_command(None, None, 'x', '/p')


def test_prompt_carries_body_and_jira_script():
    text = harness_codex.prompt('тело агента', 'задание')
    assert text.startswith('тело агента') and text.endswith('задание') and 'jira-issue.sh' in text


def test_parse_events():
    assert harness_codex.parse(EVENTS, '', 0) == {'status': 'ok', 'tokens': 120, 'cost': None,
                                                   'session_id': 't-1', 'report': 'готово'}
    assert harness_codex.parse(EVENTS + '\n' + json.dumps({'type': 'turn.failed'}), '', 0)['status'] == 'failed'
    assert harness_codex.parse(json.dumps({'type': 'thread.started'}), '', 0)['status'] == 'failed'
    assert harness_codex.parse('garbage', 'boom', 1)['status'] == 'failed'


def test_research_through_codex_is_ok_and_recorded(proj, codex):
    env = {**codex['env'], 'FAKE_WRITE': '# r\\n\\n## Problem\\nп\\n\\n## Recommendation\\nр\\n'}
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', model='gpt-6-sol', env=env, host='codex')
    assert out['status'] == 'ok' and out['route']['state'] == 'approval_required'
    assert out['tokens'] == 120 and out['session_id'] == 't-1' and out['report'] == 'готово'
    argv = codex['argv']()
    assert 'gpt-6-sol' in argv and str(proj['vault']) in argv and 'jira-issue.sh' in argv
    row = dict(proj['db'].execute('SELECT * FROM outcomes').fetchone())
    assert (row['harness'], row['model'], row['status'], row['tokens']) == ('codex', 'gpt-6-sol', 'ok', 120)


def test_codex_without_artifact_is_failed(proj, codex):
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', model='m', env=codex['env'], host='codex')
    assert out['status'] == 'failed'
    assert [r['status'] for r in proj['db'].execute('SELECT status FROM outcomes')] == ['failed']


def test_codex_needs_a_model(proj, codex):
    with pytest.raises(WorkflowError, match='Модель codex'):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', env=codex['env'], host='codex')


def test_artifact_found_regardless_of_case(proj, codex):
    env = {**codex['env'], 'FAKE_TARGET': str(proj['vault'] / 'research/X.md'),
           'FAKE_WRITE': '# r\\n\\n## Problem\\nп\\n\\n## Recommendation\\nр\\n'}
    assert pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', model='m', env=env, host='codex')['status'] == 'ok'


def test_pi_row_with_codex_harness_runs_codex_by_default(proj, codex, monkeypatch):
    real = pi.route
    launch = {'harness': 'claude', 'claude': {'id': 'claude-opus-5-5', 'effort': 'low', 'agent': 'research'},
              'pi': {'model': 'gpt-6-sol:medium', 'harness': 'codex'}}
    monkeypatch.setattr(pi, 'route', lambda ctx, db, slug: {**real(ctx, db, slug), 'launch': launch})
    env = {**codex['env'], 'FAKE_WRITE': '# r\\n\\n## Problem\\nп\\n\\n## Recommendation\\nр\\n'}
    assert pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', env=env)['status'] == 'ok'
    argv = codex['argv']().split('\n')
    assert argv[argv.index('-m') + 1] == 'gpt-6-sol' and 'model_reasoning_effort=medium' in argv


def test_replan_takes_plan_launch_not_implement(proj, monkeypatch):
    seen = {}
    monkeypatch.setattr(pi, 'route', lambda ctx, db, slug: {
        'state': 'ready', 'phase': 'implement', 'policy': '/p', 'complexity': {'value': 'high'},
        'launch': {'harness': 'claude', 'claude': {'id': 'claude-fable-5-1', 'effort': 'low', 'agent': 'implement'}}})
    monkeypatch.setattr(pi, 'launch_for', lambda phase, complexity: {'launch': {
        'harness': 'claude', 'claude': {'id': 'claude-opus-5-5', 'effort': 'high', 'agent': f'{phase}-high'}}})
    monkeypatch.setattr(pi.shutil, 'which', lambda *a, **k: '/bin/claude')

    def capture(ctx, phase, current, model, env):
        seen.update(current['launch']['claude'])
        raise WorkflowError('stop')
    monkeypatch.setattr(pi, '_claude_launch', capture)
    with pytest.raises(WorkflowError):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'plan', replan=True, host='claude', env={})
    assert seen == {'id': 'claude-opus-5-5', 'effort': 'high', 'agent': 'plan-high'}


def test_claude_row_with_pi_harness_runs_research_on_its_model(proj, monkeypatch):
    monkeypatch.setattr(pi, 'load', lambda path: {'pi': {'implement': {}}})
    for name in ('ensure_pi_model', 'shared_instructions', 'extension_path'):
        monkeypatch.setattr(pi, name, lambda *a, **k: None)
    current = {'launch': {'harness': 'pi', 'claude': {'id': 'openrouter/z-ai/glm-5.3', 'effort': 'high'}, 'pi': None}}
    chosen, source, _ = pi._pi_launch(proj['ctx'], 'research', current, None, {})
    assert (chosen, source) == ('openrouter/z-ai/glm-5.3:high', 'policy')
    with pytest.raises(WorkflowError):
        pi._pi_launch(proj['ctx'], 'research', {'launch': {'harness': 'claude', 'claude': {}, 'pi': None}}, None, {})
