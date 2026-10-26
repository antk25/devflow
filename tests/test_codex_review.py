import json
import os
import signal
import sys
import re
import shlex
import subprocess
from pathlib import Path

import pytest

from devflow import cli, codex_review
from devflow.guard import permission_decision

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def transport(tmp_path, monkeypatch):
    ctx = {'cwd': tmp_path / 'repo'}
    ctx['cwd'].mkdir()
    calls = []
    children = []
    state = dict(code=0, stdout=b'codex\nNo actionable regressions\n' * 4096,
                 stderr=b'diagnostic\n' * 4096, timeout=False, missing=False, cleanup=False)

    class FakeCodex:
        pid = 987654

        def __init__(self, argv, **kwargs):
            assert argv[:2] == ['codex', 'review'], 'Unknown executable refused'
            calls.append((argv, kwargs))
            if state['missing']:
                raise FileNotFoundError('codex missing')
            children.append(self)
            self.returncode = None
            kwargs['stdout'].write(state['stdout'])
            kwargs['stderr'].write(state['stderr'])

        def wait(self, timeout=None):
            assert timeout == 600 or timeout == 0.01
            if state['timeout']:
                raise subprocess.TimeoutExpired('safe fake', timeout)
            self.returncode = state['code']
            return self.returncode

    def cleanup(child):
        assert child in children
        child.cleaned = True
        if state['cleanup']:
            raise PermissionError('cleanup refused')

    monkeypatch.setattr(subprocess, 'Popen', FakeCodex)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('Unknown executable refused'))
    monkeypatch.setattr(codex_review, '_cleanup_process_group', cleanup)
    return ctx, calls, children, state


def evidence(result, ctx):
    for key in ('request', 'stdout', 'stderr', 'manifest'):
        path = Path(result[key])
        assert path.is_file() and not path.resolve().is_relative_to(ctx['cwd'])
    assert json.loads(Path(result['manifest']).read_text()) == result


@pytest.mark.parametrize('mode', ['base', 'commit', 'uncommitted', 'message_file'])
def test_modes_and_full_streams(transport, tmp_path, mode, monkeypatch):
    ctx, calls, children, state = transport
    monkeypatch.setenv('TMPDIR', str(ctx['cwd']))
    prompt = 'Only read; $(never execute) > output & | secrets are fictional'
    request = tmp_path / 'request.md'
    request.write_text(prompt)
    value = {'base': 'feature/base', 'commit': 'abc123', 'uncommitted': True,
             'message_file': request}[mode]
    result = codex_review.run_review(ctx, **{mode: value}, title='title; $(literal)')
    argv, kw = calls[0]
    expected = ['codex', 'review']
    if mode != 'message_file':
        expected += ['--' + mode] + ([] if mode == 'uncommitted' else [value])
    expected += ['--title', 'title; $(literal)']
    if mode == 'message_file':
        expected += ['--', prompt]
        assert Path(result['request']).read_text() == prompt
    assert argv == expected
    assert kw['stdin'] == subprocess.DEVNULL and kw['cwd'] == ctx['cwd']
    assert kw['shell'] is False and kw['start_new_session'] is True
    assert children[0].cleaned
    assert Path(result['stdout']).read_bytes() == state['stdout']
    assert Path(result['stderr']).read_bytes() == state['stderr']
    assert result['exit_code'] == 0 and result['error'] is None
    evidence(result, ctx)
    before = Path(result['manifest']).read_bytes()
    again = codex_review.run_review(ctx, uncommitted=True)
    assert again['manifest'] != result['manifest']
    assert Path(result['manifest']).read_bytes() == before
    assert list(ctx['cwd'].iterdir()) == []


@pytest.mark.parametrize('kwargs', [dict(), dict(base='main', commit='abc'),
    dict(base=''), dict(base='x\0y'), dict(uncommitted=True, title=''),
    dict(uncommitted=True, timeout=0), dict(uncommitted=True, timeout=-1),
    dict(uncommitted=True, timeout=float('nan')), dict(uncommitted=True, timeout=float('inf')),
    dict(uncommitted=True, timeout=True), dict(message_file='/missing/request.md')])
def test_invalid_before_spawn(transport, kwargs):
    ctx, calls, _, _ = transport
    result = codex_review.run_review(ctx, **kwargs)
    assert calls == [] and result['error'] and result['exit_code'] != 0
    evidence(result, ctx)


@pytest.mark.parametrize('content', ['', '-', 'nul\0text', b'\xff'])
def test_bad_prompt_before_spawn(transport, tmp_path, content):
    ctx, calls, _, _ = transport
    path = tmp_path / 'request.md'
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    result = codex_review.run_review(ctx, message_file=path)
    assert calls == [] and result['error']
    evidence(result, ctx)


@pytest.mark.parametrize('change,code', [({'code': 1, 'stderr': b'auth failure'}, 1),
    ({'code': -15}, -15), ({'missing': True}, 1), ({'stdout': b''}, 0),
    ({'timeout': True}, 124), ({'cleanup': True}, 1)])
