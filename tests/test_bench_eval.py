import json
import subprocess

import pytest

from devflow import bench, bench_eval
from devflow.documents import WorkflowError

EVAL_SCRIPT = """#!/bin/bash
set -uxo pipefail
cd /testbed
git checkout abc tests/RoundTest.php
git apply -v - <<'EOF_1'
diff
EOF_1
: '>>>>> Start Test Output'
(vendor/bin/phpunit --testdox --colors=never tests/RoundTest.php) | cat
: '>>>>> End Test Output'
git checkout abc tests/RoundTest.php
"""


def instance(repo, n, created, parser='parse_log_phpunit'):
    return {'instance_id': f'{repo.replace("/", "__")}-{n}', 'repo': repo, 'created_at': created, 'log_parser': parser,
            'image': f'swebench/sweb.eval.x86_64.{repo.replace("/", "_1776_")}-{n}:latest', 'eval_script': EVAL_SCRIPT,
            'base_commit': 'abc', 'FAIL_TO_PASS': ['t'], 'PASS_TO_PASS': []}


def write_dataset(directory, items, dataset='SWE-bench/SWE-bench_Multilingual', split='test'):
    path = bench_eval.dataset_file(dataset, split, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'dataset': dataset, 'split': split, 'swebench': '5.0.2', 'instances': items}), encoding='utf-8')
    return path


class FakeDocker:
    """Fake `execute`: AGENTS.md in the tree for `with_agents`, gold fails for `gold_fails`; the harness report is written."""

    def __init__(self, harness_dir, with_agents=(), gold_fails=(), sizes=1000):
        self.harness_dir, self.with_agents, self.gold_fails, self.sizes = harness_dir, set(with_agents), set(gold_fails), sizes
        self.calls = []

    def __call__(self, cmd, cwd=None, timeout=None):
        self.calls.append(cmd)
        if cmd[:2] == ['docker', 'run']:
            image = cmd[cmd.index('sh') + 1]
            return subprocess.CompletedProcess(cmd, 0, 'AGENTS.md\n' if image in self.with_agents else '', '')
        if cmd[:3] == ['docker', 'image', 'inspect']:
            return subprocess.CompletedProcess(cmd, 0, '\n'.join([str(self.sizes)] * (len(cmd) - 5)), '')
        if '-m' in cmd and 'swebench.harness.run_evaluation' in cmd:
            ids = cmd[cmd.index('--instance_ids') + 1:]
            run_id = cmd[cmd.index('--run_id') + 1]
            resolved = [i for i in ids if i not in self.gold_fails]
            (self.harness_dir / f'gold.{run_id}.json').write_text(json.dumps(
                {'resolved_ids': resolved, 'unresolved_ids': [i for i in ids if i in self.gold_fails]}), encoding='utf-8')
            return subprocess.CompletedProcess(cmd, 0, '', '')
        raise AssertionError(f'unexpected command {cmd}')


@pytest.fixture
def dirs(tmp_path):
    for sub in ('sets', 'harness', 'datasets'):
        (tmp_path / sub).mkdir()
    return {'sets_dir': tmp_path / 'sets', 'harness_dir': tmp_path / 'harness', 'datasets_dir': tmp_path / 'datasets'}


def test_test_cmd_strips_markers_and_cat():
    assert bench_eval.test_cmd(EVAL_SCRIPT) == 'vendor/bin/phpunit --testdox --colors=never tests/RoundTest.php'
    assert bench_eval.test_cmd('echo no markers') is None


def test_instances_from_cache_without_helper(dirs):
    items = [instance('a/b', 1, '2024-01-01 00:00:00')]
    write_dataset(dirs['datasets_dir'], items)

    def no_helper(cmd, cwd=None, timeout=None):
        raise AssertionError('helper must not run when the cache exists')

    got = bench_eval.instances('SWE-bench/SWE-bench_Multilingual', 'test', ['a__b-1'], execute=no_helper, directory=dirs['datasets_dir'])
    assert got['a__b-1']['test_cmd'].startswith('vendor/bin/phpunit')
    with pytest.raises(WorkflowError, match='unknown instances: zzz'):
        bench_eval.instances('SWE-bench/SWE-bench_Multilingual', 'test', ['zzz'], execute=no_helper, directory=dirs['datasets_dir'])


def test_load_dataset_runs_helper_once_and_caches(dirs):
    calls = []

    def helper(cmd, cwd=None, timeout=None):
        calls.append(cmd)
        assert cmd[:4] == ['uv', 'run', '--with', 'swebench==5.0.2,datasets'] and str(bench_eval.HELPER) in cmd
        write_dataset(dirs['datasets_dir'], [instance('a/b', 1, '2024-01-01 00:00:00')])
        return subprocess.CompletedProcess(cmd, 0, '', '')

    for _ in range(2):
        data = bench_eval.load_dataset('SWE-bench/SWE-bench_Multilingual', 'test', helper, dirs['datasets_dir'])
    assert len(calls) == 1 and data['swebench'] == '5.0.2'


