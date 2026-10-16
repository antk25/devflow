import json
import os
import subprocess
from pathlib import Path

import pytest

from devflow import bench, bench_eval
from devflow.documents import WorkflowError, context
from devflow.storage import connect

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


def test_test_cmd_keeps_the_build_lines_before_the_tests():
    script = EVAL_SCRIPT.replace("EOF_1\n: '>>>>>", "EOF_1\nmake build\n: '>>>>>")
    assert bench_eval.test_cmd(script) == 'make build && vendor/bin/phpunit --testdox --colors=never tests/RoundTest.php'


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


def test_by_language_ts_takes_vitest_and_jest():
    items = [instance('vuejs/core', 1, '2024-08-01 00:00:00', parser='parse_log_vitest'),
             instance('babel/babel', 1, '2023-01-01 00:00:00', parser='parse_log_jest'),
             instance('gin-gonic/gin', 1, '2024-01-01 00:00:00', parser='parse_log_gotest')]
    assert [i['instance_id'] for i in bench_eval.by_language(items, 'ts')] == ['vuejs__core-1', 'babel__babel-1']


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


AGENT_PATCH = """diff --git a/src/A.php b/src/A.php
--- a/src/A.php
+++ b/src/A.php
@@ -1,3 +1,4 @@
 a
-b
+c
+d
diff --git a/tests/ATest.php b/tests/ATest.php
--- a/tests/ATest.php
+++ b/tests/ATest.php
@@ -1 +1,2 @@
 x
+y
"""
GOLD_PATCH = """diff --git a/src/A.php b/src/A.php
--- a/src/A.php
+++ b/src/A.php
@@ -1,2 +1,2 @@
-b
+c
"""
REPORT = {'patch_successfully_applied': True, 'resolved': False, 'infra_failure': False,
          'tests_status': {'FAIL_TO_PASS': {'success': ['t1'], 'failure': ['t2']},
                           'PASS_TO_PASS': {'success': ['p1', 'p2', 'p3'], 'failure': []}}}


def test_diff_stats_counts_files_lines_and_ratio():
    stats = bench_eval.diff_stats(AGENT_PATCH, GOLD_PATCH)
    assert stats == {'files': 2, 'added': 3, 'removed': 1, 'lines': 4, 'test_files': 1, 'gold_lines': 2, 'size_ratio': 2.0}
    assert bench_eval.diff_stats('', GOLD_PATCH)['size_ratio'] == 0.0
    assert bench_eval.diff_stats(AGENT_PATCH, '')['size_ratio'] is None
    assert 'size_ratio' not in bench_eval.diff_stats(AGENT_PATCH)


def test_parse_instance_report_counts_tests():
    got = bench_eval.parse_instance_report(json.dumps({'a__b-1': REPORT}), 'a__b-1')
    assert got == {'resolved': False, 'applied': True, 'infra_failure': False,
                   'fail_to_pass': {'passed': 1, 'total': 2}, 'pass_to_pass': {'passed': 3, 'total': 3}}


class FakeHarness:
    """Fake `execute` for `run_evaluation` with a predictions file: writes an instance report per prediction;
    `resolved` for the ids in `resolves`."""

    def __init__(self, harness_dir, resolves=(), silent=()):
        self.harness_dir, self.resolves, self.silent, self.calls = harness_dir, set(resolves), set(silent), []

    def __call__(self, cmd, cwd=None, timeout=None):
        self.calls.append(cmd)
        assert 'swebench.harness.run_evaluation' in cmd and cwd == str(self.harness_dir)
        run_id = cmd[cmd.index('--run_id') + 1]
        path = cmd[cmd.index('--predictions_path') + 1]
        for line in open(path, encoding='utf-8'):
            pred = json.loads(line)
            if pred['instance_id'] in self.silent:
                continue
            report = dict(REPORT, resolved=pred['instance_id'] in self.resolves)
            out = bench_eval.instance_report_path(self.harness_dir, run_id, pred['model_name_or_path'], pred['instance_id'])
            out.parent.mkdir(parents=True)
            out.write_text(json.dumps({pred['instance_id']: report}), encoding='utf-8')
        return subprocess.CompletedProcess(cmd, 0, '', '')


