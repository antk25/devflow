import json
import subprocess
from pathlib import Path

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
