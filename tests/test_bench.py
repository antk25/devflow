import json
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