def pair_end(task, combo, replica, patch_path):
    """`pair_start` + `pair_end` as the journal writes them: the task is only on `pair_start`."""
    pair = f'{task}__{combo}__r{replica}'
    return [{'type': 'pair_start', 'pair': pair, 'attempt': 1, 'task': task, 'combo': combo, 'replica': replica},
            {'type': 'pair_end', 'pair': pair, 'attempt': 1, 'outcome': 'completed', 'patch': str(patch_path)}]


@pytest.fixture
def journal(tmp_path):
    patches = tmp_path / 'patches'
    patches.mkdir()
    (patches / 'full.diff').write_text(AGENT_PATCH, encoding='utf-8')
    (patches / 'empty.diff').write_text('', encoding='utf-8')
    records = [{'type': 'run_start', 'run': 'r', 'set': 's'},
               *pair_end('a__b-1', 'smoke', 1, patches / 'full.diff'),
               *pair_end('a__b-2', 'smoke', 1, patches / 'empty.diff'),
               *pair_end('a__b-1', 'smoke', 2, patches / 'full.diff')]
    loaded = {'a__b-1': dict(instance('a/b', 1, '2024-01-01 00:00:00'), patch=GOLD_PATCH),
              'a__b-2': dict(instance('a/b', 2, '2024-01-01 00:00:00'), patch=GOLD_PATCH)}
    return records, loaded


def test_evaluate_runs_harness_per_model_name_and_skips_empty(journal, dirs):
    records, loaded = journal
    fake = FakeHarness(dirs['harness_dir'], resolves={'a__b-1'})
    written = []
    results = bench_eval.evaluate('r', 'd', 'test', records, loaded, fake, written.append, harness_dir=dirs['harness_dir'])
    by_pair = {r['pair']: r for r in results}
    assert written == results and all(r['type'] == 'eval' for r in results)
    assert by_pair['a__b-2__smoke__r1'] == {**by_pair['a__b-2__smoke__r1'], 'resolved': False, 'reason': 'empty patch', 'harness_run_id': None}
    assert by_pair['a__b-1__smoke__r1']['resolved'] and by_pair['a__b-1__smoke__r1']['fail_to_pass'] == {'passed': 1, 'total': 2}
    assert by_pair['a__b-1__smoke__r1']['diff']['size_ratio'] == 2.0
    assert by_pair['a__b-1__smoke__r1']['harness_run_id'] == 'r-eval-1'
    assert by_pair['a__b-1__smoke__r2']['harness_run_id'] == 'r-eval-2'
    assert len(fake.calls) == 2 and '--max_workers' in fake.calls[0] and fake.calls[0][fake.calls[0].index('--max_workers') + 1] == '2'
    preds = [json.loads(line) for line in open(fake.calls[0][fake.calls[0].index('--predictions_path') + 1], encoding='utf-8')]
    assert preds == [{'instance_id': 'a__b-1', 'model_name_or_path': 'smoke__r1', 'model_patch': AGENT_PATCH}]


def test_evaluate_skips_already_evaluated_pairs(journal, dirs):
    records, loaded = journal
    fake = FakeHarness(dirs['harness_dir'])
    first = bench_eval.evaluate('r', 'd', 'test', records, loaded, fake, lambda r: None, harness_dir=dirs['harness_dir'])
    records += first
    records += pair_end('a__b-2', 'smoke', 1, dirs['harness_dir'].parent / 'patches/full.diff')  # a new attempt
    second = bench_eval.evaluate('r', 'd', 'test', records, loaded, fake, lambda r: None, harness_dir=dirs['harness_dir'])
    assert [r['pair'] for r in second] == [] and len(fake.calls) == 2
    records += pair_end('a__b-2', 'smoke', 2, dirs['harness_dir'].parent / 'patches/full.diff')
    third = bench_eval.evaluate('r', 'd', 'test', records, loaded, fake, lambda r: None, harness_dir=dirs['harness_dir'])
    assert [r['pair'] for r in third] == ['a__b-2__smoke__r2'] and third[0]['harness_run_id'] == 'r-eval-3'