def test_load_dataset_reports_helper_failure(dirs):
    def failing(cmd, cwd=None, timeout=None):
        return subprocess.CompletedProcess(cmd, 1, '', 'boom')

    with pytest.raises(WorkflowError, match='swebench_helper failed \\(1\\): boom'):
        bench_eval.load_dataset('SWE-bench/SWE-bench_Multilingual', 'test', failing, dirs['datasets_dir'])


def test_build_set_picks_freshest_per_repo_and_replaces_rejects(dirs):
    items = [instance('laravel/framework', n, f'2024-0{n}-01 00:00:00') for n in range(1, 7)]
    items += [instance('briannesbitt/carbon', n, f'2023-0{n}-01 00:00:00') for n in range(1, 5)]
    items += [instance('gin-gonic/gin', 1, '2025-01-01 00:00:00', parser='parse_log_gotest')]
    write_dataset(dirs['datasets_dir'], items)
    fake = FakeDocker(dirs['harness_dir'], with_agents={items[5]['image']}, gold_fails={'laravel__framework-4', 'briannesbitt__carbon-3'})

    result = bench_eval.build_set('php-pilot', 'SWE-bench/SWE-bench_Multilingual', 'php', 3, execute=fake, **dirs)

    assert result['instances'] == ['laravel__framework-5', 'laravel__framework-3', 'laravel__framework-2',
                                   'briannesbitt__carbon-4', 'briannesbitt__carbon-2', 'briannesbitt__carbon-1']
    assert result['rejected'] == {'laravel__framework-6': 'AGENTS.md/CLAUDE.md in tree',
                                  'laravel__framework-4': 'gold patch not resolved',
                                  'briannesbitt__carbon-3': 'gold patch not resolved'}
    assert result['harness_rounds'] == 2 and result['short_repos'] == []
    assert all(d['gold_resolved'] for d in result['details'].values())
    assert result['disk_bytes'] == 6000 and result['disk'] == '5.9 KiB'
    harness_runs = [c for c in fake.calls if 'swebench.harness.run_evaluation' in c]
    assert harness_runs[0][harness_runs[0].index('--instance_ids') + 1:] == [
        'laravel__framework-5', 'laravel__framework-4', 'laravel__framework-3',
        'briannesbitt__carbon-4', 'briannesbitt__carbon-3', 'briannesbitt__carbon-2']
    assert '--predictions_path' in harness_runs[0] and harness_runs[0][harness_runs[0].index('--predictions_path') + 1] == 'gold'
    loaded = bench.load_set('php-pilot', directory=dirs['sets_dir'])
    assert loaded['instances'] == result['instances'] and loaded['swebench'] == '5.0.2' and loaded['adapter'] == 'swebench'


def test_build_set_reports_short_repos_and_count(dirs):
    items = [instance('a/b', n, f'2024-0{n}-01 00:00:00') for n in range(1, 3)]
    items += [instance('c/d', n, f'2024-0{n}-01 00:00:00') for n in range(1, 5)]
    write_dataset(dirs['datasets_dir'], items)
    result = bench_eval.build_set('s', 'SWE-bench/SWE-bench_Multilingual', 'php', 3, count=4, execute=FakeDocker(dirs['harness_dir']), **dirs)
    assert result['short_repos'] == ['a/b'] and result['instances'] == ['c__d-4', 'c__d-3', 'c__d-2', 'a__b-2']


def test_build_set_rejects_unknown_language_and_empty(dirs):
    write_dataset(dirs['datasets_dir'], [instance('a/b', 1, '2024-01-01 00:00:00', parser='parse_log_gotest')])
    with pytest.raises(WorkflowError, match='unknown language'):
        bench_eval.build_set('s', 'SWE-bench/SWE-bench_Multilingual', 'rust', 3, execute=FakeDocker(dirs['harness_dir']), **dirs)
    with pytest.raises(WorkflowError, match='no php instances'):
        bench_eval.build_set('s', 'SWE-bench/SWE-bench_Multilingual', 'php', 3, execute=FakeDocker(dirs['harness_dir']), **dirs)


def test_run_gold_fails_without_report(dirs):
    def harness(cmd, cwd=None, timeout=None):
        assert cwd == str(dirs['harness_dir'])
        return subprocess.CompletedProcess(cmd, 1, '', 'docker down')

    with pytest.raises(WorkflowError, match='harness run r1 failed \\(1\\): docker down'):
        bench_eval.run_gold('d', 'test', ['x'], 'r1', harness, harness_dir=dirs['harness_dir'])


def test_load_set_validates(dirs):
    (dirs['sets_dir'] / 'bad.json').write_text(json.dumps({'name': 'bad', 'instances': 'x'}), encoding='utf-8')
    with pytest.raises(WorkflowError, match='missing adapter, dataset, split, swebench'):
        bench.load_set('bad', directory=dirs['sets_dir'])
    with pytest.raises(WorkflowError, match='unknown set'):
        bench.load_set('nope', directory=dirs['sets_dir'])
