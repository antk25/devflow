import json
import os
import shlex
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
    tests_line = f'`docker exec -w {repo} devflow-bench-php-cs-fixer__php-cs-fixer-8367__manual__r1 sh -c \'vendor/bin/phpunit tests/T.php\'`'
    assert tests_line in agents and '`fix: <описание>`' in agents and 'Jira нет' in agents
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
    monkeypatch.setattr(bench, 'set_instances', lambda data, ids: {INSTANCE['instance_id']: INSTANCE})
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


RESEARCH = '''---
created: 2026-10-15
project: bench
type: research
---

# bench-task — Research

## Findings
- x

## Open questions
- [ ] один
- [ ] два
- [x] закрыт
'''

PLAN = '''---
schema: 1
research_revision: {rev}
steps:
  - {{id: one, n: 1, blocked_by: []}}
---

# bench-task — Plan

## Steps

### one: Правка
- **Acceptance:** тесты
'''


def reply(model='claude-sonnet-5-5', **extra):
    data = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'ok', 'duration_ms': 1000, 'num_turns': 2,
            'total_cost_usd': 0.1, 'modelUsage': {model: {'inputTokens': 3, 'outputTokens': 4, 'costUSD': 0.1}}}
    data.update(extra)
    return data


def fake_claude(sb, finish_implement=True, model='claude-sonnet-5-5'):
    """A claude stand-in: research and plan write their documents, implement commits and records finish."""
    from devflow import documents
    calls = []

    def execute(cmd, timeout):
        phase, message = cmd[cmd.index('--agent') + 1], cmd[2]
        calls.append((phase, message))
        if phase == 'research':
            (sb['vault'] / 'research/bench-task.md').write_text(RESEARCH)
        elif phase == 'plan':
            rev = documents.document(sb['vault'] / 'research/bench-task.md')['revision']
            (sb['vault'] / 'plans/bench-task.md').write_text(PLAN.format(rev=rev))
        elif finish_implement:
            run_id = message.split('run_id: ')[1].split()[0]
            (sb['repo'] / 'src/a.php').write_text('<?php // fixed\n')
            subprocess.run(['git', '-C', str(sb['repo']), '-c', 'user.name=a', '-c', 'user.email=a@a', 'commit', '-qam', 'fix: a'], check=True)
            log = sb['vault'] / 'changelog/2026-10-15-bench-task.md'
            log.write_text(f'# x\n\n<!-- devflow-run: {run_id} -->\n## Шаг 1\n\n**Status:** done\n')
            with bench.state_env(sb['state']):
                cli.execute(cli.parser().parse_args(['--cwd', str(sb['repo']), 'finish', run_id, '--status', 'done', '--changelog', str(log)]))
        return subprocess.CompletedProcess(cmd, 0, json.dumps(reply(model)), '')
    execute.calls = calls
    return execute


def probe_ok(cmd, timeout):
    model = cmd[cmd.index('--model') + 1]
    return subprocess.CompletedProcess(cmd, 0, json.dumps({'is_error': False, 'modelUsage': {model: {}}}), '')


def test_pairs_interleave_tasks_and_count_replicas():
    result = bench.pairs(['t1', 't2'], ['A', 'B', 'A'])
    assert result == [{'task': 't1', 'combo': 'A', 'replica': 1}, {'task': 't1', 'combo': 'B', 'replica': 1},
                      {'task': 't1', 'combo': 'A', 'replica': 2}, {'task': 't2', 'combo': 'A', 'replica': 1},
                      {'task': 't2', 'combo': 'B', 'replica': 1}, {'task': 't2', 'combo': 'A', 'replica': 2}]
    assert bench.pair_id(result[2]) == 't1__A__r2'


def test_open_questions_counts_unchecked_items_of_the_section(tmp_path):
    path = tmp_path / 'r.md'
    path.write_text(RESEARCH)
    assert bench.open_questions(path) == 2
    path.write_text('# r\n\n## Findings\n- [ ] not a question\n')
    assert bench.open_questions(path) == 0
    assert bench.open_questions(tmp_path / 'missing.md') == 0


