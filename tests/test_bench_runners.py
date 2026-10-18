import json
import subprocess
from pathlib import Path

import pytest

from devflow import bench_runners
from devflow.documents import WorkflowError

SPEC = {'runner': 'claude', 'model': 'claude-sonnet-5-5', 'effort': 'low'}
REPLY = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'готово', 'session_id': 'sess-1',
         'duration_ms': 12345, 'num_turns': 7, 'total_cost_usd': 0.42,
         'modelUsage': {'claude-sonnet-5-5': {'inputTokens': 10, 'outputTokens': 200, 'cacheReadInputTokens': 3000,
                                              'cacheCreationInputTokens': 400, 'thinkingTokens': 50, 'costUSD': 0.4},
                        'claude-haiku-4-5': {'inputTokens': 5, 'outputTokens': 20, 'cacheReadInputTokens': 0,
                                             'cacheCreationInputTokens': 0, 'thinkingTokens': 0, 'costUSD': 0.02}}}


def assistant(model, effort, tools=()):
    content = [{'type': 'text', 'text': 'x'}] + [{'type': 'tool_use', 'name': t, 'input': {}} for t in tools]
    return {'type': 'assistant', 'effort': effort, 'message': {'role': 'assistant', 'model': model, 'content': content}}


def write_transcript(home, cwd, session_id):
    project = home / '.claude/projects' / str(cwd).replace('/', '-').replace('.', '-').replace('_', '-')
    (project / session_id / 'subagents').mkdir(parents=True)
    main = [{'type': 'user', 'message': {'role': 'user', 'content': 'hi'}},
            assistant('claude-sonnet-5-5', 'low', ['Bash', 'Read']), 'not json',
            assistant('claude-sonnet-5-5', 'low', ['Bash'])]
    (project / f'{session_id}.jsonl').write_text('\n'.join(l if isinstance(l, str) else json.dumps(l) for l in main))
    sub = [assistant('claude-haiku-4-5', 'medium', ['Grep'])]
    (project / session_id / 'subagents/agent-1.jsonl').write_text('\n'.join(json.dumps(l) for l in sub))
    return project


def test_claude_command_argv():
    cmd = bench_runners.claude_command('research', SPEC, 'u-1', 'DevFlow Phase — research.', 5.0, Path('/sb/home/agents-research.json'))
    assert cmd[:3] == ['claude', '-p', 'DevFlow Phase — research.']
    assert cmd[cmd.index('--agents') + 1] == '/sb/home/agents-research.json' and cmd[cmd.index('--agent') + 1] == 'research'
    assert cmd[cmd.index('--model') + 1] == 'claude-sonnet-5-5' and cmd[cmd.index('--effort') + 1] == 'low'
    assert cmd[cmd.index('--session-id') + 1] == 'u-1' and cmd[cmd.index('--output-format') + 1] == 'json'
    assert cmd[cmd.index('--permission-mode') + 1] == 'bypassPermissions' and cmd[cmd.index('--max-budget-usd') + 1] == '5.0'
    assert cmd[-len(bench_runners.CLAUDE_ISOLATION):] == bench_runners.CLAUDE_ISOLATION
    assert '--max-budget-usd' not in bench_runners.claude_command('plan', SPEC, 'u', 'm', None, Path('a.json'))


def test_claude_agent_comes_from_the_phase_agent_file():
    agent = bench_runners.claude_agent('implement')['implement']
    assert 'Bash' in agent['tools'] and 'Edit' in agent['tools'] and 'implement' in agent['prompt']
    assert agent['description']
    with pytest.raises(WorkflowError, match='Unknown phase'):
        bench_runners.claude_agent('review')


def test_claude_metrics_sums_usage_and_reads_the_transcript(tmp_path):
    cwd = tmp_path / 'sb/a__b.c/repo'
    write_transcript(tmp_path / 'home', cwd, 'sess-1')
    m = bench_runners.claude_metrics(json.dumps(REPLY), tmp_path / 'home', cwd)
    assert m['model_actual'] == 'claude-sonnet-5-5' and m['models'] == ['claude-haiku-4-5', 'claude-sonnet-5-5']
    assert (m['input'], m['output'], m['reasoning'], m['cache_read'], m['cache_write']) == (15, 220, 50, 3000, 400)
    assert m['cost_usd'] == 0.42 and m['cost_source'] == 'anthropic-list' and m['duration_s'] == 12.3 and m['turns'] == 7
    assert m['effort_actual'] == 'low,medium' and m['tools'] == {'Bash': 2, 'Read': 1, 'Grep': 1}
    assert m['session_id'] == 'sess-1' and m['is_error'] is False


