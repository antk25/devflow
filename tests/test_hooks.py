import json
import subprocess
from collections import defaultdict
from pathlib import Path

import pytest

from devflow import guard

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts' / 'devflow-cli.sh'
FIXTURES = json.loads((ROOT / 'tests' / 'hooks' / 'fixtures' / 'guard.json').read_text())


def call(stdin, log, cwd=ROOT):
    return subprocess.run([str(CLI), 'guard'], input=stdin, capture_output=True, text=True, cwd=cwd,
                          env={'PATH': '/usr/bin:/bin', 'HOME': str(log.parent), 'DEVFLOW_GUARD_LOG': str(log)})


def make_repo(path, branch, agents):
    git = ['git', '-C', str(path), '-c', 'user.name=t', '-c', 'user.email=t@t']
    subprocess.run(['git', 'init', '-q', '-b', 'main', str(path)], check=True)
    subprocess.run([*git, 'commit', '-q', '--allow-empty', '-m', 'init'], check=True)
    subprocess.run([*git, 'branch', 'feature/x'], check=True)
    subprocess.run([*git, 'branch', 'dev'], check=True)
    subprocess.run([*git, 'checkout', '-q', branch], check=True)
    if agents:
        (path / 'AGENTS.md').write_text('# X\n\n- Base branch: `dev`\n- Production branch: `production`\n')


def lines(log):
    return log.read_text().splitlines() if log.exists() else []


@pytest.mark.parametrize('case', FIXTURES, ids=lambda c: f"{c['rule']}-{c['decision']}-{c['event']['tool_input']}")
def test_fixture(case, tmp_path):
    log = tmp_path / 'guard.jsonl'
    if 'repo' in case:
        repo = tmp_path / 'repo'
        repo.mkdir()
        make_repo(repo, **case['repo'])
        case = json.loads(json.dumps(case).replace('{repo}', str(repo)))
    result = call(json.dumps(case['event']), log)
    assert result.returncode == 0
    if case['decision'] == 'allow':
        assert result.stdout == ''
        assert lines(log) == []
        return
    output = json.loads(result.stdout)['hookSpecificOutput']
    assert output['permissionDecision'] == 'deny'
    for part in case['reason_contains']:
        assert part in output['permissionDecisionReason']
    [entry] = [json.loads(line) for line in lines(log)]
    assert entry['rule'] == case['rule']
    assert entry['command'] == case['event']['tool_input']['command']
    assert entry['session_id'] == case['event']['session_id']
    assert entry['ts']


def test_every_rule_has_deny_and_allow():
    decisions = defaultdict(set)
    for case in FIXTURES:
        decisions[case['rule']].add(case['decision'])
    assert all(found == {'deny', 'allow'} for found in decisions.values()), dict(decisions)


def test_invalid_json_is_logged_and_allowed(tmp_path):
    log = tmp_path / 'guard.jsonl'
    result = call('not json', log)
    assert (result.returncode, result.stdout) == (0, '')
    assert json.loads(lines(log)[0])['rule'] == 'invalid-json'


def test_runs_outside_project(tmp_path):
    log = tmp_path / 'guard.jsonl'
    event = {'tool_name': 'Bash', 'tool_input': {'command': 'curl https://example.com'}, 'cwd': str(tmp_path)}
    result = call(json.dumps(event), log, cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'] == 'deny'


def test_plain_command_spawns_no_subprocess(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('subprocess started')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    event = {'tool_name': 'Bash', 'tool_input': {'command': 'ls -la && grep -r x . | wc -l'}, 'cwd': str(tmp_path)}
    assert guard.run(json.dumps(event), {'DEVFLOW_GUARD_LOG': str(tmp_path / 'g.jsonl')}) == ''


RESTORE = ROOT / '.claude' / 'hooks' / 'project-restore.sh'
RESTORE_FIXTURES = json.loads((ROOT / 'tests' / 'hooks' / 'fixtures' / 'project-restore.json').read_text())


@pytest.mark.parametrize('case', RESTORE_FIXTURES, ids=lambda c: c['name'])
def test_restore(case, tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    if case['agents']:
        (tmp_path / 'vault').mkdir()
        (project / 'AGENTS.md').write_text(f'---\nproject: x\nvault: {tmp_path / "vault"}\n---\n')
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path), 'XDG_RUNTIME_DIR': str(tmp_path)}
    event = json.dumps({'hook_event_name': 'SessionStart', 'session_id': f'restore-{case["name"]}', 'cwd': str(project)})
    results = [subprocess.run([str(RESTORE)], input=event, capture_output=True, text=True, cwd=project, env=env)
               for _ in range(case['calls'])]
    assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
    if case['calls'] > 1:
        assert 'PROJECT_RESTORE' in results[0].stdout
    assert results[-1].stdout == case['expect_last']


def test_deny_survives_unwritable_journal(tmp_path):
    blocker = tmp_path / 'file'
    blocker.write_text('')
    event = {'tool_name': 'Bash', 'tool_input': {'command': 'curl https://example.com'}, 'cwd': str(tmp_path)}
    output = guard.run(json.dumps(event), {'DEVFLOW_GUARD_LOG': str(blocker / 'guard.jsonl')})
    assert json.loads(output)['hookSpecificOutput']['permissionDecision'] == 'deny'


def bare_push(tmp_path, *config):
    repo = tmp_path / 'repo'
    repo.mkdir()
    make_repo(repo, 'feature/x', agents=False)
    for key, value in config:
        subprocess.run(['git', '-C', str(repo), 'config', key, value], check=True)
    event = {'tool_name': 'Bash', 'tool_input': {'command': 'git push'}, 'cwd': str(repo)}
    return guard.run(json.dumps(event), {'DEVFLOW_GUARD_LOG': str(tmp_path / 'g.jsonl')})


def test_bare_push_to_protected_upstream(tmp_path):
    output = bare_push(tmp_path, ('remote.origin.url', '.'), ('branch.feature/x.remote', 'origin'),
                       ('branch.feature/x.merge', 'refs/heads/main'), ('push.default', 'upstream'))
    assert json.loads(output)['hookSpecificOutput']['permissionDecision'] == 'deny'


def test_bare_push_with_remote_push_config(tmp_path):
    output = bare_push(tmp_path, ('remote.origin.url', '.'), ('remote.origin.push', 'refs/heads/*:refs/heads/main'))
    assert json.loads(output)['hookSpecificOutput']['permissionDecision'] == 'deny'


def test_bare_push_from_feature_branch_allowed(tmp_path):
    assert bare_push(tmp_path) == ''
