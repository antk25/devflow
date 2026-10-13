import json
import os
import subprocess
from pathlib import Path

import pytest

from devflow import bench, bench_runners, cli
from devflow.documents import WorkflowError

PHASE = {'runner': 'claude', 'model': 'claude-sonnet-5-5', 'effort': 'low'}


def write_combo(directory, name, **phases):
    data = {'name': name, 'research': PHASE, 'plan': PHASE, 'implement': PHASE}
    data.update(phases)
    path = Path(directory) / f'{name}.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


def test_repository_combos_have_three_phases_each():
    loaded = {c['name']: c for c in bench.combos()}
    assert set(loaded) == {'production', 'impl-opus', 'impl-codex', 'smoke', 'smoke-pi'}
    for combo in loaded.values():
        assert all(set(combo[p]) == {'runner', 'model', 'effort'} for p in ('research', 'plan', 'implement'))
    assert loaded['production']['implement'] == {'runner': 'claude', 'model': 'claude-fable-5-1', 'effort': 'low'}
    assert loaded['impl-codex']['implement'] == {'runner': 'pi', 'model': 'openai-codex/gpt-5.5', 'effort': 'low'}
    assert loaded['smoke-pi']['research']['model'] == 'claude-sonnet-5-5'


def test_combos_by_name_and_by_path(tmp_path):
    write_combo(tmp_path, 'a')
    write_combo(tmp_path, 'b')
    assert [c['name'] for c in bench.combos(['b', 'a'], directory=tmp_path)] == ['b', 'a']
    assert bench.combos([str(tmp_path / 'a.json')], directory='/nonexistent')[0]['name'] == 'a'
    with pytest.raises(WorkflowError, match='unknown combo'):
        bench.combos(['zzz'], directory=tmp_path)


@pytest.mark.parametrize('phase_spec, message', [
    ({'implement': {'runner': 'codex', 'model': 'gpt-5.5', 'effort': 'low'}}, 'unknown runner'),
    ({'implement': {'runner': 'pi', 'model': 'gpt-5.5', 'effort': 'low'}}, 'provider/id'),
    ({'implement': {'runner': 'claude', 'model': 'claude-opus-5-5'}}, 'effort is required'),
])
def test_load_combo_rejects_bad_phase(tmp_path, phase_spec, message):
    path = write_combo(tmp_path, 'bad', **phase_spec)
    with pytest.raises(WorkflowError, match=message):
        bench.load_combo(path)


def test_load_combo_requires_every_phase(tmp_path):
    path = tmp_path / 'x.json'
    path.write_text(json.dumps({'name': 'x', 'research': PHASE, 'plan': PHASE}), encoding='utf-8')
    with pytest.raises(WorkflowError, match='phase implement is missing'):
        bench.load_combo(path)


def fake_execute(claude_json=None, pi_message=None, returncode=0):
    calls = []

    def execute(cmd, timeout):
        calls.append(cmd)
        if cmd[0] == 'pi':
            session_dir = Path(cmd[cmd.index('--session-dir') + 1])
            records = [{'type': 'session', 'id': 's1'},
                       {'type': 'message', 'message': {'role': 'user', 'content': 'hi'}},
                       {'type': 'message', 'message': dict(role='assistant', **pi_message)}]
            (session_dir / '2026_s1.jsonl').write_text('\n'.join(json.dumps(r) for r in records), encoding='utf-8')
            return subprocess.CompletedProcess(cmd, returncode, '', '')
        return subprocess.CompletedProcess(cmd, returncode, json.dumps(claude_json), '')
    execute.calls = calls
    return execute


def test_probe_claude_ok_and_error():
    ok = fake_execute(claude_json={'is_error': False, 'result': 'ok', 'modelUsage': {'claude-opus-5-5': {}}})
    assert bench_runners.probe(ok, 'claude', 'claude-opus-5-5', 'low') == {'ok': True, 'model_actual': 'claude-opus-5-5', 'error_text': None}
    cmd = ok.calls[0]
    assert cmd[:2] == ['claude', '-p'] and '--output-format' in cmd and cmd[cmd.index('--model') + 1] == 'claude-opus-5-5'
    bad = fake_execute(claude_json={'is_error': True, 'result': 'Not logged in'}, returncode=1)
    assert bench_runners.probe(bad, 'claude', 'claude-opus-5-5', 'low') == {'ok': False, 'model_actual': None, 'error_text': 'Not logged in'}