def test_claude_metrics_without_reply_or_transcript(tmp_path):
    m = bench_runners.claude_metrics('', tmp_path, tmp_path / 'repo', 'nope')
    assert m['model_actual'] is None and m['input'] == 0 and m['cost_usd'] == 0 and m['tools'] == {} and m['effort_actual'] is None


def test_claude_error_classes():
    proc = subprocess.CompletedProcess([], 0, '', '')
    assert bench_runners.claude_error({'subtype': 'error_max_budget_usd', 'result': 'over'}, proc) == ('budget', 'over')
    assert bench_runners.claude_error({'is_error': True, 'result': 'Not logged in'}, proc) == ('api', 'Not logged in')
    assert bench_runners.claude_error({'is_error': False, 'subtype': 'success'}, proc) == (None, None)
    assert bench_runners.claude_error(None, subprocess.CompletedProcess([], 1, '', 'boom')) == ('api', 'boom')


def test_run_phase_claude(tmp_path):
    sb = {'home': tmp_path / 'home', 'repo': tmp_path / 'repo'}
    sb['home'].mkdir()
    seen = []

    def execute(cmd, timeout):
        seen.append((cmd, timeout))
        return subprocess.CompletedProcess(cmd, 0, json.dumps(REPLY), '')
    result = bench_runners.run_phase(execute, 'claude', 'plan', SPEC, 'msg', sb, 60, 5.0, home=tmp_path / 'home')
    cmd, timeout = seen[0]
    agents = json.loads(Path(cmd[cmd.index('--agents') + 1]).read_text())
    assert set(agents) == {'plan'} and timeout == 60 and cmd[cmd.index('--agent') + 1] == 'plan'
    assert result['error'] is None and result['report'] == 'готово' and result['metrics']['cost_usd'] == 0.42
    assert result['metrics']['session_id'] == cmd[cmd.index('--session-id') + 1]

    def slow(cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)
    result = bench_runners.run_phase(slow, 'claude', 'plan', SPEC, 'msg', sb, 60, None, home=tmp_path / 'home')
    assert result['error'] == 'timeout' and result['metrics']['duration_s'] == 60.0


PI_SPEC = {'runner': 'pi', 'model': 'openai-codex/gpt-5.5', 'effort': 'low'}


def pi_reply(stop='toolUse', tools=('bash',), usage=True, model='gpt-5.5', error=None):
    content = [{'type': 'text', 'text': 'x'}] + [{'type': 'toolCall', 'name': t, 'arguments': {}} for t in tools]
    u = {'input': 100, 'output': 20, 'cacheRead': 300, 'cacheWrite': 40, 'reasoning': 7, 'totalTokens': 467,
         'cost': {'input': 0.001, 'output': 0.0002, 'cacheRead': 0, 'cacheWrite': 0, 'total': 0.0012}} if usage else None
    return {'type': 'message', 'message': {'role': 'assistant', 'provider': 'openai-codex', 'model': model,
                                           'stopReason': stop, 'usage': u, 'errorMessage': error, 'content': content}}


def write_pi_session(session_dir, replies):
    session_dir.mkdir(parents=True, exist_ok=True)
    lines = [{'type': 'session', 'version': 3, 'id': 'u-1', 'cwd': '/sb/repo'},
             {'type': 'model_change', 'provider': 'openai-codex', 'modelId': 'gpt-5.5'},
             {'type': 'thinking_level_change', 'thinkingLevel': 'low'}, 'not json',
             {'type': 'message', 'message': {'role': 'user', 'content': 'hi'}}, *replies]
    (session_dir / '2026-10-15T10-00-00-000Z_u-1.jsonl').write_text(
        '\n'.join(l if isinstance(l, str) else json.dumps(l) for l in lines), encoding='utf-8')


