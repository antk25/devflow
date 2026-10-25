import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

from devflow import cli, pi, policy
from devflow.guard import permission_decision
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
    monkeypatch.setattr(pi.subprocess, 'run', lambda *a, **k: pytest.fail('subprocess.run forbidden'))
    monkeypatch.setattr(pi.subprocess, 'Popen', lambda *a, **k: pytest.fail('unmocked Popen'))
    return {'cwd': tmp_path, 'vault': tmp_path / 'vault', 'project': 'demo'}


@pytest.fixture
def popen(monkeypatch):
    def install(execute):
        class Child:
            pid = 987654

            def __init__(self, command, **kwargs):
                self.command, self.kwargs = command, kwargs
                self.returncode = None

            def wait(self, timeout=None):
                if self.returncode is None:
                    result = execute(self.command, **self.kwargs, timeout=timeout)
                    self.kwargs['stdout'].write(result.stdout)
                    self.kwargs['stderr'].write(result.stderr)
                    self.returncode = result.returncode
                return self.returncode

            def poll(self):
                return self.returncode

        monkeypatch.setattr(pi.subprocess, 'Popen', Child)
    def gone(*args):
        raise ProcessLookupError
    monkeypatch.setattr(pi.os, 'killpg', gone)
    monkeypatch.setattr(pi.subprocess, 'Popen', lambda *a, **k: pytest.fail('unknown process'))
    return install


@pytest.mark.parametrize('role', pi.ROLES)
def test_roles_state_independent(runner, monkeypatch, popen, role):
    def forbidden(*args, **kwargs):
        pytest.fail('Роль не должна обращаться к состоянию фаз')
    for name in ('route', 'start', 'interrupt'):
        monkeypatch.setattr(pi, name, forbidden)
    calls = []
    def execute(command, **kwargs):
        calls.append((command, kwargs))
        assert Path(command[command.index('--append-system-prompt') + 1]).exists()
        return subprocess.CompletedProcess(command, 0, 'находок нет', '')
    popen(execute)
    result = pi.run_agent(runner, role, 'Независимое задание', model='anthropic/model:high')
    assert result['host'] == 'pi' and result['exit_code'] == 0
    assert result['model_source'] == 'override'
    assert result['executor'] == 'anthropic/model:high'
    command, kwargs = calls[0]
    assert command[0] == 'pi' and '--no-session' in command
    assert kwargs['stdin'] == subprocess.DEVNULL and 0 < kwargs['timeout'] <= 600
    assert kwargs['start_new_session'] is True
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
def test_incomplete(runner, popen, code, report):
    popen(lambda *a, **k: subprocess.CompletedProcess([], code, report, 'error'))
    result = pi.run_agent(runner, 'crossreview', 'task')
    assert result['exit_code'] == code and 'не завершён' in result['warning']


def test_timeout_retains_partial_report(runner, popen):
    calls = []
    def timeout(*a, **k):
        if not calls:
            calls.append(True)
            k['stdout'].write('partial')
            k['stderr'].write('limit')
            raise subprocess.TimeoutExpired('pi', 1)
        return subprocess.CompletedProcess([], -9, '', '')
    popen(timeout)
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


def test_review_axes_separate_inputs_outputs_and_unchanged_tree(runner, monkeypatch, popen):
    tracked = runner['cwd'] / 'code.py'
    tracked.write_text('original\n')
    before = tracked.read_bytes()
    calls = []
    reports = {
        'review-standards': 'Худшее: правило. Цитата: «конвенция»',
        'review-conformance': 'Худшее: контракт. ТЗ: «точная цитата»',
    }

    def execute(command, **kwargs):
        prompt = Path(command[command.index('--append-system-prompt') + 1]).read_text()
        role = 'review-conformance' if '# review-conformance' in prompt else 'review-standards'
        assert 'write' not in command[command.index('--tools') + 1].split(',')
        assert 'edit' not in command[command.index('--tools') + 1].split(',')
        assert all(report not in command[-1] for report in reports.values())
        calls.append(command[command.index('--append-system-prompt') + 1])
        return subprocess.CompletedProcess(command, 0, reports[role], '')

    popen(execute)
    for role, report in reports.items():
        result = pi.run_agent(runner, role, 'cwd: demo; target: base...HEAD; slug: demo')
        assert result['report'] == report
    assert len(set(calls)) == 2
    assert tracked.read_bytes() == before
    assert not (runner['cwd'] / '.devflow').exists()