def test_evaluate_self_check_uses_gold_patch_and_own_lines(journal, dirs):
    records, loaded = journal
    fake = FakeHarness(dirs['harness_dir'], resolves={'a__b-1', 'a__b-2'})
    results = bench_eval.evaluate('r', 'd', 'test', records, loaded, fake, lambda r: None, self_check=True, harness_dir=dirs['harness_dir'])
    assert all(r['type'] == 'self_check' and r['resolved'] for r in results) and len(results) == 3
    assert all(r['diff']['size_ratio'] == 1.0 for r in results)
    assert bench_eval.pending_pairs(records + results) and not bench_eval.pending_pairs(records + results, self_check=True)


def test_evaluate_reports_missing_report(journal, dirs):
    records, loaded = journal
    fake = FakeHarness(dirs['harness_dir'], silent={'a__b-1'})
    results = bench_eval.evaluate('r', 'd', 'test', records, loaded, fake, lambda r: None, harness_dir=dirs['harness_dir'])
    assert {r['pair']: r.get('reason') for r in results} == {'a__b-2__smoke__r1': 'empty patch', 'a__b-1__smoke__r1': 'no harness report',
                                                              'a__b-1__smoke__r2': 'no harness report'}


PHPSTAN_JSON = ('{"totals":{"errors":0,"file_errors":2},"files":{"/r/src/A.php":{"errors":2,"messages":[{"message":"x",'
                '"line":3,"ignorable":true}]}},"errors":[]}')


def test_patch_files_and_parse_phpstan():
    assert bench_eval.patch_files(AGENT_PATCH + AGENT_PATCH) == bench_eval.patch_files(AGENT_PATCH)
    assert bench_eval.patch_files('') == []
    assert bench_eval.parse_phpstan(PHPSTAN_JSON) == 2
    assert bench_eval.parse_phpstan('{"totals":{"errors":1,"file_errors":0},"files":{},"errors":["boom"]}') == 1
    assert bench_eval.parse_phpstan('PHP Fatal error: out of memory') is None
    assert bench_eval.parse_phpstan('') is None