def test_pi_command_argv(tmp_path):
    sb = {'dir': tmp_path, 'home': tmp_path / 'home', 'repo': tmp_path / 'repo'}
    cmd = bench_runners.pi_command('implement', PI_SPEC, tmp_path / 'home/pi-sessions', 'u-1', 'DevFlow Phase — implement.', sb)
    assert cmd[:2] == ['pi', '-p'] and cmd[-1] == 'DevFlow Phase — implement.'
    assert '--no-session' not in cmd and '--no-extensions' in cmd and '--no-context-files' in cmd
    assert cmd[cmd.index('--session-dir') + 1] == str(tmp_path / 'home/pi-sessions') and cmd[cmd.index('--session-id') + 1] == 'u-1'
    assert cmd[cmd.index('--model') + 1] == 'openai-codex/gpt-5.5:low'
    body = Path(cmd[cmd.index('--append-system-prompt') + 1])
    assert body == tmp_path / 'pi-agent-implement.md' and 'implement' in body.read_text()
    assert set(cmd[cmd.index('--tools') + 1].split(',')) == {'read', 'grep', 'find', 'ls', 'bash', 'write', 'edit'}
    assert not any('claude' in a for a in cmd[:-1])


def test_pi_metrics_sums_replies(tmp_path):
    write_pi_session(tmp_path / 's', [pi_reply(tools=('bash', 'read')), pi_reply(stop='stop', tools=())])
    m = bench_runners.pi_metrics(tmp_path / 's', 12.34)
    assert m['runner'] == 'pi' and m['model_actual'] == 'openai-codex/gpt-5.5' and m['models'] == ['openai-codex/gpt-5.5']
    assert (m['input'], m['output'], m['reasoning'], m['cache_read'], m['cache_write']) == (200, 40, 14, 600, 80)
    assert m['cost_usd'] == 0.0024 and m['cost_source'] == 'pi-catalog' and m['duration_s'] == 12.3 and m['turns'] == 2
    assert m['effort_actual'] == 'low' and m['tools'] == {'bash': 1, 'read': 1} and m['is_error'] is False
    empty = bench_runners.pi_metrics(tmp_path / 'none', 1)
    assert empty['model_actual'] is None and empty['input'] == 0 and empty['turns'] == 0 and empty['tools'] == {}


def test_run_phase_pi(tmp_path):
    sb = {'dir': tmp_path, 'home': tmp_path / 'home', 'repo': tmp_path / 'repo'}
    sb['home'].mkdir()
    seen = []

    def execute(cmd, timeout):
        seen.append((cmd, timeout))
        write_pi_session(Path(cmd[cmd.index('--session-dir') + 1]), [pi_reply(), pi_reply(stop='stop', tools=())])
        return subprocess.CompletedProcess(cmd, 0, 'готово', '')
    result = bench_runners.run_phase(execute, 'pi', 'implement', PI_SPEC, 'msg', sb, 60, 5.0)
    cmd, timeout = seen[0]
    session_id = cmd[cmd.index('--session-id') + 1]
    assert timeout == 60 and '--max-budget-usd' not in cmd
    assert cmd[cmd.index('--session-dir') + 1] == str(sb['home'] / 'pi-sessions' / session_id)
    assert result['error'] is None and result['report'] == 'готово'
    assert result['metrics']['input'] == 200 and result['metrics']['session_id'] == session_id

    def failing(cmd, timeout):
        write_pi_session(Path(cmd[cmd.index('--session-dir') + 1]),
                         [pi_reply(stop='error', tools=(), usage=False, model='gpt-6-astra', error="Codex error: The 'gpt-6-astra' model is not supported")])
        return subprocess.CompletedProcess(cmd, 0, '', '')
    result = bench_runners.run_phase(failing, 'pi', 'plan', {**PI_SPEC, 'model': 'openai-codex/gpt-6-astra'}, 'msg', sb, 60, None)
    assert result['error'] == 'api' and 'gpt-6-astra' in result['error_text'] and result['metrics']['input'] == 0

    def silent(cmd, timeout):
        return subprocess.CompletedProcess(cmd, 1, '', 'boom')
    result = bench_runners.run_phase(silent, 'pi', 'plan', PI_SPEC, 'msg', sb, 60, None)
    assert result['error'] == 'api' and result['error_text'] == 'boom'

    def slow(cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)
    result = bench_runners.run_phase(slow, 'pi', 'plan', PI_SPEC, 'msg', sb, 60, None)
    assert result['error'] == 'timeout' and result['metrics']['duration_s'] == 60.0
    with pytest.raises(WorkflowError, match='unknown runner'):
        bench_runners.run_phase(execute, 'codex', 'plan', PI_SPEC, 'msg', sb, 60, None)