def test_journal_append_and_read(tmp_path):
    journal = tmp_path / 'runs/x/journal.jsonl'
    assert bench.read(journal) == []
    bench.append(journal, {'type': 'run_start', 'run': 'x'})
    bench.append(journal, {'type': 'phase', 'tools': {'Bash': 1}, 'note': 'ё'})
    assert bench.read(journal) == [{'type': 'run_start', 'run': 'x'}, {'type': 'phase', 'tools': {'Bash': 1}, 'note': 'ё'}]


def test_extract_patch_takes_commits_edits_and_new_files_but_not_excluded(sandbox_env):
    sb = bench.make_sandbox(sandbox_env / 'run', PAIR, INSTANCE, execute=lambda cmd, timeout: None)
    repo = sb['repo']
    (repo / 'src/a.php').write_text('<?php // committed\n')
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=a', '-c', 'user.email=a@a', 'commit', '-qam', 'fix: a'], check=True)
    (repo / 'src/b.php').write_text('<?php // new\n')
    (repo / '.gitignore').write_text('vendor/\n# edited\n')
    (repo / 'AGENTS.md').write_text('changed\n')
    (repo / '.devflow/extra.json').write_text('{}')
    patch = bench.extract_patch(repo, sb['base'])
    assert '// committed' in patch and 'src/b.php' in patch and '# edited' in patch
    assert 'AGENTS.md' not in patch and '.devflow' not in patch and 'vendor' not in patch.split('.gitignore')[0]
    assert not (repo / '.git/bench-index').exists()
    assert subprocess.run(['git', '-C', str(repo), 'status', '--porcelain'], capture_output=True, text=True).stdout.startswith(' M')


def test_drive_runs_the_pipeline_without_a_human(sandbox_env, tmp_path):
    sb = bench.make_sandbox(sandbox_env / 'run', PAIR, INSTANCE, execute=lambda cmd, timeout: None)
    execute = fake_claude(sb)
    journal = tmp_path / 'journal.jsonl'
    combo = bench.combos(['smoke'])[0]
    result = bench.drive(sb, combo, execute, journal, {'timeout': 30})
    assert result == {'outcome': 'completed', 'phases': 3, 'steps': 1, 'open_questions': 2, 'error_text': None}
    assert [c[0] for c in execute.calls] == ['research', 'plan', 'implement']
    assert 'run_id: ' in execute.calls[2][1] and 'step: one' in execute.calls[2][1] and 'tz: ' in execute.calls[0][1]
    lines = bench.read(journal)
    assert [l['type'] for l in lines] == ['phase'] * 3
    assert [l['route_after'] for l in lines] == ['approval_required', 'approval_required', 'completed']
    assert lines[2]['step'] == 'one' and lines[2]['runner'] == 'claude' and lines[2]['model_actual'] == 'claude-sonnet-5-5'
    assert lines[2]['input'] == 3 and lines[2]['cost_usd'] == 0.1 and lines[2]['duration_s'] == 1.0 and lines[2]['pair'] == sb['pair']
    assert lines[0]['model_req'] == 'claude-sonnet-5-5' and lines[0]['effort_req'] == 'low' and lines[0]['error'] is None
    assert 'DEVFLOW_STATE_DIR' not in os.environ


def test_drive_interrupts_a_step_that_did_not_finish(sandbox_env, tmp_path):
    sb = bench.make_sandbox(sandbox_env / 'run', PAIR, INSTANCE, execute=lambda cmd, timeout: None)
    execute = fake_claude(sb, finish_implement=False)
    result = bench.drive(sb, bench.combos(['smoke'])[0], execute, tmp_path / 'j.jsonl')
    assert result['outcome'] == 'blocked' and result['steps'] == 1 and [c[0] for c in execute.calls] == ['research', 'plan', 'implement']
    with bench.state_env(sb['state']):
        state = cli.execute(cli.parser().parse_args(['--cwd', str(sb['repo']), 'route', 'bench-task']))
    assert state['state'] == 'blocked' and state['reason'] == bench.RUNNING_REASON


def test_drive_stalls_when_a_phase_changes_nothing(sandbox_env, tmp_path):
    sb = bench.make_sandbox(sandbox_env / 'run', PAIR, INSTANCE, execute=lambda cmd, timeout: None)
    idle = lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, json.dumps(reply()), '')
    result = bench.drive(sb, bench.combos(['smoke'])[0], idle, tmp_path / 'j.jsonl')
    assert result['outcome'] == 'stalled' and result['phases'] == 2
    assert [l['route_after'] for l in bench.read(tmp_path / 'j.jsonl')] == ['research', 'research']