def php_repo(path, phpstan=True):
    """A git repository with `src/A.php`, `src/B.php` on the base commit; the patch then changes A and adds C."""
    (path / 'src').mkdir(parents=True)
    (path / 'src/A.php').write_text('<?php\n', encoding='utf-8')
    (path / 'src/B.php').write_text('<?php\n', encoding='utf-8')
    if phpstan:
        (path / 'vendor/bin').mkdir(parents=True)
        (path / 'vendor/bin/phpstan').write_text('', encoding='utf-8')
        (path / 'phpstan.neon.dist').write_text('', encoding='utf-8')
        (path / '.gitignore').write_text('/vendor/\n', encoding='utf-8')
    run = lambda *args: subprocess.run(['git', '-C', str(path), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                                       check=True, capture_output=True)
    run('init', '-q'); run('add', '-A'); run('commit', '-q', '-m', 'base')
    base = subprocess.run(['git', '-C', str(path), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    (path / 'src/A.php').write_text('<?php\nfunction f(): int { return 1; }\n', encoding='utf-8')
    (path / 'src/C.php').write_text('<?php\n', encoding='utf-8')
    return base


class FakePhp:
    """`execute` of the task container: `php -l` fails on `bad`; phpstan reports `errors[dir]` for the directory it
    is run from (`sh -c 'cd <dir> && ...'`), or crashes when `errors[dir]` is None."""

    def __init__(self, bad=(), errors=None):
        self.bad, self.errors, self.calls = set(bad), errors or {}, []

    def __call__(self, cmd, timeout):
        if cmd[:2] == ['docker', 'exec']:  # through `container.executor`: `docker exec -w <cwd> <name> <cmd>`
            cmd = cmd[5:]
        self.calls.append(cmd)
        if cmd[:2] == ['sh', '-c']:
            directory, binary = cmd[2].split(' && exec ')[0].removeprefix('cd '), cmd[2].split(' && exec ')[1].split(' ')[0]
            assert (Path(directory) / binary).is_file(), f'{binary} is missing in {directory}'
        if cmd[:2] == ['php', '-l']:
            ok = cmd[2] not in self.bad
            return subprocess.CompletedProcess(cmd, 0 if ok else 255, f"{'No syntax errors' if ok else 'Errors parsing'} {cmd[2]}", '')
        assert cmd[:2] == ['sh', '-c'] and '--error-format=json' in cmd[2]
        directory = cmd[2].split(' && ', 1)[0].removeprefix('cd ')
        n = self.errors.get(directory)
        if n is None:
            return subprocess.CompletedProcess(cmd, 255, '', 'PHP Fatal error: out of memory')
        return subprocess.CompletedProcess(cmd, 1 if n else 0, f'{{"totals":{{"errors":0,"file_errors":{n}}},"files":{{}},"errors":[]}}', '')


def test_static_check_lints_and_diffs_phpstan_against_base(tmp_path):
    repo = tmp_path / 'repo'
    base = php_repo(repo)
    fake = FakePhp(bad={'src/C.php'}, errors={str(repo): 3, str(tmp_path / 'base'): 1})
    result = bench_eval.static_check(fake, repo, base, ['src/A.php', 'src/C.php', 'src/gone.php', 'README.md'])
    assert result == {'tool': 'php -l + vendor/bin/phpstan (phpstan.neon.dist)', 'files': 2, 'lint_errors': 1,
                      'static_before': 1, 'static_after': 3, 'new_static_errors': 2}
    assert [c[2] for c in fake.calls if c[0] == 'php'] == ['src/A.php', 'src/C.php']
    stan = [c[2] for c in fake.calls if c[0] == 'sh']
    assert stan[0].endswith(' src/A.php src/C.php') and stan[1].endswith(' src/A.php')  # C.php is not on the base
    assert not (tmp_path / 'base').exists()
    assert 'worktree' not in subprocess.run(['git', '-C', str(repo), 'worktree', 'list'], capture_output=True, text=True).stdout.splitlines()[1:]


def test_static_check_without_php_files_or_phpstan(tmp_path):
    repo = tmp_path / 'repo'
    base = php_repo(repo, phpstan=False)
    fake = FakePhp()
    assert bench_eval.static_check(fake, repo, base, ['README.md']) == {
        'tool': None, 'files': 0, 'lint_errors': 0, 'new_static_errors': None, 'reason': 'no php files in the patch'}
    result = bench_eval.static_check(fake, repo, base, ['src/A.php'])
    assert result == {'tool': 'php -l', 'files': 1, 'lint_errors': 0, 'new_static_errors': None, 'reason': 'no phpstan in the repository'}
    assert fake.calls == [['php', '-l', 'src/A.php']]


def test_static_check_reports_phpstan_crash(tmp_path):
    repo = tmp_path / 'repo'
    base = php_repo(repo)
    result = bench_eval.static_check(FakePhp(errors={str(tmp_path / 'base'): 0}), repo, base, ['src/A.php'])
    assert result['new_static_errors'] is None and result['reason'].startswith('phpstan gave no report: PHP Fatal error')
    assert not (tmp_path / 'base').exists()


def test_static_run_writes_quality_lines_per_pending_pair(tmp_path):
    sb = tmp_path / 'sb' / 'a__b-1__smoke__r1'
    base = php_repo(sb / 'repo')
    patch = tmp_path / 'p.diff'
    patch.write_text('diff --git a/src/A.php b/src/A.php\n+x\ndiff --git a/src/C.php b/src/C.php\n+y\n', encoding='utf-8')
    gone = pair_end('a__b-2', 'smoke', 1, patch)
    gone[0].update(sandbox=str(tmp_path / 'missing'), base='0' * 40)
    records = [{'type': 'run_start', 'run': 'r', 'set': 's'},
               dict(pair_end('a__b-1', 'smoke', 1, patch)[0], sandbox=str(sb), base=base), pair_end('a__b-1', 'smoke', 1, patch)[1],
               *gone]
    fake = FakePhp(errors={str(sb / 'repo'): 0, str(sb / 'base'): 0})
    started = []
    journal = tmp_path / 'journal.jsonl'
    results = bench.static_run(records, {'a__b-1': {'image': 'img'}, 'a__b-2': {'image': 'img'}}, journal, execute=fake,
                               start=lambda name, image, workdir, execute: started.append((name, image, str(workdir))),
                               stop=lambda name, execute: started.append(('stop', name)))
    assert [r['type'] for r in results] == ['quality', 'quality'] and len(bench.read(journal)) == 2
    assert results[0]['pair'] == 'a__b-1__smoke__r1' and results[0]['lint_errors'] == 0 and results[0]['new_static_errors'] == 0
    assert results[1]['reason'].startswith('no sandbox at') and results[1]['new_static_errors'] is None
    assert started == [('devflow-bench-static-a__b-1__smoke__r1', 'img', str(sb)), ('stop', 'devflow-bench-static-a__b-1__smoke__r1')]
    assert bench.static_run(records + results, {}, journal, execute=fake) == []


def git_repo(path, dates):
    """A repository with one commit per ISO date (author and committer dates), on `main`."""
    path.mkdir(parents=True)
    git = ['git', '-C', str(path), '-c', 'user.name=t', '-c', 'user.email=t@t']
    subprocess.run(git + ['init', '-q', '-b', 'main'], check=True)
    shas = []
    for n, date in enumerate(dates):
        (path / 'file.txt').write_text(f'{n}\n')
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-q', '-m', f'c{n}'], check=True,
                       env={**os.environ, 'GIT_AUTHOR_DATE': date, 'GIT_COMMITTER_DATE': date})
        shas.append(subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip())
    return shas


@pytest.fixture
def reference_project(tmp_path, monkeypatch):
    """A project with its own state root: tz documents in the vault, approved research and plan in the database."""
    monkeypatch.setenv('DEVFLOW_STATE_DIR', str(tmp_path / 'state'))
    repo = tmp_path / 'repo'
    shas = git_repo(repo, ['2026-09-20T10:00:00+00:00', '2026-09-22T10:00:00+00:00', '2026-09-24T10:00:00+00:00'])
    vault = tmp_path / 'vault'
    for folder in ('tz', 'research', 'plans', 'changelog'):
        (vault / folder).mkdir(parents=True)
    (repo / 'AGENTS.md').write_text(f'---\nproject: p\nvault: {vault}\n---\n', encoding='utf-8')
    (vault / 'tz/DF-1-one.md').write_text('---\ntask: DF-1\n---\n\n# DF-1 One\n\nСуть задачи.\n', encoding='utf-8')
    (vault / 'tz/DF-2-two.md').write_text('# DF-2 Two\n', encoding='utf-8')
    ctx = context(repo)
    db = connect(ctx, create=True)
    rows = [('df-1-one', 'research', 'r1', '2026-09-23T08:00:00+00:00', '# research 1'),
            ('df-1-one', 'plan', 'p1', '2026-09-23T09:00:00+00:00', '# plan 1'),
            ('df-1-one', 'plan', 'p2', '2026-09-23T11:00:00+00:00', '# plan 2'),
            ('df-2-two', 'research', 'r2', '2026-09-25T08:00:00+00:00', '# research 2')]
    for slug, phase, revision, at, content in rows:
        db.execute('INSERT INTO artifacts VALUES (?,?,?,?)', (slug, phase, revision, content))
        db.execute('INSERT INTO approvals VALUES (?,?,?,?)', (slug, phase, revision, at))
    db.execute('INSERT INTO artifacts VALUES (?,?,?,?)', ('df-1-one', 'plan', 'p3', '# plan 3, never approved'))
    db.close()
    return {'ctx': ctx, 'shas': shas, 'sets_dir': tmp_path / 'sets', 'references_dir': tmp_path / 'refs', 'tmp': tmp_path}


def test_snapshot_references_takes_latest_approved_and_commit_before_research(reference_project):
    p = reference_project
    before = (p['tmp'] / 'state').rglob('*')
    stat = {f: f.stat().st_mtime_ns for f in before if f.is_file()}
    result = bench_eval.snapshot_references('refs', p['ctx'], slugs=('df-1-one',), sets_dir=p['sets_dir'],
                                            references_dir=p['references_dir'])
    assert result['adapter'] == 'references' and result['instances'] == ['df-1-one'] and result['swebench'] is None
    detail = result['details']['df-1-one']
    assert detail['commit'] == p['shas'][1] and detail['commit_source'] == 'git log --until'
    assert detail['research_revision'] == 'r1' and detail['plan_revision'] == 'p2'
    saved = json.loads((p['references_dir'] / 'refs/df-1-one.json').read_text(encoding='utf-8'))
    assert saved['plan']['content'] == '# plan 2' and saved['research']['content'] == '# research 1'
    assert saved['tz'].startswith('---\ntask: DF-1') and saved['commit'] == p['shas'][1]
    data = bench.load_set('refs', directory=p['sets_dir'])
    assert data['dataset'] == 'refs' and data['details']['df-1-one']['plan_approved_at'] == '2026-09-23T11:00:00+00:00'
    assert {f: f.stat().st_mtime_ns for f in (p['tmp'] / 'state').rglob('*') if f.is_file()} == stat
    assert not (Path.home() / '.local/share/devflow/bench/references/refs').exists()


def test_snapshot_references_manual_commit_and_missing_documents(reference_project):
    p = reference_project
    result = bench_eval.snapshot_references('refs', p['ctx'], slugs=('df-1-one',), commits={'df-1-one': 'abc123'},
                                            sets_dir=p['sets_dir'], references_dir=p['references_dir'])
    assert result['details']['df-1-one'] == {**result['details']['df-1-one'], 'commit': 'abc123', 'commit_source': 'manual'}
    with pytest.raises(WorkflowError, match='df-2-two: no approved plan'):
        bench_eval.snapshot_references('refs', p['ctx'], slugs=('df-2-two',), sets_dir=p['sets_dir'], references_dir=p['references_dir'])
    with pytest.raises(WorkflowError, match='df-3-three: no tz document'):
        bench_eval.snapshot_references('refs', p['ctx'], slugs=('df-3-three',), sets_dir=p['sets_dir'], references_dir=p['references_dir'])


def test_reference_instances_schema_and_set_dispatch(reference_project):
    p = reference_project
    bench_eval.snapshot_references('refs', p['ctx'], slugs=('df-1-one',), sets_dir=p['sets_dir'], references_dir=p['references_dir'])
    data = bench.load_set('refs', directory=p['sets_dir'])
    loaded = bench_eval.set_instances(data, ['df-1-one'], references_dir=p['references_dir'])
    item = loaded['df-1-one']
    assert item['instance_id'] == 'df-1-one' and item['base_commit'] == p['shas'][1] and item['source'] == str(p['ctx']['cwd'])
    assert item['problem_statement'] == '\n# DF-1 One\n\nСуть задачи.\n' and item['test_cmd'] == bench_eval.REFERENCES_TEST_CMD
    assert item['image'] == bench_eval.REFERENCES_IMAGE and item['reference']['plan']['revision'] == 'p2'
    with pytest.raises(WorkflowError, match='no reference snapshot for df-9'):
        bench_eval.set_instances(data, ['df-9'], references_dir=p['references_dir'])
    with pytest.raises(WorkflowError, match="unknown adapter 'x'"):
        bench_eval.set_instances({'name': 's', 'adapter': 'x'}, [])


def test_parse_commits():
    assert bench.parse_commits(['a=1', 'b=2']) == {'a': '1', 'b': '2'} and bench.parse_commits(None) == {}
    with pytest.raises(WorkflowError, match='--commit expects'):
        bench.parse_commits(['a'])


class JudgeResp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def jev_answers(sent, coverage=(0.99, 0.4), verdict=(0.9, 0.7, 0.8)):
    """Fake `urlopen`: coverage answers for `addr_n`/`cov_n`, judge answers for the three judge keys."""
    def ok(req, timeout):
        body = json.loads(req.data)
        sent.append(body)
        answers = {}
        if 'addr_1' in body['questions']:
            for n, v in enumerate(coverage, 1):
                answers[f'addr_{n}'] = {'type': 'noul', 'noul': v}
                answers[f'cov_{n}'] = {'type': 'choice', 'choice': 'covered' if v > 0.5 else 'not_covered'}
        else:
            answers = {k: {'type': 'noul', 'noul': v} for k, v in zip(('same_requirements', 'no_extra_steps', 'boundaries'), verdict)}
        return JudgeResp(json.dumps({'model': 'typesafe/jev-1.13-x', 'answers': answers}).encode())
    return ok


CANDIDATE_RESEARCH = '---\nproject: bench\ntype: research\n---\n\n# bench-task — Research\n\n## Requirements\n- шаг один (ТЗ)\n- шаг два (ТЗ)\n'
CANDIDATE_PLAN = '''---
schema: 1
research_revision: {rev}
steps:
  - {{id: one, n: 1, blocked_by: []}}
  - {{id: two, n: 2, blocked_by: [one]}}
---

# bench-task — Plan

## Steps

### one: Первый
- **Acceptance:** тесты

### two: Второй
- **Acceptance:** тесты
'''


def judge_sandbox(root, plan=True):
    from devflow import documents
    sb = root
    for folder in ('tz', 'research', 'plans', 'changelog', 'notes'):
        (sb / 'vault' / folder).mkdir(parents=True)
    (sb / 'vault/research/bench-task.md').write_text(CANDIDATE_RESEARCH, encoding='utf-8')
    if plan:
        rev = documents.document(sb / 'vault/research/bench-task.md')['revision']
        (sb / 'vault/plans/bench-task.md').write_text(CANDIDATE_PLAN.format(rev=rev), encoding='utf-8')
    return sb


def judge_records(tmp_path, *pairs):
    records = [{'type': 'run_start', 'run': 'refs-1', 'set': 'devflow-refs'}]
    for task, sandbox in pairs:
        pair = f'{task}__smoke__r1'
        records += [{'type': 'pair_start', 'pair': pair, 'attempt': 1, 'task': task, 'combo': 'smoke', 'replica': 1, 'sandbox': str(sandbox), 'base': 'b'},
                    {'type': 'pair_end', 'pair': pair, 'attempt': 1, 'outcome': 'planned', 'patch': str(tmp_path / 'none.diff')}]
    return records


REFERENCE = {'research': {'revision': 'r', 'approved_at': 't', 'content': '# research\n'},
             'plan': {'revision': 'p', 'approved_at': 't', 'content': '# plan эталон key=sk-abcdefghijklmnopqrstuvwxyz0123456789\n'}}


def test_judge_run_validates_covers_and_judges_the_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'k')
    monkeypatch.delenv('DEVFLOW_JEV_PLAN_THRESHOLD', raising=False)
    sent = []
    monkeypatch.setattr(bench_eval.jev.urllib.request, 'urlopen', jev_answers(sent))
    good, empty = judge_sandbox(tmp_path / 'good'), judge_sandbox(tmp_path / 'empty', plan=False)
    records = judge_records(tmp_path, ('df-1-one', good), ('df-2-two', empty))
    instances = {'df-1-one': {'instance_id': 'df-1-one', 'reference': REFERENCE}, 'df-2-two': {'instance_id': 'df-2-two', 'reference': REFERENCE}}
    written = []
    results = bench_eval.judge_run(records, instances, written.append)
    assert written == results and [r['type'] for r in results] == ['judge', 'judge']
    first, second = results
    assert first['pair'] == 'df-1-one__smoke__r1' and first['reason'] is None
    assert first['validate'] == {'ok': True, 'steps': 2, 'error': None}
    assert first['coverage'] == {'status': 'ok', 'reason': None, 'model': 'typesafe/jev-1.13-x', 'noul': [0.99, 0.4], 'flagged': 1, 'min': 0.4}
    assert first['judge'] == {'model': 'typesafe/jev-1.13-x', 'noul': {'same_requirements': 0.9, 'no_extra_steps': 0.7, 'boundaries': 0.8}, 'reason': None}
    assert second['reason'].startswith('no plan at') and second['validate'] is None and second['judge'] is None
    assert len(sent) == 2
    assert 'шаг один' in sent[0]['state']['ticket'] and '### two: Второй' in sent[0]['state']['plan']
    judge_body = sent[1]
    assert set(judge_body['questions']) == {'same_requirements', 'no_extra_steps', 'boundaries'}
    assert all(q['type'] == 'noul' for q in judge_body['questions'].values())
    assert '# plan эталон' in judge_body['state']['reference'] and 'sk-abcdef' not in judge_body['state']['reference']
    assert '### two: Второй' in judge_body['state']['candidate'] and 'research' not in judge_body['state']
    assert 'jev: true' in (good / 'judge/AGENTS.md').read_text() and not list((good / 'vault/changelog').iterdir())
    assert sorted(p.name for p in (good / 'vault').rglob('*.md')) == ['bench-task.md', 'bench-task.md']
    assert bench_eval.judge_run(records + results, instances, lambda r: None) == []


def test_judge_run_without_key_or_reference_and_invalid_plan(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    sb = judge_sandbox(tmp_path / 'sb')
    (sb / 'vault/plans/bench-task.md').write_text('---\nschema: 1\n---\n# нет шагов\n', encoding='utf-8')
    records = judge_records(tmp_path, ('df-1-one', sb), ('df-3-three', judge_sandbox(tmp_path / 'noref')))
    instances = {'df-1-one': {'instance_id': 'df-1-one', 'reference': REFERENCE}, 'df-3-three': {'instance_id': 'df-3-three'}}
    results = bench_eval.judge_run(records, instances, lambda r: None, threshold=0.5)
    first, third = results
    assert first['validate']['ok'] is False and 'research_revision' in first['validate']['error']
    assert first['coverage']['status'] == 'skipped' and first['coverage']['reason'] == 'OPENROUTER_API_KEY не задан' and first['coverage']['min'] is None
    assert first['judge'] == {'model': None, 'noul': None, 'reason': 'OPENROUTER_API_KEY не задан'}
    assert third['reason'] == 'df-3-three: no reference documents' and third['judge'] is None


def test_judge_skips_documents_over_the_limit_and_missing_noul(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'k')
    big = {'plan': {'content': 'x' * (bench_eval.jev.INPUT_LIMIT + 1)}}
    assert bench_eval.judge(big, {'plan': ''})['reason'].startswith('документы больше лимита')
    monkeypatch.setattr(bench_eval.jev.urllib.request, 'urlopen',
                        lambda req, timeout: JudgeResp(json.dumps({'model': 'm', 'answers': {'boundaries': {'noul': 0.5}}}).encode()))
    out = bench_eval.judge({'plan': {'content': 'a'}}, {'plan': 'b'})
    assert out == {'model': 'm', 'noul': None, 'reason': 'в ответе нет noul для same_requirements, no_extra_steps'}
