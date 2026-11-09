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
    assert harness_codex.parse(EVENTS, '', 0) == {'status': 'ok', 'tokens': 175, 'cost': None,
                                                   'session_id': 't-1', 'report': 'готово'}
    assert harness_codex.parse(EVENTS + '\n' + json.dumps({'type': 'turn.failed'}), '', 0)['status'] == 'failed'
    assert harness_codex.parse(json.dumps({'type': 'thread.started'}), '', 0)['status'] == 'failed'
    assert harness_codex.parse('garbage', 'boom', 1)['status'] == 'failed'


def test_research_through_codex_is_ok_and_recorded(proj, codex):
    env = {**codex['env'], 'FAKE_WRITE': '# r\\n\\n## Problem\\nп\\n\\n## Recommendation\\nр\\n'}
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', model='gpt-6-sol', env=env, host='codex')
    assert out['status'] == 'ok' and out['route']['state'] == 'approval_required'
    assert out['tokens'] == 175 and out['session_id'] == 't-1' and out['report'] == 'готово'
    argv = codex['argv']()
    assert 'gpt-6-sol' in argv and str(proj['vault']) in argv and 'jira-issue.sh' in argv
    row = dict(proj['db'].execute('SELECT * FROM outcomes').fetchone())
    assert (row['harness'], row['model'], row['status'], row['tokens']) == ('codex', 'gpt-6-sol', 'ok', 175)


def test_codex_without_artifact_is_failed(proj, codex):
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', model='m', env=codex['env'], host='codex')
    assert out['status'] == 'failed'
    assert [r['status'] for r in proj['db'].execute('SELECT status FROM outcomes')] == ['failed']


def test_codex_needs_a_model(proj, codex):
    with pytest.raises(WorkflowError, match='Модель codex'):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', env=codex['env'], host='codex')