def test_drive_stops_on_model_mismatch_and_errors(sandbox_env, tmp_path):
    sb = bench.make_sandbox(sandbox_env / 'run', PAIR, INSTANCE, execute=lambda cmd, timeout: None)
    combo = bench.combos(['smoke'])[0]
    wrong = fake_claude(sb, model='claude-opus-5-5')
    result = bench.drive(sb, combo, wrong, tmp_path / 'j.jsonl')
    assert result['outcome'] == 'model_mismatch' and 'claude-opus-5-5' in result['error_text'] and result['phases'] == 1
    sb = bench.make_sandbox(sandbox_env / 'run', PAIR, INSTANCE, execute=lambda cmd, timeout: None)
    budget = lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, json.dumps(reply(subtype='error_max_budget_usd', is_error=True, result='over')), '')
    assert bench.drive(sb, combo, budget, tmp_path / 'j2.jsonl')['outcome'] == 'budget'
    api = lambda cmd, timeout: subprocess.CompletedProcess(cmd, 1, json.dumps(reply(is_error=True, result='Not logged in')), '')
    result = bench.drive(sb, combo, api, tmp_path / 'j3.jsonl')
    assert result['outcome'] == 'paused' and result['error_text'] == 'Not logged in'
    assert bench.read(tmp_path / 'j3.jsonl')[0]['error'] == 'api'


def test_run_writes_journal_patch_and_stops_the_container(sandbox_env, tmp_path, monkeypatch):
    docker = []

    def execute(cmd, timeout, cwd=None, env=None):
        docker.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, '', '')
    holder = {}
    monkeypatch.setattr(bench.container, 'runner_executor', lambda name, cwd, env=None: holder.setdefault('exec', fake_claude(holder['sb'])))
    real_make = bench.make_sandbox

    def make(root, pair, instance, execute=None):
        holder['sb'] = real_make(root, pair, instance, execute)
        return holder['sb']
    monkeypatch.setattr(bench, 'make_sandbox', make)
    monkeypatch.setattr(bench, 'load_set', lambda name, directory=None: {'name': name, 'dataset': 'd', 'split': 'test', 'swebench': '5.0.2', 'instances': [INSTANCE['instance_id'], 'other']})
    monkeypatch.setattr(bench, 'set_instances', lambda data, ids: {INSTANCE['instance_id']: INSTANCE})
    dry = bench.run('smoke-1', 'php-pilot', ['smoke'], tasks=1, root=sandbox_env / 'sb', journal_dir=tmp_path / 'runs/smoke-1',
                    claude_limit=(None, 95))
    assert dry['state'] == 'dry_run' and dry['pairs'] == ['php-cs-fixer__php-cs-fixer-8367__smoke__r1'] and not (tmp_path / 'runs').exists()
    assert dry['estimate'] == {'pairs': 1, 'phase_calls': 3, 'cost_usd': {'claude': {'low': 4.9, 'high': 82.0}}, 'cost_source': ['prior'],
                               'hours': 0.7, 'claude_limit': None}
    result = bench.run('smoke-1', 'php-pilot', ['smoke'], tasks=1, yes=True, root=sandbox_env / 'sb',
                       journal_dir=tmp_path / 'runs/smoke-1', execute=execute, probe_execute=probe_ok, claude_limit=(None, 95))
    assert result['state'] == 'done' and result['outcomes'] == {'php-cs-fixer__php-cs-fixer-8367__smoke__r1': 'completed'}
    assert result['pairs_done'] == 1 and result['pairs_left'] == 0 and result['combos_skipped'] == {}
    lines = bench.read(tmp_path / 'runs/smoke-1/journal.jsonl')
    assert [l['type'] for l in lines] == ['run_start', 'pair_start', 'phase', 'phase', 'phase', 'pair_end']
    assert lines[0]['pairs'] == dry['pairs'] and set(lines[0]['agents_sha256']) == {'research', 'plan', 'implement'} and lines[0]['swebench'] == '5.0.2'
    assert lines[1]['sandbox'] == str(sandbox_env / 'sb/smoke-1/php-cs-fixer__php-cs-fixer-8367__smoke__r1') and lines[1]['base'] == holder['sb']['base']
    end = lines[-1]
    assert end['outcome'] == 'completed' and end['steps'] == 1 and end['open_questions'] == 2 and end['patch_bytes'] > 0
    patch = Path(end['patch']).read_text()
    assert '// fixed' in patch and 'AGENTS.md' not in patch and '.devflow' not in patch
    assert Path(end['patch']) == tmp_path / 'runs/smoke-1/patches/php-cs-fixer__php-cs-fixer-8367__smoke__r1.diff'
    run_cmd = next(c for c in docker if c[:2] == ['docker', 'run'])
    assert run_cmd[run_cmd.index('--name') + 1] == 'devflow-bench-php-cs-fixer__php-cs-fixer-8367__smoke__r1'
    assert docker[-1] == ['docker', 'rm', '-f', 'devflow-bench-php-cs-fixer__php-cs-fixer-8367__smoke__r1']