@pytest.mark.parametrize('source', ['inherited', 'default', 'override'])
@pytest.mark.parametrize('outcome', ['success', 'error', 'empty', 'timeout'])
def test_role_model_result_contract(runner, popen, source, outcome):
    env = {'DEVFLOW_INSTRUCTIONS': os.environ['DEVFLOW_INSTRUCTIONS'],
           'DEVFLOW_MODEL_POLICY': os.environ['DEVFLOW_MODEL_POLICY']}
    if source == 'inherited':
        env.update(PI_PROVIDER='provider', PI_MODEL='current', PI_REASONING_LEVEL='low')
    if source == 'default':
        (runner['cwd'] / 'settings.json').write_text(json.dumps({
            'defaultProvider': 'provider', 'defaultModel': 'configured'}))
    calls = []

    def execute(command, **kwargs):
        if outcome == 'timeout':
            if not calls:
                calls.append(command)
                kwargs['stdout'].write('partial')
                kwargs['stderr'].write('limit')
                raise subprocess.TimeoutExpired(command, 1)
            return subprocess.CompletedProcess(command, -9, '', '')
        return subprocess.CompletedProcess(command, 1 if outcome == 'error' else 0,
                                           '' if outcome == 'empty' else 'report', 'diagnostic')

    popen(execute)
    result = pi.run_agent(runner, 'review-standards', 'task', env=env,
                          model='provider/explicit:low' if source == 'override' else None)
    assert result['model_source'] == source
    assert result['executor'] == {'inherited': 'provider/current:low',
                                  'default': 'provider/configured',
                                  'override': 'provider/explicit:low'}[source]
    if source in ('inherited', 'default'):
        assert 'наследуется' in result['model_note']
    else:
        assert 'model_note' not in result
    if outcome == 'success':
        assert result['exit_code'] == 0 and result['report'] == 'report'
        assert 'warning' not in result
    else:
        assert 'не завершён' in result['warning']
        assert result['exit_code'] == {'error': 1, 'empty': 0, 'timeout': 124}[outcome]
        if outcome == 'timeout':
            assert result['report'] == 'partial' and result['stderr'] == 'limit'


def test_review_skill_commands_guarded(runner, popen):
    skill = (Path(__file__).resolve().parents[1] / 'skills/review/SKILL.md').read_text()
    block = re.search(r'```bash\n(.*?)\n```', skill, re.S).group(1)
    commands = block.splitlines()
    assert len(commands) == 2
    config = runner['cwd'] / 'policy.json'
    config.write_text(json.dumps({'permissions': {'allow': ['Bash(devflow agent run:*)']}}))
    inputs = {}
    for role in ('review-standards', 'review-conformance'):
        path = runner['cwd'] / (role.removeprefix('review-') + '.in.md')
        path.write_text('cwd: demo; target: base...HEAD; slug: demo; сделай свою ось')
        inputs[role] = path
    reports = []

    def execute(command, **kwargs):
        assert all(report not in command[-1] for report in reports)
        reports.append('Отдельный результат ' + str(len(reports)))
        return subprocess.CompletedProcess(command, 0, reports[-1], '')

    popen(execute)
    results = []
    for command, role in zip(commands, inputs):
        command = command.replace('<tmp>', str(runner['cwd']))
        verdict = permission_decision({'toolName': 'bash', 'input': {'command': command},
                                       'cwd': str(runner['cwd'])}, [config])
        assert verdict['decision'] == 'allow', verdict
        assert not any(token in command for token in ('>', '<', '&', '|', ';'))
        args = shlex.split(command)
        assert args == ['devflow', 'agent', 'run', role, '--message-file', str(inputs[role])]
        results.append(json.loads(json.dumps(pi.run_agent(runner, role, inputs[role].read_text()))))
    assert [result['report'] for result in results] == reports
    assert results[0]['role'] != results[1]['role']
    assert len(reports) == 2


def test_bridge_before_process(runner, monkeypatch):
    monkeypatch.setattr(pi.subprocess, 'run', lambda *a, **k: pytest.fail('process started'))
    monkeypatch.setattr(pi.subprocess, 'Popen', lambda *a, **k: pytest.fail('process started'))
    with pytest.raises(WorkflowError, match='claude-bridge'):
        pi.run_agent(runner, 'crossreview', 'task', model='claude-bridge/x')