def test_failures_keep_evidence(transport, change, code):
    ctx, calls, children, state = transport
    state.update(change)
    result = codex_review.run_review(ctx, uncommitted=True, timeout=0.01)
    assert result['exit_code'] == code and result['error']
    assert result['timed_out'] == state['timeout']
    if children:
        assert children[0].cleaned
    assert Path(result['stdout']).read_bytes() == (b'' if state['missing'] else state['stdout'])
    assert Path(result['stderr']).read_bytes() == (b'' if state['missing'] else state['stderr'])
    evidence(result, ctx)


def test_artifact_failure_no_spawn(transport, monkeypatch):
    ctx, calls, _, _ = transport
    def fail(*a, **k):
        raise PermissionError('artifact preparation failed')
    monkeypatch.setattr(codex_review.tempfile, 'mkdtemp', fail)
    with pytest.raises(PermissionError):
        codex_review.run_review(ctx, uncommitted=True)
    assert calls == []


def test_cli_before_connect(transport, monkeypatch):
    ctx, calls, _, _ = transport
    monkeypatch.setattr(cli, 'context', lambda cwd: ctx)
    monkeypatch.setattr(cli, 'connect', lambda *a, **k: pytest.fail('SQLite opened'))
    result = cli.execute(cli.parser().parse_args(['codex-review', '--base', 'main', '--title', 'task']))
    assert result['exit_code'] == 0 and len(calls) == 1
    for args in [[], ['--base', 'a', '--commit', 'b'], ['--executable', 'anything']]:
        with pytest.raises(SystemExit):
            cli.parser().parse_args(['codex-review', *args])


def test_safe_fake_process_uses_existing_group_cleanup(tmp_path, monkeypatch):
    from devflow.pi import _cleanup_process_group
    fake = tmp_path / 'safe_fake.py'
    fake.write_text('import sys\nprint("codex\\nNo actionable regressions", flush=True)\n'
                    'print("fake diagnostic", file=sys.stderr, flush=True)\n')
    repo = tmp_path / 'repo'
    repo.mkdir()
    real_popen = subprocess.Popen
    children = []

    def spawn(argv, **kwargs):
        assert argv == ['codex', 'review', '--uncommitted'], 'Unknown executable refused'
        child = real_popen([sys.executable, str(fake)], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, 'Popen', spawn)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('Unknown executable refused'))
    monkeypatch.setattr(codex_review, '_cleanup_process_group',
                        lambda child: _cleanup_process_group(child, grace=0.01))
    try:
        result = codex_review.run_review({'cwd': repo}, uncommitted=True)
        assert result['exit_code'] == 0 and result['error'] is None
        assert 'No actionable regressions' in Path(result['stdout']).read_text()
        assert Path(result['stderr']).read_text() == 'fake diagnostic\n'
        assert children[0].poll() == 0
        with pytest.raises(ProcessLookupError):
            os.killpg(children[0].pid, 0)
    finally:
        for child in children:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=2)


def test_instructions_real_guard_and_failure_contract(tmp_path):
    config = tmp_path / 'policy.json'
    for filename in ('skills/xreview/SKILL.md', 'agents/crossreview.md'):
        text = (ROOT / filename).read_text()
        commands = re.findall(r'(devflow codex-review[^`\n]*)', text)
        assert commands
        for command in commands:
            command = (command.replace('<base>', 'main').replace('<sha>', 'abc123')
                       .replace('<slug>', 'task').replace('<tmp>', str(tmp_path)))
            args = shlex.split(command)
            assert args[:2] == ['devflow', 'codex-review']
            cli.parser().parse_args(args[1:])
            for decision in ('allow', 'ask', 'deny'):
                config.write_text(json.dumps({'permissions': {decision: ['Bash(devflow codex-review:*)']}}))
                verdict = permission_decision(dict(toolName='bash', input={'command': command},
                                                   cwd=str(tmp_path)), [config])
                assert verdict['decision'] == decision and verdict['rule'] != 'shell-uncertain'
        for marker in ('DEVNULL', '600 секунд', 'REVIEW_STALE', 'base/HEAD', 'diff',
                       'cleanup', 'вердикта', 'только чит', 'read', 'stderr', 'manifest'):
            assert marker in text
        assert 'Код транспорта 0' in text
    cross = (ROOT / 'agents/crossreview.md').read_text()
    assert 'SECOND_OPINION_NEEDED' in cross and 'Fable 5.1 high' in cross
    assert 'codex login status' in cross
    for command in ('codex review --base main </dev/null > /tmp/out 2>&1',
                    'codex review "$(< /tmp/request.md)"'):
        verdict = permission_decision(dict(toolName='bash', input={'command': command},
                                           cwd=str(tmp_path)), [config])
        assert verdict['decision'] == 'deny' and verdict['rule'] == 'shell-uncertain'