def test_cli_bench_run_wires_arguments(monkeypatch):
    seen = {}
    monkeypatch.setattr(bench, 'run', lambda name, set_name, combo_names, tasks=None, yes=False, root=None, freeze=None, source=None, phases=None: seen.update(locals()) or {'ok': True})
    args = ['bench', 'run', '--name', 'pilot', '--set', 'php-pilot', '--combo', 'production', '--combo', 'impl-opus', '--combo', 'production', '--tasks', '8', '--yes']
    assert cli.execute(cli.parser().parse_args(args)) == {'ok': True}
    assert seen['name'] == 'pilot' and seen['combo_names'] == ['production', 'impl-opus', 'production'] and seen['tasks'] == 8 and seen['yes'] is True
    assert seen['freeze'] is None and seen['source'] is None and seen['phases'] is None
    cli.execute(cli.parser().parse_args(args + ['--phases', 'research,plan']))
    assert seen['phases'] == ['research', 'plan']
    cli.execute(cli.parser().parse_args(args + ['--freeze', 'research,plan', '--from', 'smoke-1:smoke:r2']))
    assert seen['freeze'] == ['research', 'plan'] and seen['source'] == 'smoke-1:smoke:r2'
    with pytest.raises(WorkflowError):
        cli.execute(cli.parser().parse_args(args + ['--freeze', 'plan', '--from', 'smoke-1:smoke']))


def test_estimate_prefers_journal_medians_over_priors():
    combo = {'name': 'smoke', **{phase: dict(PHASE) for phase in ('research', 'plan', 'implement')}}
    past = [{'type': 'phase', 'runner': 'claude', 'model_req': 'claude-sonnet-5-5', 'effort_req': 'low', 'phase': 'research',
             'cost_usd': cost, 'duration_s': 60, 'error': None} for cost in (0.1, 0.5, 9.0)]
    past.append({'type': 'phase', 'runner': 'claude', 'model_req': 'claude-sonnet-5-5', 'effort_req': 'low', 'phase': 'plan',
                 'cost_usd': 99, 'duration_s': 60, 'error': 'api'})
    result = bench.estimate(bench.pairs(['t1', 't2'], ['smoke']), {'smoke': combo}, past,
                            {'window': 'seven_day', 'used_percentage': 88})
    assert result['pairs'] == 2 and result['phase_calls'] == 6 and result['cost_source'] == ['journal', 'prior']
    assert result['cost_usd'] == {'claude': {'low': 2 * (0.5 + 0.3 + 4.0), 'high': 2 * (0.5 + 9.0 + 64.0)}}
    assert result['hours'] == round(2 * (60 + 300 + 1800) / 3600, 1) and result['claude_limit'] == {'window': 'seven_day', 'used_percentage': 88}


def test_history_reads_phase_lines_of_every_journal(tmp_path):
    for name in ('a', 'b'):
        bench.append(tmp_path / name / 'journal.jsonl', {'type': 'run_start'})
        bench.append(tmp_path / name / 'journal.jsonl', {'type': 'phase', 'phase': 'plan', 'run': name})
    assert [r['run'] for r in bench.history(tmp_path)] == ['a', 'b']


