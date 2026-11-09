import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from devflow import pi


@pytest.fixture
def browser(tmp_path, monkeypatch):
    verdict = tmp_path / 'demo/verdict.md'
    verdict.parent.mkdir()
    verdict.write_text('## Вердикт: 1/1 ✅')
    message = 'Аргументы: slug: demo; Проверить\nВердикт: /tmp/devflow-smoke/demo/verdict.md'
    children, signals, calls = [], [], []

    class Child:
        def __init__(self, command, **kwargs):
            assert kwargs['start_new_session'] is True
            self.pid = 900000 + len(children)
            self.returncode = 0
            children.append(self)

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            assert timeout is not None
            return self.returncode

    def killpg(pid, sig):
        signals.append((pid, sig))
        if sig == 0 and (pid, signal.SIGKILL) in signals:
            raise ProcessLookupError

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(pi.subprocess, 'Popen', Child)
    monkeypatch.setattr(pi.subprocess, 'run', run)
    monkeypatch.setattr(pi.os, 'killpg', killpg)
    return {'cwd': tmp_path}, message, {'DEVFLOW_SMOKE_DIR': str(tmp_path)}, children, signals, calls, verdict


def test_browser_exited_parents_still_kill_descendants(browser):
    ctx, message, env, children, signals, calls, verdict = browser
    result = pi._browser_process(['fake-pi'], ctx, message, env, 1)
    assert result.returncode == 0
    assert len(children) == 2
    assert all((child.pid, signal.SIGKILL) in signals for child in children)
    assert calls[-1][-2:] == ['stop-task', 'demo']


def test_browser_second_spawn_failure_cleans_first(browser, monkeypatch):
    ctx, message, env, children, signals, calls, verdict = browser
    spawn = pi.subprocess.Popen
    def popen(*args, **kwargs):
        if children:
            raise OSError('second spawn')
        return spawn(*args, **kwargs)
    monkeypatch.setattr(pi.subprocess, 'Popen', popen)
    with pytest.raises(OSError, match='second spawn'):
        pi._browser_process(['fake-pi'], ctx, message, env, 1)
    assert (children[0].pid, signal.SIGKILL) in signals
    assert calls[-1][-2:] == ['stop-task', 'demo']
    assert not verdict.exists()


def test_browser_cleanup_error_attempts_both_and_stop(browser, monkeypatch):
    ctx, message, env, children, signals, calls, verdict = browser
    original = pi.os.killpg
    def denied(pid, sig):
        if pid == 900000:
            raise PermissionError('cleanup denied')
        original(pid, sig)
    monkeypatch.setattr(pi.os, 'killpg', denied)
    result = pi._browser_process(['fake-pi'], ctx, message, env, 1)
    assert result.returncode != 0 and 'cleanup denied' in result.stderr
    assert (children[1].pid, signal.SIGKILL) in signals
    assert calls[-1][-2:] == ['stop-task', 'demo']
    assert not verdict.exists()


@pytest.mark.parametrize('gone_at', [0, 1, 2])
def test_cleanup_group_disappearance(monkeypatch, gone_at):
    calls = []
    class Child:
        pid = 900001
        def wait(self, timeout=None):
            assert timeout is not None
            return 0
    def killpg(pid, sig):
        calls.append(sig)
        if len(calls) > gone_at:
            raise ProcessLookupError
    monkeypatch.setattr(pi.os, 'killpg', killpg)
    pi._cleanup_process_group(Child(), grace=0.01)
    assert calls[0] == signal.SIGTERM


# Linux subreaper keeps orphaned test grandchildren reapable in the isolated supervisor.
TREE_PROBE = r'''
import ctypes, os, signal, subprocess, sys, tempfile, time
from pathlib import Path
from devflow import pi
ctypes.CDLL(None).prctl(36, 1, 0, 0, 0)
mode = sys.argv[1]
children = []
real_popen = subprocess.Popen
child_script = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(30)"
with tempfile.TemporaryDirectory() as folder:
    ready = Path(folder) / 'ready'
    parent_script = """
import subprocess,sys,time
from pathlib import Path
p = subprocess.Popen([sys.executable, '-c', sys.argv[2]], stdout=subprocess.PIPE, text=True)
assert p.stdout.readline().strip() == 'ready'
Path(sys.argv[1]).write_text(str(p.pid))
print('partial', flush=True)
print('limit', file=sys.stderr, flush=True)
if sys.argv[3] == 'live': time.sleep(30)
"""
    def spawn(command, **kwargs):
        assert command[0] == 'pi' and kwargs['start_new_session']
        p = real_popen([sys.executable, '-c', parent_script, str(ready), child_script, mode], **kwargs)
        children.append(p)
        deadline = time.monotonic() + 2
        while not ready.exists():
            assert time.monotonic() < deadline
            time.sleep(.005)
        return p
    pi.subprocess.Popen = spawn
    pi.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError('ungrouped run forbidden'))
    cleanup = pi._cleanup_process_group
    pi._cleanup_process_group = lambda p: cleanup(p, grace=.05)
    pi.extension_path = lambda env: Path('/fake-extension')
    start = time.monotonic()
    try:
        if mode == 'exited':
            result = pi._run_process({'cwd': folder}, 'reader', 'body', [], None, 'task', dict(os.environ), 1)
            assert result.stdout == 'partial\n' and result.stderr == 'limit\n'
        else:
            try:
                pi._run_process({'cwd': folder}, 'reader', 'body', [], None, 'task', dict(os.environ), .15)
                raise AssertionError('timeout missing')
            except subprocess.TimeoutExpired as exc:
                assert exc.stdout == 'partial\n' and exc.stderr == 'limit\n'
        pid = int(ready.read_text())
        deadline = time.monotonic() + 1
        while True:
            status = Path(f'/proc/{pid}/stat')
            if not status.exists() or status.read_text().split()[2] == 'Z': break
            assert time.monotonic() < deadline, 'descendant active'
            time.sleep(.005)
        assert time.monotonic() - start < 3
    finally:
        for p in children:
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            p.wait(timeout=1)
        if ready.exists():
            pid = int(ready.read_text())
            try: os.kill(pid, signal.SIGKILL)
            except ProcessLookupError: pass
            try: os.waitpid(pid, 0)
            except ChildProcessError: pass
print('tree clean')
'''


@pytest.mark.parametrize('mode', ['exited', 'live'])
def test_local_process_tree(mode):
    result = subprocess.run([sys.executable, '-c', TREE_PROBE, mode],
                            capture_output=True, text=True, timeout=6,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'scripts')})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == 'tree clean'
