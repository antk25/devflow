import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'evidence', Path(__file__).parents[1] / 'scripts/browser_session_evidence.py')
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def process(pid, ppid=1, start='100', session=False, args=(), state='S'):
    return dict(pid=pid, ppid=ppid, starttime=start, sessions=['abc'] if session else [],
                args=list(args), state=state)


def captured(tmp_path):
    pidfile = tmp_path / 'daemon.pid'
    pidfile.write_text('10')
    table = {10: process(10, session=True, args=['/cli/daemon/daemon.js']),
             11: process(11, ppid=10, args=['chrome', '--user-data-dir=/tmp/isolated']),
             12: process(12, ppid=11), 99: process(99, args=['chrome'])}
    return evidence.capture('abc', pidfile, table), table


def test_capture_proves_metadata_profile_descendants(tmp_path):
    record, table = captured(tmp_path)
    assert record['profiles'] == ['/tmp/isolated']
    assert [p['pid'] for p in record['processes']] == [10, 11, 12]
    assert [p['pid'] for p in evidence.verify(record, table)] == [10, 11, 12]


def test_reparented_child_is_still_live(tmp_path):
    record, _ = captured(tmp_path)
    assert evidence.verify(record, {12: process(12)})


def test_pid_reuse_and_unrelated_chrome_are_not_leaks(tmp_path):
    record, _ = captured(tmp_path)
    assert evidence.verify(record, {12: process(12, start='101'), 99: process(99)}) == []


def test_late_child_inherits_session_or_profile(tmp_path):
    record, _ = captured(tmp_path)
    assert len(evidence.verify(record, {
        20: process(20, session=True),
        21: process(21, args=['--user-data-dir=/tmp/isolated']),
        22: process(22, ppid=21)})) == 3


def test_zombie_is_not_running(tmp_path):
    record, _ = captured(tmp_path)
    assert evidence.verify(record, {12: process(12, state='Z')}) == []


def test_unreadable_unrelated_environment_is_not_a_browser_failure(tmp_path, monkeypatch):
    directory = tmp_path / '405'
    directory.mkdir()
    fields = ['S', '1'] + ['0'] * 17 + ['100']
    (directory / 'stat').write_text('405 (sd-pam) ' + ' '.join(fields))
    (directory / 'cmdline').write_bytes(b'(sd-pam)')
    original = Path.read_bytes

    def denied(path):
        if path.name == 'environ':
            raise PermissionError('not dumpable')
        return original(path)

    monkeypatch.setattr(Path, 'read_bytes', denied)
    assert evidence.processes(tmp_path)[405]['sessions'] == []
    (directory / 'cmdline').write_bytes(b'chrome')
    with pytest.raises(PermissionError):
        evidence.processes(tmp_path)


def test_rejects_wrong_metadata_and_missing_profile(tmp_path):
    pidfile = tmp_path / 'daemon.pid'
    pidfile.write_text('10')
    with pytest.raises(ValueError, match='not this session'):
        evidence.capture('abc', pidfile, {10: process(10)})
    with pytest.raises(ValueError, match='profile'):
        evidence.capture('abc', pidfile, {
            10: process(10, session=True, args=['/cli/daemon/daemon.js'])})