@pytest.fixture
def two_task_run(sandbox_env, tmp_path, monkeypatch):
    """`run` over two tasks with fake docker, a claude stand-in per sandbox and no probes on the host."""
    other = dict(INSTANCE, instance_id='php-cs-fixer__php-cs-fixer-9999')
    holder = {}
    monkeypatch.setattr(bench.container, 'runner_executor',
                        lambda name, cwd, env=None: holder['make_claude'](holder['sb']))
    real_make = bench.make_sandbox

    def make(root, pair, instance, execute=None):
        holder['sb'] = real_make(root, pair, instance, execute)
        holder['made'].append(holder['sb']['pair'])
        return holder['sb']
    monkeypatch.setattr(bench, 'make_sandbox', make)
    monkeypatch.setattr(bench, 'load_set', lambda name, directory=None: {'name': name, 'dataset': 'd', 'split': 'test', 'swebench': '5.0.2',
                                                                         'instances': [INSTANCE['instance_id'], other['instance_id']]})
    monkeypatch.setattr(bench, 'set_instances', lambda data, ids: {INSTANCE['instance_id']: INSTANCE, other['instance_id']: other})
    holder['made'] = []
    holder['make_claude'] = fake_claude
    directory = tmp_path / 'runs/smoke-2'

    def go(combo_names=('smoke',), **kw):
        args = dict(tasks=2, yes=True, root=sandbox_env / 'sb', journal_dir=directory, probe_execute=probe_ok, claude_limit=(None, 95),
                    execute=lambda cmd, timeout, cwd=None, env=None: subprocess.CompletedProcess(cmd, 0, '', ''))
        args.update(kw)
        return bench.run('smoke-2', 'php-pilot', list(combo_names), **args)
    holder['go'] = go
    holder['dir'] = directory
    return holder


def test_run_stops_after_the_current_pair_and_resumes_without_rerunning(two_task_run):
    directory = two_task_run['dir']
    original = two_task_run['make_claude']

    def touching(sb):
        (directory / 'STOP').touch()
        return original(sb)
    two_task_run['make_claude'] = touching
    first = two_task_run['go']()
    assert first['state'] == 'stopped' and first['pairs_done'] == 1 and first['pairs_left'] == 1
    assert two_task_run['made'] == ['php-cs-fixer__php-cs-fixer-8367__smoke__r1']
    (directory / 'STOP').unlink()
    two_task_run['make_claude'] = original
    second = two_task_run['go']()
    assert second['state'] == 'done' and second['pairs_done'] == 2 and second['pairs_left'] == 0
    assert two_task_run['made'] == ['php-cs-fixer__php-cs-fixer-8367__smoke__r1', 'php-cs-fixer__php-cs-fixer-9999__smoke__r1']
    lines = bench.read(directory / 'journal.jsonl')
    assert [l['type'] for l in lines if l['type'] in ('run_start', 'pair_start', 'pair_end')] == ['run_start', 'pair_start', 'pair_end', 'pair_start', 'pair_end']
    assert [l['attempt'] for l in lines if l['type'] == 'pair_end'] == [1, 1]


def test_run_retries_an_unfinished_pair_as_a_new_attempt(two_task_run):
    directory = two_task_run['dir']
    bench.append(directory / 'journal.jsonl', {'type': 'run_start'})
    bench.append(directory / 'journal.jsonl', {'type': 'pair_start', 'pair': 'php-cs-fixer__php-cs-fixer-8367__smoke__r1', 'attempt': 1})
    bench.append(directory / 'journal.jsonl', {'type': 'pair_start', 'pair': 'php-cs-fixer__php-cs-fixer-9999__smoke__r1', 'attempt': 1})
    bench.append(directory / 'journal.jsonl', {'type': 'pair_end', 'pair': 'php-cs-fixer__php-cs-fixer-9999__smoke__r1', 'attempt': 1, 'outcome': 'completed'})
    result = two_task_run['go']()
    assert result['state'] == 'done' and result['pairs_done'] == 2 and result['pairs_left'] == 0
    assert two_task_run['made'] == ['php-cs-fixer__php-cs-fixer-8367__smoke__r1']
    starts = [(l['pair'], l['attempt']) for l in bench.read(directory / 'journal.jsonl') if l['type'] == 'pair_start']
    assert starts[-1] == ('php-cs-fixer__php-cs-fixer-8367__smoke__r1', 2)


