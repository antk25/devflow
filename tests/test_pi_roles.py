import json
import os
import subprocess
from pathlib import Path

import pytest

from devflow import cli, pi, policy
from devflow.documents import WorkflowError


@pytest.fixture
def runner(tmp_path, monkeypatch):
    rules = tmp_path / 'rules.md'
    rules.write_text('Общие правила')
    monkeypatch.setenv('DEVFLOW_INSTRUCTIONS', str(rules))
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(tmp_path / 'absent.json'))
    monkeypatch.setattr(pi.shutil, 'which', lambda *a, **k: '/fake/pi')
    monkeypatch.setattr(pi, 'extension_path', lambda env: Path('/extension.ts'))
    monkeypatch.setattr(pi, 'settings_path', lambda env: tmp_path / 'settings.json')
    return {'cwd': tmp_path, 'vault': tmp_path / 'vault', 'project': 'demo'}


@pytest.mark.parametrize('role', pi.ROLES)
def test_roles_state_independent(runner, monkeypatch, role):
    def forbidden(*args, **kwargs):
        pytest.fail('Роль не должна обращаться к состоянию фаз')
    for name in ('route', 'start', 'interrupt'):
        monkeypatch.setattr(pi, name, forbidden)
    calls = []
    def execute(command, **kwargs):
        calls.append((command, kwargs))
        assert Path(command[command.index('--append-system-prompt') + 1]).exists()
        return subprocess.CompletedProcess(command, 0, 'находок нет', '')
    monkeypatch.setattr(pi.subprocess, 'run', execute)
    result = pi.run_agent(runner, role, 'Независимое задание', model='anthropic/model:high')
    assert result['host'] == 'pi' and result['exit_code'] == 0
    assert result['model_source'] == 'override'
    assert result['executor'] == 'anthropic/model:high'
    command, kwargs = calls[0]
    assert command[0] == 'pi' and '--no-session' in command
    assert kwargs['stdin'] == subprocess.DEVNULL and kwargs['timeout'] == 600
    assert not Path(command[command.index('--append-system-prompt') + 1]).exists()
    assert not (runner['cwd'] / '.devflow').exists()


def test_cli_state_bypasses_connect(runner, monkeypatch, tmp_path):
    message = tmp_path / 'message.md'
    message.write_text('Задание')
    monkeypatch.setattr(cli, 'context', lambda cwd: runner)
    monkeypatch.setattr(cli, 'connect', lambda *a, **k: pytest.fail('DB opened'))
    monkeypatch.setattr(pi, 'run_agent', lambda ctx, role, text, **kw: {'report': text})
    assert cli.execute(cli.parser().parse_args(['agent', 'run', 'crossreview', '--message-file', str(message)])) == {'report': 'Задание'}


@pytest.mark.parametrize('code,report', [(0, ''), (1, 'partial'), (-15, 'partial')])
def test_incomplete(runner, monkeypatch, code, report):
    monkeypatch.setattr(pi.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess([], code, report, 'error'))
    result = pi.run_agent(runner, 'crossreview', 'task')
    assert result['exit_code'] == code and 'не завершён' in result['warning']


def test_timeout_retains_partial_report(runner, monkeypatch):
    def timeout(*a, **k):
        raise subprocess.TimeoutExpired('pi', 1, output=b'partial', stderr=b'limit')
    monkeypatch.setattr(pi.subprocess, 'run', timeout)
    result = pi.run_agent(runner, 'second-opinion', 'task', timeout=1)
    assert result['exit_code'] == 124 and result['report'] == 'partial'
    assert result['stderr'] == 'limit'


def test_role_policy_independent_and_legacy():
    env = {'PI_PROVIDER': 'provider', 'PI_MODEL': 'current', 'PI_REASONING_LEVEL': 'low'}
    cfg = {'pi': {'roles': {'second-opinion': {'model': 'anthropic/other', 'effort': 'high'}}}}
    assert policy.resolve_pi_role(cfg, 'crossreview', env)['model'] == 'provider/current:low'
    assert policy.resolve_pi_role(cfg, 'second-opinion', env)['model'] == 'anthropic/other:high'
    assert policy.resolve_pi_role(cfg, 'second-opinion', env, 'provider/explicit')['model_source'] == 'override'
    assert policy.resolve_pi_role(None, 'second-opinion', {})['model_source'] == 'default'


@pytest.mark.parametrize('role', ['../implement', 'implement', 'unknown'])
def test_role_closed_list(runner, role):
    with pytest.raises(WorkflowError, match='Unknown role'):
        pi.run_agent(runner, role, 'task')


def test_bridge_before_process(runner, monkeypatch):
    monkeypatch.setattr(pi.subprocess, 'run', lambda *a, **k: pytest.fail('process started'))
    with pytest.raises(WorkflowError, match='claude-bridge'):
        pi.run_agent(runner, 'crossreview', 'task', model='claude-bridge/x')
