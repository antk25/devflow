import json
import subprocess
from pathlib import Path

import pytest

from devflow.guard import command_forms, permission_decision, settings_paths

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def policy(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text((ROOT / 'settings.global.example.json').read_text())
    subprocess.run(['git', 'init', '-b', 'feature', str(tmp_path)], check=True, capture_output=True)
    (tmp_path / 'AGENTS.md').write_text('- Base branch: `stable`\n')
    return tmp_path, [path]


def decision(policy, command):
    cwd, paths = policy
    return permission_decision({'toolName': 'bash', 'input': {'command': command}, 'cwd': str(cwd)}, paths)['decision']


@pytest.mark.parametrize('command', [
    'git push origin main', 'git push origin master', 'git push origin production',
    'git push origin stable', 'git push --force origin feature', 'git push origin +feature',
    'git push --delete origin feature', 'git push origin :feature', 'git push --mirror origin',
    'gh pr merge 1', 'gh api repos', 'gh release create v1', 'gh workflow run ci',
    'gh release upload v1 x', 'gh release delete v1', 'exec -a innocent curl host',
    'bash ~/.config/devflow/integrations/jira-create.sh --yes -c true',
    'curl https://example.test', 'wget https://example.test', 'ssh host',
    'env A=1 rtk proxy git push origin main', 'bash -c "git push origin main"',
    'true && gh api repos', '/usr/bin/curl localhost', 'claude -p hi',
    'env claude-bridge hi', '"cu""rl" host', "c'u'rl host", 'bash -lc "curl host"',
    'bash ~/.config/devflow/integrations/jira-create.sh --yes && curl host',
])
def test_denied(policy, command):
    assert decision(policy, command) == 'deny'


@pytest.mark.parametrize('command', [
    'git push origin feature', 'gh pr create --title test', 'lcurl http://localhost:1',
    'git status', 'printf hello', 'bash -c "git status"',
    'bash ~/.config/devflow/integrations/jira-create.sh --summary test',
    '~/.claude/skills/timesheet/timesheet apply --dry-run',
])
def test_allowed(policy, command):
    assert decision(policy, command) == 'allow'


@pytest.mark.parametrize('command', [
    'bash ~/.config/devflow/integrations/jira-create.sh --summary test --yes',
    'bash ~/.config/devflow/integrations/jira-worklog.sh --issue X --yes',
    '~/.claude/skills/timesheet/timesheet apply --task X --yes',
    '~/.claude/skills/timesheet/timesheet mirror --task X --yes',
])
def test_ask(policy, command):
    assert decision(policy, command) == 'ask'
    assert decision(policy, command.replace('~/', str(Path.home()) + '/')) == 'ask'


@pytest.mark.parametrize('argument', [
    ''''() => document.querySelector("button").click()' ''',
    '''"() => 1"''',
    ''''literal $() `text` > < \\ data' ''',
])
def test_browser_quoted_javascript(policy, argument):
    command = 'devflow-browser example evaluate_script ' + argument
    assert command_forms(command, policy[0])
    assert decision(policy, command) == 'allow'


@pytest.mark.parametrize('command', [
    'devflow-browser example evaluate_script x > output',
    'devflow-browser example evaluate_script "$(curl host)"',
    'devflow-browser example evaluate_script "`curl host`"',
    "devflow-browser example evaluate_script 'unfinished",
    'devflow-browser example evaluate_script "unfinished',
    'devflow-browser example evaluate_script x\\\\; curl host',
    '''sh -c 'sh -c "curl host"' ''',
    '''sh -c 'printf x > output' ''',
    '''devflow-browser example evaluate_script '() => 1'; curl host''',
])
def test_browser_shell_operations_stay_restricted(policy, command):
    assert decision(policy, command) != 'allow'


def test_ask_without_optional_arguments(policy):
    for command in ('bash ~/.config/devflow/integrations/jira-create.sh --yes',
                    '~/.claude/skills/timesheet/timesheet apply --yes'):
        assert decision(policy, command) == 'ask'


def test_project_deny_wins_and_files(policy, tmp_path):
    cwd, paths = policy
    local = tmp_path / 'local.json'
    local.write_text(json.dumps({'permissions': {'deny': ['Bash(git push:*)', 'Write(**/secret)', 'Edit(**/secret)']}}))
    paths.append(local)
    assert decision(policy, 'git push origin feature') == 'deny'
    for tool in ('write', 'edit'):
        result = permission_decision({'toolName': tool, 'input': {'path': 'secret'}, 'cwd': str(cwd)}, paths)
        assert result['decision'] == 'deny'


def test_soft_deny_errors_and_uncertain(policy):
    cwd, paths = policy
    paths[0].write_text(json.dumps({'autoMode': {'soft_deny': ['$defaults', 'Bash(mysql * UPDATE*)']}}))
    assert decision(policy, 'mysql prod UPDATE table') == 'ask'
    for command in ('echo $(curl host)', 'bash -c "$(claude)"', 'echo `gh api repos`', 'bash -c "unterminated'):
        assert decision(policy, command) != 'allow'
    paths[0].write_text('{broken')
    assert decision(policy, 'true') == 'deny'
    paths[0].write_text(json.dumps({'permissions': {'deny': ['not valid (rule']}}))
    assert decision(policy, 'true') == 'deny'


def test_git_c_and_cd(policy, tmp_path):
    other = tmp_path / 'other'
    subprocess.run(['git', 'init', '-b', 'main', str(other)], check=True, capture_output=True)
    assert decision(policy, f'git -C {other} push origin HEAD') == 'deny'
    assert decision(policy, f'cd {other} && git push origin HEAD') == 'deny'


def test_project_paths_from_subdirectory(policy):
    cwd, paths = policy
    config = cwd / '.claude' / 'settings.local.json'
    config.parent.mkdir()
    config.write_text(json.dumps({'permissions': {'deny': ['Write(/secret)', 'Edit(/secret)']}}))
    sub = cwd / 'sub'
    sub.mkdir()
    assert config in settings_paths(sub)
    for tool in ('write', 'edit'):
        event = {'toolName': tool, 'input': {'path': '../secret'}, 'cwd': str(sub)}
        assert permission_decision(event, [config])['decision'] == 'deny'


def test_settings_protocol_and_exceptions(tmp_path):
    config = tmp_path / '.claude/settings.json'
    config.parent.mkdir()
    config.write_text(json.dumps({'permissions': {'deny': ['Bash(printf:*)']}}))
    import os
    env = {**os.environ, 'HOME': str(tmp_path)}
    process = subprocess.run([str(ROOT / 'scripts/devflow-cli.sh'), 'guard', '--host', 'pi'],
                             input=json.dumps({'toolName': 'bash', 'input': {'command': 'printf test'},
                                               'cwd': str(tmp_path)}),
                             env=env, text=True, capture_output=True)
    assert process.returncode == 0
    assert json.loads(process.stdout)['decision'] == 'deny'
    assert json.loads(config.read_text())['permissions']['deny'] == ['Bash(printf:*)']
    config.write_text(json.dumps({'permissions': {'allow': ['Bash(custom:*)']}}))
    assert permission_decision({'toolName': 'bash', 'input': {'command': 'custom test'}}, [config])['rule'] == 'Bash(custom:*)'


@pytest.mark.parametrize('flags', [
    '--no-pager', '--no-optional-locks', '--no-pager --no-optional-locks',
    '--no-optional-locks --no-pager', '--no-pager --no-pager --no-optional-locks',
])
def test_safe_git_global_flags(policy, flags):
    cwd, paths = policy
    command = f'git {flags} status'
    assert command_forms(command, cwd) == [(command, cwd), ('git status', cwd)]
    assert decision(policy, command) == 'allow'
    mixed = f'git {flags} -C sub -c core.fsmonitor=false status --no-pager'
    assert command_forms(mixed, cwd) == [(mixed, cwd), ('git status --no-pager', cwd / 'sub')]
    interleaved = f'git -c core.fsmonitor=false {flags} -C sub status'
    assert command_forms(interleaved, cwd)[-1] == ('git status', cwd / 'sub')


@pytest.mark.parametrize('flags', [
    '--no-pager', '--no-optional-locks', '--no-pager --no-optional-locks',
    '--no-optional-locks --no-pager', '--no-pager --no-pager --no-optional-locks',
])
@pytest.mark.parametrize('rules,expected,rule', [
    ({}, 'allow', 'pi-default'),
    ({'allow': ['Bash(git status)']}, 'allow', 'Bash(git status)'),
    ({'allow': ['Bash(git *)'], 'ask': ['Bash(git status)']}, 'ask', 'Bash(git status)'),
    ({'allow': ['Bash(git *)'], 'ask': ['Bash(git status)'], 'deny': ['Bash(git status)']},
     'deny', 'Bash(git status)'),
])
@pytest.mark.parametrize('prefix', ['', '-C sub -c core.fsmonitor=false '])
def test_safe_git_flags_policy_equivalence(policy, flags, rules, expected, rule, prefix):
    cwd, paths = policy
    paths[0].write_text(json.dumps({'permissions': rules}))
    baseline = f'git {prefix}status'
    flagged = f'git {flags} {prefix}status'
    for command in (baseline, flagged):
        result = permission_decision({'toolName': 'bash', 'input': {'command': command}, 'cwd': str(cwd)}, paths)
        assert (result['decision'], result['rule']) == (expected, rule)


@pytest.mark.parametrize('kind', ['deny', 'ask'])
@pytest.mark.parametrize('form', ['original', 'normalized'])
def test_safe_git_flags_local_restrictions(policy, tmp_path, kind, form):
    cwd, paths = policy
    paths[0].write_text(json.dumps({'permissions': {'allow': ['Bash(git *)']}}))
    flagged = 'git --no-pager --no-optional-locks status'
    pattern = flagged if form == 'original' else 'git status'
    local = tmp_path / 'local-policy.json'
    local.write_text(json.dumps({'permissions': {kind: [f'Bash({pattern})']}}))
    paths.append(local)
    result = permission_decision({'toolName': 'bash', 'input': {'command': flagged}, 'cwd': str(cwd)}, paths)
    assert (result['decision'], result['rule']) == (kind, f'Bash({pattern})')
    assert decision(policy, 'git status') == (kind if form == 'normalized' else 'allow')


@pytest.mark.parametrize('flag', ['--no-pager=x', '--no-optional-locks=x', '--no-page', '--no-optional-lock', '--unknown'])
def test_unknown_git_global_flags(policy, flag):
    with pytest.raises(ValueError, match='глобальная опция'):
        command_forms(f'git {flag} status', policy[0])
    assert decision(policy, f'git {flag} status') != 'allow'


@pytest.mark.parametrize('tail', [
    'push origin main', 'push origin master', 'push origin production', 'push origin stable',
    'push --force origin feature', 'push --delete origin feature', 'push --mirror origin',
    'push origin +feature', 'push origin :feature', 'push origin feature:main',
])
def test_safe_flags_preserve_publication_denials(policy, tail):
    assert decision(policy, f'git {tail}') == 'deny'
    assert decision(policy, f'git --no-pager --no-optional-locks {tail}') == 'deny'


@pytest.mark.parametrize('command', [
    'git --no-pager --unknown status', 'git --no-optional-locks status $(true)',
    'git --no-pager status `true`', 'git --no-pager status > output',
])
def test_safe_flags_do_not_allow_unknown_or_shell(policy, command):
    assert decision(policy, command) != 'allow'


def test_protocol(tmp_path):
    result = subprocess.run([str(ROOT / 'scripts/devflow-cli.sh'), 'guard', '--host', 'pi'],
                            input='{broken', text=True, capture_output=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)['decision'] == 'deny'
