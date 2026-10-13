import json
import os
import subprocess
from pathlib import Path

import pytest

from devflow import bench, bench_container, bench_runners, cli
from devflow.documents import WorkflowError

INSTANCE = {'instance_id': 'php-cs-fixer__php-cs-fixer-8367', 'image': 'swebench/php-cs-fixer-8367:latest',
            'test_patch': 'diff --git a/t.php b/t.php\n', 'patch': 'diff --git a/s.php b/s.php\n',
            'test_cmd': 'vendor/bin/phpunit tests/T.php'}


def fake_docker(test_exits=(1, 0), offline_exit=6, network_exists=True):
    """A Docker stand-in: records argv, answers inspect/create/exec; test runs exit with `test_exits` in order."""
    calls, state = [], {'tests': list(test_exits), 'network': network_exists}

    def execute(cmd, timeout, cwd=None, env=None):
        calls.append(list(cmd))
        if cmd[:3] == ['docker', 'network', 'inspect']:
            return subprocess.CompletedProcess(cmd, 0 if state['network'] else 1, 'true\n' if state['network'] else '', '')
        if cmd[:3] == ['docker', 'network', 'create']:
            state['network'] = True
            return subprocess.CompletedProcess(cmd, 0, '', '')
        if cmd[:2] == ['docker', 'create']:
            return subprocess.CompletedProcess(cmd, 0, 'cid123\n', '')
        if cmd[:2] == ['docker', 'exec']:
            script = cmd[-1]
            if script == bench_container.OFFLINE_SCRIPT:
                return subprocess.CompletedProcess(cmd, offline_exit, '', 'Could not resolve host')
            return subprocess.CompletedProcess(cmd, state['tests'].pop(0), 'Tests: 1\n', '')
        return subprocess.CompletedProcess(cmd, 0, '', '')
    execute.calls = calls
    return execute


def test_run_command_mounts_workdir_at_its_own_path_as_the_user():
    cmd = bench_container.run_command('c1', 'img:latest', '/work/pair', env_names=['CLAUDE_CODE_OAUTH_TOKEN'])
    assert cmd[:3] == ['docker', 'run', '-d']
    assert cmd[cmd.index('--user') + 1] == f'{os.getuid()}:{os.getgid()}'
    assert cmd[cmd.index('--network') + 1] == bench_container.NETWORK
    assert '-v' in cmd and cmd[cmd.index('-v') + 1] == '/work/pair:/work/pair' and cmd[cmd.index('-w') + 1] == '/work/pair'
    assert ['-e', 'CLAUDE_CODE_OAUTH_TOKEN'] == cmd[cmd.index('CLAUDE_CODE_OAUTH_TOKEN') - 1:cmd.index('CLAUDE_CODE_OAUTH_TOKEN') + 1]
    assert not any('=' in arg and arg.startswith('CLAUDE_CODE_OAUTH_TOKEN') for arg in cmd)
    assert cmd[-3:] == ['sleep', 'img:latest', 'infinity']


def test_executor_prefixes_docker_exec_and_stops_the_container_on_timeout():
    calls = []

    def execute(cmd, timeout):
        calls.append(cmd)
        if cmd[1] == 'exec':
            raise subprocess.TimeoutExpired(cmd, timeout)
        return subprocess.CompletedProcess(cmd, 0, '', '')
    run = bench_container.executor('c1', '/work/pair/repo', env={'DEVFLOW_STATE_DIR': '/work/pair/state'}, execute=execute)
    with pytest.raises(subprocess.TimeoutExpired):
        run(['sh', '-c', 'phpunit'], 7)
    assert calls[0] == ['docker', 'exec', '-w', '/work/pair/repo', '-e', 'DEVFLOW_STATE_DIR=/work/pair/state', 'c1', 'sh', '-c', 'phpunit']
    assert calls[1] == ['docker', 'rm', '-f', 'c1']