def test_run_pauses_on_an_api_error_without_closing_the_pair(two_task_run):
    def failing(sb):
        return lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, json.dumps(reply(is_error=True, result='rate limited')), '')
    two_task_run['make_claude'] = failing
    result = two_task_run['go']()
    assert result['state'] == 'paused' and result['pairs_done'] == 0 and result['pairs_left'] == 2
    lines = bench.read(two_task_run['dir'] / 'journal.jsonl')
    assert [l['type'] for l in lines] == ['run_start', 'pair_start', 'phase', 'run_paused']
    assert lines[-1]['reason'].startswith('api: ') and 'rate limited' in lines[-1]['reason']
    assert not (two_task_run['dir'] / 'patches').exists()


def test_run_pauses_before_a_claude_pair_when_the_limit_is_blown(two_task_run):
    result = two_task_run['go'](claude_limit=({'exhausted': True, 'window': 'seven_day', 'used_percentage': 97}, 95))
    assert result['state'] == 'paused' and result['pairs_done'] == 0 and two_task_run['made'] == []
    lines = bench.read(two_task_run['dir'] / 'journal.jsonl')
    assert lines[-1]['type'] == 'run_paused' and lines[-1]['reason'] == 'claude limit seven_day 97% ≥ 95%'


def test_run_skips_a_combo_whose_probe_fails(two_task_run):
    def probe(cmd, timeout):
        if cmd[cmd.index('--model') + 1] == 'claude-opus-5-5':
            return subprocess.CompletedProcess(cmd, 1, '', 'model not available')
        return probe_ok(cmd, timeout)
    result = two_task_run['go'](['smoke', 'impl-opus'], probe_execute=probe)
    assert result['state'] == 'done' and result['pairs_done'] == 2 and result['pairs_left'] == 0
    assert list(result['combos_skipped']) == ['impl-opus'] and 'model not available' in result['combos_skipped']['impl-opus']
    assert [p.split('__')[-2] for p in two_task_run['made']] == ['smoke', 'smoke']
    skipped = [l for l in bench.read(two_task_run['dir'] / 'journal.jsonl') if l['type'] == 'combo_skipped']
    assert len(skipped) == 1 and skipped[0]['combo'] == 'impl-opus'


def test_run_frozen_copies_approved_documents_and_starts_at_implement(two_task_run, sandbox_env, tmp_path):
    source = two_task_run['go'](tasks=1)
    assert source['state'] == 'done'
    result = two_task_run['go'](tasks=2, root=sandbox_env / 'sb2', journal_dir=tmp_path / 'runs/frz',
                                freeze=['research', 'plan'], source='smoke-2:smoke')
    assert result['state'] == 'done' and result['outcomes'] == {'php-cs-fixer__php-cs-fixer-8367__smoke__r1': 'completed',
                                                                 'php-cs-fixer__php-cs-fixer-9999__smoke__r1': 'skipped'}
    lines = bench.read(tmp_path / 'runs/frz/journal.jsonl')
    assert [l['type'] for l in lines] == ['run_start', 'pair_start', 'phase', 'pair_end', 'pair_start', 'pair_end']
    assert lines[0]['frozen'] == ['research', 'plan'] and lines[0]['frozen_from'] == 'smoke-2:smoke'
    src = sandbox_env / 'sb/smoke-2/php-cs-fixer__php-cs-fixer-8367__smoke__r1'
    assert lines[1]['frozen'] == ['research', 'plan'] and lines[1]['frozen_from'] == str(src)
    assert lines[2]['phase'] == 'implement' and lines[2]['step'] == 'one'
    assert lines[3]['outcome'] == 'completed' and lines[3]['steps'] == 1 and lines[3]['phases'] == 1
    frozen = sandbox_env / 'sb2/smoke-2/php-cs-fixer__php-cs-fixer-8367__smoke__r1/vault'
    assert (frozen / 'research/bench-task.md').read_text() == (src / 'vault/research/bench-task.md').read_text()
    assert (frozen / 'plans/bench-task.md').read_text() == (src / 'vault/plans/bench-task.md').read_text()
    assert lines[5]['outcome'] == 'skipped' and lines[5]['error_text'] == 'frozen: no source pair' and lines[5]['patch_bytes'] == 0