def test_probe_pi_error_comes_from_stop_reason_not_exit_code():
    usage = {'input': 0, 'output': 0}
    bad = fake_execute(pi_message={'provider': 'openai-codex', 'model': 'gpt-6-astra', 'stopReason': 'error',
                                   'errorMessage': "Codex error: The 'gpt-6-astra' model is not supported", 'usage': usage})
    result = bench_runners.probe(bad, 'pi', 'openai-codex/gpt-6-astra', 'low')
    assert result == {'ok': False, 'model_actual': 'openai-codex/gpt-6-astra',
                      'error_text': "Codex error: The 'gpt-6-astra' model is not supported"}
    cmd = bad.calls[0]
    assert cmd[:2] == ['pi', '-p'] and cmd[cmd.index('--model') + 1] == 'openai-codex/gpt-6-astra:low'
    assert '--no-extensions' in cmd and not Path(cmd[cmd.index('--session-dir') + 1]).exists()
    good = fake_execute(pi_message={'provider': 'openai-codex', 'model': 'gpt-5.5', 'stopReason': 'stop', 'usage': usage})
    assert bench_runners.probe(good, 'pi', 'openai-codex/gpt-5.5', 'low') == {'ok': True, 'model_actual': 'openai-codex/gpt-5.5', 'error_text': None}


def test_probe_reports_timeout_and_unparsable_output():
    def slow(cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)
    assert bench_runners.probe(slow, 'claude', 'claude-opus-5-5', 'low')['ok'] is False
    garbage = lambda cmd, timeout: subprocess.CompletedProcess(cmd, 1, 'not json', 'boom')
    assert bench_runners.probe(garbage, 'claude', 'claude-opus-5-5', 'low') == {'ok': False, 'model_actual': None, 'error_text': 'boom'}
    assert bench_runners.probe(garbage, 'codex', 'x', 'low')['error_text'] == 'unknown runner: codex'


def test_probe_combos_probes_each_model_once(monkeypatch):
    selected = bench.combos(['production', 'impl-opus'])
    seen = []

    def execute(cmd, timeout):
        seen.append(cmd[cmd.index('--model') + 1])
        return subprocess.CompletedProcess(cmd, 0, json.dumps({'is_error': False, 'modelUsage': {cmd[cmd.index('--model') + 1]: {}}}), '')
    probes = bench.probe_combos(selected, execute=execute)
    assert sorted(seen) == ['claude-fable-5-1', 'claude-opus-5-5', 'claude-opus-5-5']
    assert {(p['model'], p['effort'], p['ok']) for p in probes} == {('claude-opus-5-5', 'medium', True), ('claude-opus-5-5', 'low', True), ('claude-fable-5-1', 'low', True)}


def test_cli_bench_combos_runs_before_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no AGENTS.md here
    result = cli.execute(cli.parser().parse_args(['bench', 'combos', 'smoke']))
    assert [c['name'] for c in result['combos']] == ['smoke'] and 'probes' not in result
    monkeypatch.setattr(bench, 'host_execute', lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, json.dumps({'is_error': False, 'modelUsage': {'claude-sonnet-5-5': {}}}), ''))
    result = cli.execute(cli.parser().parse_args(['bench', 'combos', 'smoke', '--probe']))
    assert result['probes'] == [{'runner': 'claude', 'model': 'claude-sonnet-5-5', 'effort': 'low', 'ok': True, 'model_actual': 'claude-sonnet-5-5', 'error_text': None}]


INSTANCE = {'instance_id': 'php-cs-fixer__php-cs-fixer-8367', 'repo': 'php-cs-fixer/php-cs-fixer',
            'image': 'swebench/php-cs-fixer-8367:latest', 'problem_statement': 'Arrow functions are not fixed.\n\n```php\nfn() => 1;\n```',
            'test_cmd': 'vendor/bin/phpunit tests/T.php'}
PAIR = {'task': INSTANCE['instance_id'], 'combo': 'manual', 'replica': 1}


def fake_checkout(image, dest, execute=None, source='/testbed'):
    """The image's /testbed stand-in: a deep history, an ignored vendor/ and a tag."""
    dest = Path(dest)
    dest.mkdir(parents=True)
    (dest / 'src').mkdir()
    (dest / 'src/a.php').write_text('<?php\n')
    (dest / '.gitignore').write_text('vendor/\n')
    (dest / 'vendor').mkdir()
    (dest / 'vendor/x.php').write_text('<?php\n')
    git = ['git', '-C', str(dest), '-c', 'user.name=t', '-c', 'user.email=t@t']
    subprocess.run(git + ['init', '-q'], check=True)
    for n in range(3):
        (dest / 'src/a.php').write_text(f'<?php // {n}\n')
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-q', '-m', f'c{n}'], check=True)
    subprocess.run(git + ['tag', 'v1'], check=True)
    return dest


