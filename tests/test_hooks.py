import json
import os
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


@pytest.mark.parametrize('source', ['clear', 'startup', 'resume', 'compact'])
@pytest.mark.parametrize('slug', ['df-pi-workflow-parity', 'DF-11'])
def test_restore_handoff_from_either_host(source, slug, tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    vault = tmp_path / 'vault'
    notes = vault / 'notes'
    notes.mkdir(parents=True)
    (project / 'AGENTS.md').write_text(f'---\nproject: x\nvault: {vault}\n---\n')
    handoff = notes / f'handoff-{slug}.md'
    handoff.write_text(f'---\ntype: handoff\ntask: {slug}\n---\n# Передача\n')
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path), 'XDG_RUNTIME_DIR': str(tmp_path)}
    event = json.dumps({'source': source})
    result = subprocess.run([str(RESTORE)], input=event, capture_output=True, text=True, cwd=project, env=env)
    assert result.returncode == 0, result.stderr
    assert f'HANDOFF {handoff}' in result.stdout
    assert 'devflow route <полный slug>' in result.stdout
    assert not (project / '.devflow').exists()
    (notes / 'handoff-other.md').write_text('---\ntype: handoff\ntask: other\n---\n# Другая\n')
    result = subprocess.run([str(RESTORE)], input=event, capture_output=True, text=True, cwd=project, env=env)
    assert 'выберите полный slug явно' in result.stdout
    assert f'HANDOFF {handoff}' not in result.stdout
    os.utime(notes / 'handoff-other.md', (0, 0))
    result = subprocess.run([str(RESTORE)], input=event, capture_output=True, text=True, cwd=project, env=env)
    assert f'HANDOFF {handoff}' in result.stdout


PRE_COMPACT = ROOT / '.claude' / 'hooks' / 'pre-compact.sh'
GUARD_HOOK = ROOT / '.claude' / 'hooks' / 'context-guard.sh'
SESSION = 'abcdef12-session'


def compact_env(tmp_path, tasks=('df-1-x',)):
    home, vault, project = tmp_path / 'home', tmp_path / 'vault', tmp_path / 'project'
    for d in (home / '.claude' / 'devflow', vault / 'notes', vault / 'tz', project):
        d.mkdir(parents=True)
    for task in tasks:
        (vault / 'tz' / f'{task}.md').write_text('# X\n')
    (project / 'AGENTS.md').write_text(f'---\nproject: x\nvault: {vault}\n---\n')
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'XDG_RUNTIME_DIR': str(tmp_path)}
    return home, vault, project, env


def write_ledger(home, task):
    (home / '.claude/devflow/task-ledger.jsonl').write_text(
        json.dumps({'ts': '2026-11-09T10:00:00', 'session': SESSION, 'task': task}) + '\n')


def transcript(tmp_path, tokens):
    path = tmp_path / 't.jsonl'
    path.write_text(json.dumps({'message': {'usage': {'input_tokens': 1000, 'cache_read_input_tokens': tokens - 1000}}}) + '\n')
    return path


def test_pre_compact_writes_handoff_and_prints_instructions(tmp_path):
    home, vault, project, env = compact_env(tmp_path)
    write_ledger(home, 'DF-1')
    event = json.dumps({'hook_event_name': 'PreCompact', 'session_id': SESSION, 'trigger': 'auto',
                        'cwd': str(project), 'transcript_path': str(transcript(tmp_path, 190000))})
    result = subprocess.run([str(PRE_COMPACT)], input=event, capture_output=True, text=True, cwd=project, env=env)
    assert result.returncode == 0, result.stderr
    handoff = vault / 'notes' / 'handoff-df-1-x.md'
    assert handoff.exists()
    assert f'Передача задачи: {handoff}' in result.stdout
    assert not result.stdout.lstrip().startswith('{')
    assert not (project / '.devflow').exists()


@pytest.mark.parametrize('event', ['not json', 'agents'])
def test_pre_compact_silent_without_project(event, tmp_path):
    home, vault, project, env = compact_env(tmp_path)
    if event == 'agents':
        (project / 'AGENTS.md').unlink()
        event = json.dumps({'session_id': SESSION, 'trigger': 'manual', 'cwd': str(project)})
    result = subprocess.run([str(PRE_COMPACT)], input=event, capture_output=True, text=True, cwd=project, env=env)
    assert (result.returncode, result.stdout) == (0, '')
    assert not list((vault / 'notes').iterdir())


@pytest.mark.parametrize('linked', [True, False])
def test_restore_after_compact_picks_session_handoff(linked, tmp_path):
    home, vault, project, env = compact_env(tmp_path, ('df-1-x', 'df-2-y'))
    for slug in ('df-1-x', 'df-2-y'):
        (vault / 'notes' / f'handoff-{slug}.md').write_text(f'---\ntype: handoff\ntask: {slug}\n---\n# П\n')
    if linked:
        write_ledger(home, 'DF-2')
    event = json.dumps({'source': 'compact', 'session_id': SESSION})
    result = subprocess.run([str(RESTORE)], input=event, capture_output=True, text=True, cwd=project, env=env)
    assert result.returncode == 0, result.stderr
    if linked:
        assert f"HANDOFF {vault / 'notes' / 'handoff-df-2-y.md'}" in result.stdout
        assert 'выберите полный slug явно' not in result.stdout
    else:
        assert 'выберите полный slug явно' in result.stdout
    assert not (project / '.devflow').exists()


@pytest.mark.parametrize('tokens, prefix', [(185000, 'CONTEXT_CUT 185K'), (125000, 'CONTEXT_WARN 125K'), (50000, '')])
def test_context_guard_text_from_cli(tokens, prefix, tmp_path):
    home, vault, project, env = compact_env(tmp_path)
    event = json.dumps({'session_id': SESSION, 'transcript_path': str(transcript(tmp_path, tokens))})
    result = subprocess.run([str(GUARD_HOOK)], input=event, capture_output=True, text=True, cwd=project, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(prefix)
    if not prefix:
        assert result.stdout == ''
    if tokens == 185000:
        assert 'без спроса' in result.stdout
    assert not (project / '.devflow').exists()


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
