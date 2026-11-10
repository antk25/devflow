import json
import os

import pytest

from devflow import harness_claude, pi
from devflow.documents import WorkflowError
from test_pi import proj  # noqa: F401

REPLY = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'готово', 'session_id': 's-1',
         'total_cost_usd': 0.5, 'modelUsage': {'claude-opus-5-5': {
             'inputTokens': 10, 'outputTokens': 20, 'cacheReadInputTokens': 300, 'cacheCreationInputTokens': 40,
             'thinkingTokens': 5, 'costUSD': 0.5}}}
FAKE = '''#!/usr/bin/env bash
printf '%s\\n' "$@" > "$FAKE_LOG"
[ -n "$FAKE_WRITE" ] && printf '%b' "$FAKE_WRITE" > "$FAKE_TARGET"
printf '%s' "$FAKE_REPLY"
exit "${FAKE_EXIT:-0}"
'''


@pytest.fixture
def claude(tmp_path, proj):
    exe = tmp_path / 'bin' / 'claude'
    exe.parent.mkdir()
    exe.write_text(FAKE)
    exe.chmod(0o755)
    env = {**os.environ, 'PATH': f"{exe.parent}:{os.environ['PATH']}", 'FAKE_LOG': str(tmp_path / 'argv'),
           'FAKE_TARGET': str(proj['vault'] / 'research/x.md'), 'FAKE_REPLY': json.dumps(REPLY)}
    return {'env': env, 'argv': lambda: (tmp_path / 'argv').read_text().splitlines()}


def test_command_line():
    cmd = harness_claude.build_command('research-high', 'claude-opus-5-5', 'high', ['Read', 'Write'], 'msg', ['/v'])
    assert cmd[:3] == ['claude', '-p', 'msg']
    assert cmd[cmd.index('--agent') + 1] == 'research-high' and cmd[cmd.index('--effort') + 1] == 'high'
    assert cmd[cmd.index('--permission-mode') + 1] == 'acceptEdits'
    assert cmd[cmd.index('--allowedTools') + 1] == 'Read,Write' and cmd[cmd.index('--add-dir') + 1] == '/v'
    assert cmd[cmd.index('--output-format') + 1] == 'json'
    assert '--setting-sources' not in cmd and '--effort' not in harness_claude.build_command('a', 'm', None, [], 'x')


def test_parse_reads_tokens_and_cost():
    out = harness_claude.parse(json.dumps(REPLY), '', 0)
    assert out == {'status': 'ok', 'tokens': 375, 'cost': 0.5, 'session_id': 's-1', 'report': 'готово'}
    assert harness_claude.parse(json.dumps({**REPLY, 'is_error': True}), '', 0)['status'] == 'failed'
    assert harness_claude.parse('not json', 'boom', 1)['status'] == 'failed'


def test_research_through_claude_is_ok_and_recorded(proj, claude):
    env = {**claude['env'], 'FAKE_WRITE': '# r\\n\\n## Problem\\nп\\n\\n## Recommendation\\nр\\n'}
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', model='claude-opus-5-5', env=env, host='claude')
    assert out['status'] == 'ok' and out['route']['state'] == 'approval_required'
    assert out['tokens'] == 375 and out['cost'] == 0.5 and out['report'] == 'готово'
    argv = claude['argv']()
    assert argv[argv.index('--agent') + 1] == 'research' and argv[argv.index('--add-dir') + 1] == str(proj['vault'])
    assert argv[argv.index('--allowedTools') + 1] == 'Read,Grep,Glob,Bash,Write,Skill'
    row = dict(proj['db'].execute('SELECT * FROM outcomes').fetchone())
    assert (row['harness'], row['status'], row['tokens'], row['cost']) == ('claude', 'ok', 375, 0.5)


def test_claude_error_reply_is_failed(proj, claude):
    env = {**claude['env'], 'FAKE_REPLY': json.dumps({**REPLY, 'is_error': True}), 'FAKE_EXIT': '1'}
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', model='m', env=env, host='claude')
    assert out['status'] == 'failed'
    assert [r['status'] for r in proj['db'].execute('SELECT status FROM outcomes')] == ['failed']


def test_claude_needs_a_model(proj, claude):
    with pytest.raises(WorkflowError, match='Модель claude'):
        pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', env=claude['env'], host='claude')


def test_claude_session_is_pinned_to_task_for_tokens(proj, claude, isolated_ledger):
    from devflow import transcripts
    env = {**claude['env'], 'FAKE_WRITE': '# r\\n\\n## Problem\\nп\\n\\n## Recommendation\\nр\\n'}
    pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', model='m', env=env, host='claude')
    assert [task for _, task in transcripts.load_ledger()['s-1']] == ['X']
    transcripts.mark_session('s-2', 'df-31-multi-harness-orchestrator')
    assert transcripts.load_ledger()['s-2'][0][1] == 'DF-31'


def test_hung_claude_is_killed_by_timeout_and_failed(proj, claude, tmp_path):
    exe = tmp_path / 'bin' / 'claude'
    exe.write_text('#!/bin/sh\nsleep 30\n')
    env = {**claude['env'], 'DEVFLOW_PHASE_TIMEOUT': '1'}
    out = pi.run_phase(proj['ctx'], proj['db'], 'x', 'research', model='m', env=env, host='claude')
    assert (out['status'], out['exit_code']) == ('failed', 124)
    assert 'timeout 1s' in out['stderr']