def test_docker_execute_closes_stdin(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, '', '')
    monkeypatch.setattr(subprocess, 'run', fake_run)
    bench_container.docker_execute(['docker', 'ps'], 5)
    assert seen['stdin'] is subprocess.DEVNULL and seen['timeout'] == 5 and seen['capture_output']


def test_host_executor_runs_in_cwd_with_added_env(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, '', '')
    monkeypatch.setattr(subprocess, 'run', fake_run)
    bench_container.host_executor('/work/pair/repo', env={'DEVFLOW_STATE_DIR': '/work/pair/state'})(['claude', '-p'], 9)
    assert seen['cwd'] == '/work/pair/repo' and seen['env']['DEVFLOW_STATE_DIR'] == '/work/pair/state'
    assert seen['env']['PATH'] == os.environ['PATH'] and seen['stdin'] is subprocess.DEVNULL


def test_runner_executor_follows_runner_mode(monkeypatch):
    assert bench_container.RUNNER_MODE == 'host'
    seen = []
    monkeypatch.setattr(bench_container, 'docker_execute', lambda cmd, timeout, cwd=None, env=None: seen.append((cmd, cwd)) or subprocess.CompletedProcess(cmd, 0, '', ''))
    bench_container.runner_executor('c1', '/work/repo')(['pi', '-p'], 1)
    assert seen == [(['pi', '-p'], '/work/repo')]
    monkeypatch.setattr(bench_container, 'RUNNER_MODE', 'container')
    bench_container.runner_executor('c1', '/work/repo')(['pi', '-p'], 1)
    assert seen[-1][0][:5] == ['docker', 'exec', '-w', '/work/repo', 'c1']


def test_ensure_network_creates_the_internal_network_once():
    execute = fake_docker(network_exists=False)
    assert bench_container.ensure_network(execute) is True
    assert execute.calls[1] == ['docker', 'network', 'create', '--internal', bench_container.NETWORK]
    assert bench_container.ensure_network(execute) is True
    assert sum(1 for c in execute.calls if c[:3] == ['docker', 'network', 'create']) == 1


def test_checkout_copies_testbed_from_a_throwaway_container(tmp_path):
    execute = fake_docker()
    dest = tmp_path / 'repo'
    dest.mkdir()
    (dest / 'stale').write_text('x')
    assert bench_container.checkout('img:latest', dest, execute) == dest
    assert not (dest / 'stale').exists()
    assert execute.calls[0] == ['docker', 'create', 'img:latest']
    assert execute.calls[1] == ['docker', 'cp', 'cid123:/testbed/.', str(dest)]
    assert execute.calls[2] == ['docker', 'rm', 'cid123']


def test_claude_probe_argv_isolates_the_host_session():
    cmd = bench_runners.claude_probe_command('claude-sonnet-5-5', 'low', output_format='stream-json')
    assert cmd[:3] == ['claude', '-p', bench_runners.PROBE_MESSAGE]
    assert cmd[cmd.index('--setting-sources') + 1] == 'project' and '--strict-mcp-config' in cmd
    assert cmd[cmd.index('--disallowedTools') + 1] == 'WebFetch,WebSearch' and cmd[cmd.index('--output-format') + 1] == 'stream-json'
    init = {'type': 'system', 'subtype': 'init', 'tools': ['Bash', 'Read']}
    assert bench_runners.claude_init('garbage\n' + json.dumps({'type': 'assistant'}) + '\n' + json.dumps(init)) == init
    assert bench_runners.claude_init('nothing') is None


