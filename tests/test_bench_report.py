import json

import pytest

from devflow import bench, bench_report
from devflow.documents import WorkflowError

TASKS = ['repo__a-1', 'repo__a-2', 'repo__a-3']
# combo -> (resolved per task, cost per phase, seconds per phase)
COMBOS = {('production', 1): ([True, True, False], 0.5, 60), ('smoke', 1): ([True, False, False], 0.1, 20),
          ('smoke', 2): ([False, False, False], 0.3, 20)}


def phase(pair, name, runner, cost, seconds, model='m'):
    return {'type': 'phase', 'pair': pair, 'attempt': 1, 'phase': name, 'step': None, 'runner': runner, 'model_req': model,
            'effort_req': 'low', 'model_actual': model, 'input': 10, 'output': 100, 'cache_read': 1000, 'cache_write': 200,
            'cost_usd': cost, 'cost_source': 'anthropic-list' if runner == 'claude' else 'pi-catalog', 'duration_s': seconds,
            'tools': {'Bash': 2, 'Read': 1}, 'error': None, 'error_text': None, 'route_after': 'x'}


def journal(mismatch=False):
    records = [{'type': 'run_start', 'run': 'r', 'set': 'php-pilot', 'combos': ['production', 'smoke', 'smoke']},
               {'type': 'combo_skipped', 'combo': 'impl-codex', 'reason': 'pi: probe failed'}]
    for task in TASKS:
        for (combo, replica), (resolved, cost, seconds) in COMBOS.items():
            pair = f'{task}__{combo}__r{replica}'
            runner = 'pi' if combo == 'production' else 'claude'
            records.append({'type': 'pair_start', 'pair': pair, 'attempt': 1, 'task': task, 'combo': combo, 'replica': replica})
            records += [phase(pair, p, runner, cost, seconds) for p in ('research', 'plan', 'implement')]
            outcome = 'model_mismatch' if mismatch and combo == 'smoke' and replica == 2 and task == TASKS[0] else 'completed'
            records.append({'type': 'pair_end', 'pair': pair, 'attempt': 1, 'outcome': outcome, 'phases': 3, 'steps': 1,
                            'open_questions': 2, 'error_text': 'requested m, got n' if outcome != 'completed' else None,
                            'patch_bytes': 100})
            if task != TASKS[2] or combo != 'smoke':
                records.append({'type': 'eval', 'pair': pair, 'attempt': 1, 'task': task, 'resolved': resolved[TASKS.index(task)],
                                'diff': {'size_ratio': 2.0}})
    return records


def test_summarize_matrix_takes_last_attempt():
    records = journal()
    pair = f'{TASKS[0]}__smoke__r1'
    records += [{'type': 'pair_start', 'pair': pair, 'attempt': 2, 'task': TASKS[0], 'combo': 'smoke', 'replica': 1},
                phase(pair, 'research', 'claude', 9.0, 5), phase(pair, 'research', 'claude', 9.0, 5) | {'attempt': 2},
                {'type': 'pair_end', 'pair': pair, 'attempt': 2, 'outcome': 'blocked', 'phases': 1, 'steps': 0},
                {'type': 'eval', 'pair': pair, 'attempt': 2, 'task': TASKS[0], 'resolved': False, 'diff': {}}]
    summary = bench_report.summarize(records)
    assert summary['tasks'] == TASKS
    assert summary['combos'] == ['production', 'smoke', 'smoke r2']
    row = summary['rows'][(TASKS[0], 'smoke')]
    assert (row['outcome'], row['resolved'], row['phases'], row['cost'], row['duration_s']) == ('blocked', False, 1, {'claude': 9.0, 'pi': 0}, 5.0)
    base = summary['rows'][(TASKS[0], 'production')]
    assert base['cost'] == {'claude': 0, 'pi': 1.5} and base['tools'] == 9 and base['input'] == 30 and base['cache_read'] == 3000
    assert summary['rows'][(TASKS[2], 'smoke')]['resolved'] is None
    assert summary['specs']['production'] == {p: 'pi:m:low' for p in ('research', 'plan', 'implement')}
    assert summary['skipped'] == {'impl-codex': 'pi: probe failed'}


def test_mcnemar_and_holm():
    assert bench_report.mcnemar(0, 5) == pytest.approx(0.0625)
    assert bench_report.mcnemar(0, 0) == 1.0
    assert bench_report.mcnemar(3, 3) == 1.0
    assert bench_report.holm({'a': 0.01, 'b': 0.04, 'c': 0.03}) == {'a': pytest.approx(0.03), 'c': pytest.approx(0.06), 'b': pytest.approx(0.06)}


def test_compare_against_base_and_noise():
    summary = bench_report.summarize(journal())
    comparison = bench_report.compare(summary, 'production')
    smoke = comparison['smoke']
    assert (smoke['tasks'], smoke['base_only'], smoke['combo_only']) == (2, 1, 0)
    assert smoke['p'] == 1.0 and smoke['p_holm'] == 1.0
    assert smoke['cost']['median_ratio'] == pytest.approx(0.2) and smoke['cost']['p'] == pytest.approx(0.25)
    assert smoke['time']['median_ratio'] == 0.33
    assert comparison['smoke r2']['base_only'] == 2
    assert bench_report.compare(summary, 'absent') is None
    aa = bench_report.noise(summary)
    assert aa['smoke']['tasks'] == 3 and aa['smoke']['disagree'] == [TASKS[0]]
    assert aa['smoke']['cost_spread_median'] == pytest.approx(1.0)


def test_report_writes_markdown(tmp_path):
    directory = tmp_path / 'runs' / 'r'
    directory.mkdir(parents=True)
    (directory / 'journal.jsonl').write_text('\n'.join(json.dumps(r) for r in journal(mismatch=True)) + '\n', encoding='utf-8')
    result = bench.report_run('r', journal_dir=directory)
    text = (directory / 'report.md').read_text(encoding='utf-8')
    assert result['resolved'] == {'production': '2/3', 'smoke': '1/2', 'smoke r2': '0/1'}
    assert '| repo__a-1 | ✓ completed' in text and '⚠ model_mismatch' in text
    assert '## Не та модель' in text and 'requested m, got n' in text
    assert '`impl-codex`: пропущена — pi: probe failed' in text
    assert '| production | 2/3 |' in text and 'pi $' in text and 'research pi:m:low' in text
    assert '## Сравнение с базой `production`' in text and '## Шум A/A′' in text and 'разошлись по решённости: 1' in text
    with pytest.raises(WorkflowError):
        bench.report_run('none', journal_dir=tmp_path / 'runs' / 'none')