@pytest.fixture
def sandbox_env(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('DEVFLOW_STATE_DIR', raising=False)
    monkeypatch.setattr(bench.container, 'checkout', fake_checkout)
    return tmp_path


def test_make_sandbox_single_base_commit_excludes_and_tz(sandbox_env):
    sb = bench.make_sandbox(sandbox_env / 'run', PAIR, INSTANCE, execute=lambda cmd, timeout: None)
    assert sb['dir'] == sandbox_env / 'run' / 'php-cs-fixer__php-cs-fixer-8367__manual__r1'
    repo = sb['repo']
    log = subprocess.run(['git', '-C', str(repo), 'log', '--oneline'], capture_output=True, text=True).stdout
    assert log.splitlines() == [f'{sb["base"][:7]} base']
    assert subprocess.run(['git', '-C', str(repo), 'tag'], capture_output=True, text=True).stdout == ''
    assert subprocess.run(['git', '-C', str(repo), 'status', '--porcelain'], capture_output=True, text=True).stdout == ''
    assert (repo / '.git/info/exclude').read_text() == 'AGENTS.md\n.devflow/\n'
    assert (repo / 'vendor/x.php').exists() and (repo / 'src/a.php').read_text() == '<?php // 2\n'
    agents = (repo / 'AGENTS.md').read_text()
    assert agents.startswith(f'---\nproject: bench\nvault: {sb["vault"]}\n---\n') and 'jev' not in agents
    assert '`vendor/bin/phpunit tests/T.php`' in agents and '`fix: <описание>`' in agents and 'Jira нет' in agents
    tz = (sb['vault'] / 'tz/bench-task.md').read_text()
    assert INSTANCE['problem_statement'] in tz and 'Jira' in tz
    assert all((sb['vault'] / d).is_dir() for d in ('tz', 'research', 'plans', 'changelog', 'notes'))
    assert (sb['home']).is_dir()


def test_make_sandbox_state_lives_under_sb_state_only(sandbox_env, monkeypatch):
    sb = bench.make_sandbox(sandbox_env / 'run', PAIR, INSTANCE, execute=lambda cmd, timeout: None)
    assert list(sb['state'].rglob('state.sqlite3')) and (sb['repo'] / '.devflow/project.json').exists()
    assert not (sandbox_env / 'home/.local/share/devflow').exists()
    assert 'DEVFLOW_STATE_DIR' not in os.environ
    monkeypatch.setenv('DEVFLOW_STATE_DIR', str(sb['state']))
    result = cli.execute(cli.parser().parse_args(['--cwd', str(sb['repo']), 'route', 'bench-task']))
    assert result['state'] == 'research' and result['source'] == 'tz'


def test_make_sandbox_replaces_an_existing_directory(sandbox_env):
    sb = bench.make_sandbox(sandbox_env / 'run', PAIR, INSTANCE, execute=lambda cmd, timeout: None)
    (sb['repo'] / 'leftover.php').write_text('<?php\n')
    (sb['vault'] / 'research/bench-task.md').write_text('x')
    again = bench.make_sandbox(sandbox_env / 'run', PAIR, INSTANCE, execute=lambda cmd, timeout: None)
    assert again['dir'] == sb['dir']
    assert not (sb['repo'] / 'leftover.php').exists() and not (sb['vault'] / 'research/bench-task.md').exists()


def test_sandbox_command_starts_the_task_container(sandbox_env, monkeypatch):
    calls = []

    def execute(cmd, timeout, cwd=None, env=None):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, '', '')
    monkeypatch.setattr(bench, 'load_set', lambda name, directory=None: {'dataset': 'd', 'split': 'test', 'instances': [INSTANCE['instance_id']]})
    monkeypatch.setattr(bench, 'instances', lambda dataset, split, ids: {INSTANCE['instance_id']: INSTANCE})
    result = bench.sandbox('php-pilot', INSTANCE['instance_id'], root=sandbox_env / 'sb', execute=execute)
    run = next(c for c in calls if c[:2] == ['docker', 'run'])
    assert result['container'] == 'devflow-bench-php-cs-fixer__php-cs-fixer-8367__manual__r1'
    assert run[run.index('--name') + 1] == result['container'] and run[run.index('-v') + 1] == f"{result['dir']}:{result['dir']}"
    assert run[-2] == INSTANCE['image'] and result['route'].startswith(f"DEVFLOW_STATE_DIR={result['state']} devflow --cwd {result['repo']} route bench-task")
    with pytest.raises(WorkflowError, match='not in set'):
        bench.sandbox('php-pilot', 'other', root=sandbox_env / 'sb', execute=execute)


def test_cli_bench_sandbox_wires_set_and_instance(monkeypatch):
    monkeypatch.setattr(bench, 'sandbox', lambda set_name, instance_id: {'set': set_name, 'instance': instance_id})
    assert cli.execute(cli.parser().parse_args(['bench', 'sandbox', 'php-pilot', 'x-1'])) == {'set': 'php-pilot', 'instance': 'x-1'}