def doctor_probe_execute(tools=('Bash', 'Read', 'Edit')):
    def execute(cmd, timeout):
        if cmd[0] == 'pi':
            session_dir = Path(cmd[cmd.index('--session-dir') + 1])
            message = {'role': 'assistant', 'provider': 'openai-codex', 'model': 'gpt-5.5', 'stopReason': 'stop'}
            (session_dir / 's.jsonl').write_text(json.dumps({'type': 'message', 'message': message}), encoding='utf-8')
            return subprocess.CompletedProcess(cmd, 0, '', '')
        model = cmd[cmd.index('--model') + 1]
        if cmd[cmd.index('--output-format') + 1] == 'stream-json':
            lines = [json.dumps({'type': 'system', 'subtype': 'init', 'tools': list(tools), 'mcp_servers': [], 'skills': [],
                                 'memory_paths': {}}), json.dumps({'type': 'result', 'is_error': False})]
            return subprocess.CompletedProcess(cmd, 0, '\n'.join(lines), '')
        return subprocess.CompletedProcess(cmd, 0, json.dumps({'is_error': False, 'modelUsage': {model: {}}}), '')
    return execute


@pytest.fixture
def instance_lookup(monkeypatch):
    monkeypatch.setattr(bench, 'instances', lambda dataset, split, ids: {ids[0]: dict(INSTANCE, instance_id=ids[0])})
    applied = []
    monkeypatch.setattr(bench, 'git_apply', lambda repo, patch: applied.append(patch))
    return applied


def test_doctor_all_green(tmp_path, instance_lookup):
    docker = fake_docker()
    result = bench.doctor('php-cs-fixer__php-cs-fixer-8367', execute=docker, probe_execute=doctor_probe_execute(),
                          workdir=tmp_path / 'work')
    assert result['ok'] is True and result['runner_mode'] == 'host'
    assert {c['check'] for c in result['checks']} >= {'network', 'claude web tools', 'offline', 'gold',
                                                      'probe pi openai-codex/gpt-5.5 low', 'probe claude claude-fable-5-1 low'}
    assert instance_lookup == [INSTANCE['test_patch'], INSTANCE['patch']]
    run = next(c for c in docker.calls if c[:2] == ['docker', 'run'])
    assert run[run.index('--user') + 1] == f'{os.getuid()}:{os.getgid()}' and run[run.index('--network') + 1] == 'devflow-bench'
    execs = [c for c in docker.calls if c[:2] == ['docker', 'exec']]
    assert execs[0][-1] == INSTANCE['test_cmd'] and execs[0][3] == str(tmp_path / 'work/repo')
    assert docker.calls[-1] == ['docker', 'rm', '-f', 'devflow-bench-doctor-php-cs-fixer__php-cs-fixer-8367']
    assert not (tmp_path / 'work').exists()


def test_doctor_flags_leaked_web_tools_open_network_and_tests_passing_without_gold(tmp_path, instance_lookup):
    docker = fake_docker(test_exits=(0, 0), offline_exit=0)
    result = bench.doctor('php-cs-fixer__php-cs-fixer-8331', execute=docker, probe_execute=doctor_probe_execute(tools=('Bash', 'WebSearch')),
                          workdir=tmp_path / 'work', keep=True)
    by_name = {c['check']: c for c in result['checks']}
    assert result['ok'] is False
    assert by_name['claude web tools']['ok'] is False and 'WebSearch' in by_name['claude web tools']['detail']
    assert by_name['offline']['ok'] is False and by_name['gold']['ok'] is False
    assert (tmp_path / 'work/repo').is_dir()


def test_doctor_rejects_an_instance_outside_every_set():
    with pytest.raises(WorkflowError, match='in no set'):
        bench.set_of_instance('nope-1')
    assert bench.set_of_instance('php-cs-fixer__php-cs-fixer-8367')['name'] == 'php-pilot'


def test_cli_bench_doctor_wires_instance_and_keep(monkeypatch):
    seen = {}
    monkeypatch.setattr(bench, 'doctor', lambda instance, keep=False: seen.update(instance=instance, keep=keep) or {'ok': True})
    assert cli.execute(cli.parser().parse_args(['bench', 'doctor', 'x-1', '--keep'])) == {'ok': True}
    assert seen == {'instance': 'x-1', 'keep': True}