def test_run_frozen_skips_a_pair_whose_source_has_no_plan(two_task_run, sandbox_env, tmp_path):
    two_task_run['go'](tasks=1)
    (sandbox_env / 'sb/smoke-2/php-cs-fixer__php-cs-fixer-8367__smoke__r1/vault/plans/bench-task.md').unlink()
    result = two_task_run['go'](tasks=1, root=sandbox_env / 'sb2', journal_dir=tmp_path / 'runs/frz',
                                freeze=['research', 'plan'], source='smoke-2:smoke')
    assert result['outcomes'] == {'php-cs-fixer__php-cs-fixer-8367__smoke__r1': 'skipped'}
    end = bench.read(tmp_path / 'runs/frz/journal.jsonl')[-1]
    assert end['type'] == 'pair_end' and end['error_text'].startswith('frozen plan: no ')


def test_run_frozen_dry_run_counts_only_implement_calls(two_task_run, sandbox_env, tmp_path):
    result = two_task_run['go'](tasks=1, yes=False, freeze=['research', 'plan'], source='smoke-2:smoke')
    assert result['state'] == 'dry_run' and result['estimate']['phase_calls'] == 1
    with pytest.raises(WorkflowError):
        two_task_run['go'](tasks=1, yes=False, freeze=['research', 'plan'])


def test_make_sandbox_from_a_source_commit_without_docker(sandbox_env):
    source = sandbox_env / 'source'
    fake_checkout(None, source)
    first = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD~2'], capture_output=True, text=True).stdout.strip()
    instance = {'instance_id': 'df-1-one', 'repo': 'devflow', 'source': str(source), 'base_commit': first,
                'problem_statement': 'Суть.', 'test_cmd': 'pytest -q', 'image': 'python:3.12-bookworm',
                'reference': {'research': {'content': 'secret'}, 'plan': {'content': 'secret'}}}
    calls = []
    sb = bench.make_sandbox(sandbox_env / 'run', {'task': 'df-1-one', 'combo': 'smoke', 'replica': 1}, instance,
                            execute=lambda cmd, timeout: calls.append(cmd))
    assert calls == [] and (sb['repo'] / 'src/a.php').read_text() == '<?php // 0\n'
    log = subprocess.run(['git', '-C', str(sb['repo']), 'log', '--oneline'], capture_output=True, text=True).stdout
    assert log.splitlines() == [f'{sb["base"][:7]} base']
    assert not list((sb['vault'] / 'research').iterdir()) and not list((sb['vault'] / 'plans').iterdir())
    assert 'secret' not in (sb['vault'] / 'tz/bench-task.md').read_text()


def test_drive_stops_after_the_approved_plan_without_implement(sandbox_env, tmp_path):
    sb = bench.make_sandbox(sandbox_env / 'run', PAIR, INSTANCE, execute=lambda cmd, timeout: None)
    execute = fake_claude(sb)
    journal = tmp_path / 'journal.jsonl'
    result = bench.drive(sb, bench.combos(['smoke'])[0], execute, journal, {'timeout': 30}, phases=['research', 'plan'])
    assert result == {'outcome': 'planned', 'phases': 2, 'steps': 0, 'open_questions': 2, 'error_text': None}
    assert [c[0] for c in execute.calls] == ['research', 'plan']
    assert [l['route_after'] for l in bench.read(journal)] == ['approval_required', 'approval_required']
    with bench.state_env(sb['state']):
        state = cli.execute(cli.parser().parse_args(['--cwd', str(sb['repo']), 'route', 'bench-task']))
    assert state['state'] == 'ready' and state['step'] == 'one'


def test_run_with_phases_records_them_and_counts_two_calls(two_task_run):
    dry = two_task_run['go'](tasks=1, yes=False, phases=['research', 'plan'])
    assert dry['estimate']['phase_calls'] == 2
    result = two_task_run['go'](tasks=1, phases=['research', 'plan'])
    assert result['outcomes'] == {'php-cs-fixer__php-cs-fixer-8367__smoke__r1': 'planned'}
    lines = bench.read(two_task_run['dir'] / 'journal.jsonl')
    assert lines[0]['phases'] == ['research', 'plan'] and [l['type'] for l in lines] == ['run_start', 'pair_start', 'phase', 'phase', 'pair_end']
    assert lines[-1]['outcome'] == 'planned' and lines[-1]['patch_bytes'] == 0
    with pytest.raises(WorkflowError):
        bench.parse_phases('plan')
    assert bench.parse_phases('research,plan,implement') == ['research', 'plan', 'implement']


def test_eval_run_judges_a_references_run(tmp_path, monkeypatch):
    directory = tmp_path / 'runs/refs-1'
    directory.mkdir(parents=True)
    sandbox = tmp_path / 'sb'
    (sandbox / 'vault/plans').mkdir(parents=True)
    journal = directory / 'journal.jsonl'
    bench.append(journal, {'type': 'run_start', 'run': 'refs-1', 'set': 'devflow-refs'})
    bench.append(journal, {'type': 'pair_start', 'pair': 'df-1__smoke__r1', 'attempt': 1, 'task': 'df-1', 'combo': 'smoke', 'replica': 1, 'sandbox': str(sandbox), 'base': 'b'})
    bench.append(journal, {'type': 'pair_end', 'pair': 'df-1__smoke__r1', 'attempt': 1, 'outcome': 'planned', 'patch': str(tmp_path / 'p.diff')})
    monkeypatch.setattr(bench, 'load_set', lambda name, directory=None: {'name': name, 'adapter': 'references', 'dataset': name, 'split': 'references', 'instances': ['df-1']})
    monkeypatch.setattr(bench, 'set_instances', lambda data, ids: {'df-1': {'instance_id': 'df-1', 'reference': {'plan': {'content': 'x'}}}})
    result = bench.eval_run('refs-1', journal_dir=directory)
    assert result['judged'] == 1 and result['results']['df-1__smoke__r1']['reason'].startswith('no plan at')
    assert result['results']['df-1__smoke__r1'] == {'validate': None, 'coverage_min': None, 'judge': None, 'reason': result['results']['df-1__smoke__r1']['reason']}
    assert bench.read(journal)[-1]['type'] == 'judge'


def test_make_sandbox_quotes_the_test_command_for_the_shell(sandbox_env):
    cmd = 'CFG=a.json; [ -f $CFG ] || CFG=b.js\necho jest -c=$CFG'
    sb = bench.make_sandbox(sandbox_env / 'run', PAIR, dict(INSTANCE, test_cmd=cmd), execute=lambda c, timeout: None)
    assert f"sh -c {shlex.quote(cmd)}`" in (sb['repo'] / 'AGENTS.md').read_text()


def test_sandbox_tests_command_is_shell_quoted(sandbox_env, monkeypatch):
    cmd = 'echo $CFG\necho two'
    monkeypatch.setattr(bench, 'load_set', lambda name, directory=None: {'dataset': 'd', 'split': 'test', 'instances': [INSTANCE['instance_id']]})
    monkeypatch.setattr(bench, 'set_instances', lambda data, ids: {INSTANCE['instance_id']: dict(INSTANCE, test_cmd=cmd)})
    result = bench.sandbox('php-pilot', INSTANCE['instance_id'], root=sandbox_env / 'sb',
                           execute=lambda c, timeout, cwd=None, env=None: subprocess.CompletedProcess(c, 0, '', ''))
    assert shlex.split(result['tests'])[-1] == cmd


def test_extract_patch_survives_a_non_utf8_file(sandbox_env):
    sb = bench.make_sandbox(sandbox_env / 'run', PAIR, INSTANCE, execute=lambda cmd, timeout: None)
    (sb['repo'] / 'src/latin.txt').write_bytes(b'caf\xe9\n')
    patch = bench.extract_patch(sb['repo'], sb['base'])
    assert 'src/latin.txt' in patch and patch.encode('utf-8', 'surrogateescape').count(b'caf\xe9') == 1


def test_run_rereads_the_claude_limit_before_each_pair(two_task_run, monkeypatch):
    snapshots = iter([(None, 95), ({'exhausted': True, 'window': 'five_hour', 'used_percentage': 50}, 95)])
    monkeypatch.setattr(bench, 'claude_limits', lambda: next(snapshots, (None, 95)))
    result = two_task_run['go'](claude_limit=None)
    assert result['state'] == 'paused' and result['pairs_done'] == 1
    lines = bench.read(two_task_run['dir'] / 'journal.jsonl')
    assert lines[-1]['type'] == 'run_paused' and 'five_hour' in lines[-1]['reason']


def test_run_refuses_implement_for_the_references_set(two_task_run, monkeypatch):
    monkeypatch.setattr(bench, 'load_set', lambda name, directory=None: {'name': name, 'adapter': 'references', 'instances': ['df-1']})
    with pytest.raises(WorkflowError, match='references'):
        two_task_run['go'](phases=list(bench.PHASES))
