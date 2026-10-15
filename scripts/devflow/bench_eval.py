"""SWE-bench set adapter: dataset instances, gold run in the harness, set building."""
import json
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .documents import WorkflowError

ROOT = Path(__file__).resolve().parents[2]
SETS_DIR = ROOT / 'bench/sets'
HELPER = ROOT / 'bench/swebench_helper.py'
CACHE_DIR = Path('~/.local/share/devflow/bench').expanduser()
DATASETS_DIR = CACHE_DIR / 'datasets'
HARNESS_DIR = CACHE_DIR / 'harness'
SWEBENCH_VERSION = '5.0.2'
LANGUAGE_PARSERS = {'php': ('parse_log_phpunit',), 'go': ('parse_log_gotest',)}
TEST_OUTPUT = re.compile(r"^: '>>>>> Start Test Output'\n(.*?)\n: '>>>>> End Test Output'", re.S | re.M)


def host_execute(cmd, cwd=None, timeout=None):
    return subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)


def uv_command(script_args):
    return ['uv', 'run', '--with', f'swebench=={SWEBENCH_VERSION},datasets', 'python', '-I', *script_args]


def test_cmd(eval_script):
    """The test command of a harness eval script: the lines between the test-output markers, without the `| cat`."""
    match = TEST_OUTPUT.search(eval_script or '')
    if not match:
        return None
    lines = []
    for line in match.group(1).splitlines():
        line = re.sub(r'\s*\|\s*cat$', '', line.strip())
        if line.startswith('(') and line.endswith(')'):
            line = line[1:-1]
        lines.append(line)
    return '\n'.join(lines)


def dataset_file(dataset, split, directory=DATASETS_DIR):
    return Path(directory) / f'{dataset.replace("/", "__")}__{split}.json'


def load_dataset(dataset, split, execute=None, directory=DATASETS_DIR):
    """All instances of the dataset split from the cache, filled through swebench_helper on first use."""
    path = dataset_file(dataset, split, directory)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        cmd = uv_command([str(HELPER), 'instances', '--dataset', dataset, '--split', split, '--out', str(path)])
        proc = (execute or host_execute)(cmd, timeout=1800)
        if proc.returncode != 0 or not path.is_file():
            raise WorkflowError(f'swebench_helper failed ({proc.returncode}): {(proc.stderr or "").strip()[-2000:]}')
    data = json.loads(path.read_text(encoding='utf-8'))
    for item in data['instances']:
        item['test_cmd'] = test_cmd(item.get('eval_script'))
    return data


def instances(dataset, split, ids, execute=None, directory=DATASETS_DIR):
    data = load_dataset(dataset, split, execute, directory)
    by_id = {item['instance_id']: item for item in data['instances']}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise WorkflowError(f'{dataset}:{split}: unknown instances: {", ".join(missing)}')
    return {i: by_id[i] for i in ids}


def by_language(items, language):
    parsers = LANGUAGE_PARSERS.get(language)
    if not parsers:
        raise WorkflowError(f'unknown language {language!r}; expected one of {", ".join(LANGUAGE_PARSERS)}')
    return [item for item in items if item.get('log_parser') in parsers]


def has_agent_files(image, execute):
    """True when the task repository at the base commit carries its own AGENTS.md or CLAUDE.md (pulls the image)."""
    cmd = ['docker', 'run', '--rm', '--entrypoint', 'sh', image, '-c',
           'cd /testbed && ls AGENTS.md CLAUDE.md 2>/dev/null; true']
    proc = execute(cmd, timeout=3600)
    if proc.returncode != 0:
        raise WorkflowError(f'docker run {image} failed ({proc.returncode}): {(proc.stderr or "").strip()[-500:]}')
    return bool((proc.stdout or '').strip())


def parse_gold_report(text):
    report = json.loads(text)
    return set(report.get('resolved_ids') or [])


def run_gold(dataset, split, ids, run_id, execute, workers=1, harness_dir=HARNESS_DIR, timeout=1800):
    """Gold patches of `ids` through the harness; returns the set of resolved ids."""
    harness_dir = Path(harness_dir)
    harness_dir.mkdir(parents=True, exist_ok=True)
    cmd = uv_command(['-m', 'swebench.harness.run_evaluation', '--dataset_name', dataset, '--split', split,
                      '--predictions_path', 'gold', '--run_id', run_id, '--max_workers', str(workers),
                      '--timeout', str(timeout), '--report_dir', str(harness_dir), '--instance_ids', *ids])
    proc = execute(cmd, cwd=str(harness_dir), timeout=(timeout + 600) * len(ids))
    report = harness_dir / f'gold.{run_id}.json'
    if proc.returncode != 0 or not report.is_file():
        raise WorkflowError(f'harness run {run_id} failed ({proc.returncode}): {(proc.stderr or "").strip()[-2000:]}')
    return parse_gold_report(report.read_text(encoding='utf-8'))


def image_bytes(images, execute):
    if not images:
        return 0
    proc = execute(['docker', 'image', 'inspect', '--format', '{{.Size}}', *images], timeout=120)
    if proc.returncode != 0:
        return None
    return sum(int(line) for line in proc.stdout.split() if line.isdigit())


def human_size(size):
    if size is None:
        return None
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if size < 1024 or unit == 'TiB':
            return f'{size:.1f} {unit}' if unit != 'B' else f'{size} B'
        size /= 1024


def build_set(name, dataset, language, per_repo, count=None, split='test', execute=None, sets_dir=SETS_DIR,
              harness_dir=HARNESS_DIR, datasets_dir=DATASETS_DIR, workers=1):
    """Freshest `per_repo` instances per repository whose gold patch passes the harness; writes bench/sets/<name>.json."""
    execute = execute or host_execute
    data = load_dataset(dataset, split, execute, datasets_dir)
    candidates = {}
    for item in sorted(by_language(data['instances'], language), key=lambda x: x['created_at'], reverse=True):
        candidates.setdefault(item['repo'], []).append(item)
    if not candidates:
        raise WorkflowError(f'{dataset}:{split}: no {language} instances')
    chosen, rejected, exhausted = {repo: [] for repo in candidates}, {}, set()
    rounds = 0
    while True:
        batch = []
        for repo, queue in candidates.items():
            while len(chosen[repo]) + sum(1 for b in batch if b['repo'] == repo) < per_repo:
                if not queue:
                    exhausted.add(repo)
                    break
                item = queue.pop(0)
                if has_agent_files(item['image'], execute):
                    rejected[item['instance_id']] = 'AGENTS.md/CLAUDE.md in tree'
                    continue
                batch.append(item)
        if not batch:
            break
        rounds += 1
        resolved = run_gold(dataset, split, [b['instance_id'] for b in batch], f'set-{name}-{rounds}', execute,
                            workers, harness_dir)
        for item in batch:
            if item['instance_id'] in resolved:
                chosen[item['repo']].append(item)
            else:
                rejected[item['instance_id']] = 'gold patch not resolved'
    picked = [item for repo in candidates for item in chosen[repo]]
    if count:
        picked = picked[:count]
    images = [item['image'] for item in picked]
    size = image_bytes(images, execute)
    result = {'name': name, 'adapter': 'swebench', 'dataset': dataset, 'split': split, 'language': language,
              'swebench': data.get('swebench', SWEBENCH_VERSION),
              'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'instances': [item['instance_id'] for item in picked],
              'details': {item['instance_id']: {'repo': item['repo'], 'created_at': item['created_at'],
                                                'image': item['image'], 'gold_resolved': True} for item in picked},
              'rejected': rejected}
    sets_dir = Path(sets_dir)
    sets_dir.mkdir(parents=True, exist_ok=True)
    path = sets_dir / f'{name}.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return dict(result, path=str(path), harness_rounds=rounds, short_repos=sorted(exhausted),
                disk_bytes=size, disk=human_size(size))


def patch_files(patch):
    """Paths touched by a patch, in order of their `diff --git` lines."""
    files = []
    for line in (patch or '').splitlines():
        if line.startswith('diff --git '):
            path = line.split(' b/', 1)[-1]
            files.append(path) if path not in files else None
    return files


def diff_stats(patch, gold=None):
    """Size of a patch from its text: files, added/removed lines, test files touched; `size_ratio` — lines changed
    against the gold patch (None without a gold patch or when it changes nothing)."""
    files = patch_files(patch)
    tests = {path for path in files if re.search(r'(^|/)tests?/|Test\.php$|_test\.go$|\.test\.[jt]sx?$', path)}
    added, removed = 0, 0
    for line in (patch or '').splitlines():
        if line.startswith('+') and not line.startswith('+++'):
            added += 1
        elif line.startswith('-') and not line.startswith('---'):
            removed += 1
    stats = {'files': len(files), 'added': added, 'removed': removed, 'lines': added + removed, 'test_files': len(tests)}
    if gold is not None:
        gold_lines = diff_stats(gold)['lines']
        stats['gold_lines'] = gold_lines
        stats['size_ratio'] = round(stats['lines'] / gold_lines, 2) if gold_lines else None
    return stats


def parse_instance_report(text, instance_id):
    """`report.json` of one instance: resolved, applied, FAIL_TO_PASS and PASS_TO_PASS counts."""
    report = json.loads(text)[instance_id]
    status = report.get('tests_status') or {}
    counts = {}
    for key, name in (('FAIL_TO_PASS', 'fail_to_pass'), ('PASS_TO_PASS', 'pass_to_pass')):
        group = status.get(key) or {}
        passed, failed = len(group.get('success') or []), len(group.get('failure') or [])
        counts[name] = {'passed': passed, 'total': passed + failed}
    return {'resolved': bool(report.get('resolved')), 'applied': bool(report.get('patch_successfully_applied')),
            'infra_failure': bool(report.get('infra_failure')), **counts}


def instance_report_path(harness_dir, run_id, model_name, instance_id):
    return Path(harness_dir) / 'logs/run_evaluation' / run_id / model_name.replace('/', '__') / instance_id / 'report.json'


def run_predictions(dataset, split, predictions, run_id, execute, workers=2, harness_dir=HARNESS_DIR, timeout=1800):
    """`predictions` (`instance_id`, `model_name_or_path`, `model_patch`; one model name) through the harness;
    returns the parsed instance reports by instance id."""
    harness_dir = Path(harness_dir)
    harness_dir.mkdir(parents=True, exist_ok=True)
    path = harness_dir / f'predictions.{run_id}.jsonl'
    path.write_text(''.join(json.dumps(p, ensure_ascii=False) + '\n' for p in predictions), encoding='utf-8')
    cmd = uv_command(['-m', 'swebench.harness.run_evaluation', '--dataset_name', dataset, '--split', split,
                      '--predictions_path', str(path), '--run_id', run_id, '--max_workers', str(workers),
                      '--timeout', str(timeout), '--report_dir', str(harness_dir)])
    proc = execute(cmd, cwd=str(harness_dir), timeout=(timeout + 600) * len(predictions))
    reports = {}
    for p in predictions:
        report = instance_report_path(harness_dir, run_id, p['model_name_or_path'], p['instance_id'])
        if report.is_file():
            reports[p['instance_id']] = parse_instance_report(report.read_text(encoding='utf-8'), p['instance_id'])
    if proc.returncode != 0 and len(reports) < len(predictions):
        raise WorkflowError(f'harness run {run_id} failed ({proc.returncode}): {(proc.stderr or "").strip()[-2000:]}')
    return reports


def pending_pairs(records, self_check=False, kind=None):
    """Last `pair_end` of every pair without an `eval` line (`self_check` line for the self-check, `kind` for any
    other result type), with the pair's `task`, `sandbox` and `base` from its `pair_start`."""
    kind = kind or ('self_check' if self_check else 'eval')
    tasks, ends, done = {}, {}, set()
    for r in records:
        if r.get('type') == 'pair_start':
            tasks[r['pair']] = {k: r.get(k) for k in ('task', 'sandbox', 'base')}
        elif r.get('type') == 'pair_end':
            ends[r['pair']] = dict(r, **tasks[r['pair']])
        elif r.get('type') == kind:
            done.add(r['pair'])
    return [r for pair, r in ends.items() if pair not in done]


def evaluate(run, dataset, split, records, instances, execute, append, self_check=False, harness_dir=HARNESS_DIR,
             workers=2, patch_text=None):
    """`devflow bench eval`: hidden tests and diff size for every finished pair not yet evaluated. One harness call
    per model name (`<combo>__r<replica>`) — the harness keys predictions by instance. With `self_check` the gold
    patch stands in for the agent's; the result goes to `self_check` lines, not `eval`."""
    kind = 'self_check' if self_check else 'eval'
    patch_text = patch_text or (lambda path: Path(path).read_text(encoding='utf-8'))
    pending = pending_pairs(records, self_check)
    rounds = len({r['harness_run_id'] for r in records if r.get('type') in ('eval', 'self_check') and r.get('harness_run_id')})
    groups = {}
    results = []
    for end in pending:
        instance = instances[end['task']]
        patch = instance['patch'] if self_check else patch_text(end['patch'])
        record = {'type': kind, 'at': now(), 'pair': end['pair'], 'attempt': end.get('attempt', 1), 'task': end['task'],
                  'diff': diff_stats(patch, instance['patch'])}
        if not patch.strip():
            record.update(resolved=False, reason='empty patch', harness_run_id=None)
            results.append(record)
            continue
        model = end['pair'][len(end['task']) + 2:]
        groups.setdefault(model, []).append((record, {'instance_id': end['task'], 'model_name_or_path': model, 'model_patch': patch}))
    for model, items in groups.items():
        rounds += 1
        run_id = f'{run}-eval-{rounds}'
        reports = run_predictions(dataset, split, [pred for _, pred in items], run_id, execute, workers, harness_dir)
        for record, pred in items:
            report = reports.get(pred['instance_id'])
            record['harness_run_id'] = run_id
            if report is None:
                record.update(resolved=False, reason='no harness report')
            else:
                record.update(report)
            results.append(record)
    for record in results:
        append(record)
    return results


PHPSTAN_BINARIES = ('vendor/bin/phpstan', 'dev-tools/vendor/bin/phpstan')
PHPSTAN_CONFIGS = ('phpstan.neon', 'phpstan.neon.dist', 'phpstan.dist.neon')


def parse_phpstan(text):
    """Error count of `phpstan --error-format=json`: file errors plus the errors outside files; None when the output
    is not its JSON (a crash, a missing config)."""
    try:
        totals = json.loads(text)['totals']
        return int(totals['file_errors']) + int(totals['errors'])
    except (ValueError, KeyError, TypeError):
        return None


def phpstan_tool(repo):
    """`(binary, config)` of phpstan in the repository tree, None without either."""
    repo = Path(repo)
    binary = next((b for b in PHPSTAN_BINARIES if (repo / b).is_file()), None)
    config = next((c for c in PHPSTAN_CONFIGS if (repo / c).is_file()), None)
    return (binary, config) if binary and config else None


def phpstan_errors(execute, binary, directory, files, timeout=900):
    script = f'cd {shlex.quote(str(directory))} && exec {shlex.quote(binary)} analyse --error-format=json --no-progress ' \
             f'--memory-limit=1G {" ".join(shlex.quote(f) for f in files)}'
    proc = execute(['sh', '-c', script], timeout)
    return parse_phpstan(proc.stdout), (proc.stderr or '').strip()[-500:]


def static_check(execute, repo, base, files):
    """Lint and static analysis of the patch's PHP files in the task container, `execute` bound to `repo`.
    `lint_errors` — files `php -l` rejects after the patch; `new_static_errors` — phpstan errors after the patch minus
    those on the base commit (a worktree next to `repo`), None with the `reason` when there is no phpstan or it crashed."""
    repo = Path(repo)
    php = [f for f in files if f.endswith('.php') and (repo / f).is_file()]
    result = {'tool': None, 'files': len(php), 'lint_errors': 0, 'new_static_errors': None}
    if not php:
        return dict(result, reason='no php files in the patch')
    result['tool'] = 'php -l'
    for path in php:
        if execute(['php', '-l', path], 120).returncode != 0:
            result['lint_errors'] += 1
    tool = phpstan_tool(repo)
    if tool is None:
        return dict(result, reason='no phpstan in the repository')
    binary, config = tool
    result['tool'] = f'php -l + {binary} ({config})'
    base_dir = repo.parent / 'base'
    worktree = subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '--detach', '--force', str(base_dir), base],
                              capture_output=True, text=True, timeout=600)
    if worktree.returncode != 0:
        return dict(result, reason=f'git worktree failed: {(worktree.stderr or "").strip()[-300:]}')
    try:
        for vendor in {Path(b).parent.parent for b in PHPSTAN_BINARIES}:  # ignored by git, so absent from the worktree
            if (repo / vendor).is_dir() and not (base_dir / vendor).exists():
                (base_dir / vendor).symlink_to(repo / vendor)
        after, after_err = phpstan_errors(execute, binary, repo, php)
        before_files = [f for f in php if (base_dir / f).is_file()]
        before, before_err = phpstan_errors(execute, binary, base_dir, before_files) if before_files else (0, '')
    finally:
        subprocess.run(['git', '-C', str(repo), 'worktree', 'remove', '--force', str(base_dir)], capture_output=True, timeout=600)
    if after is None or before is None:
        return dict(result, reason=f'phpstan gave no report: {after_err or before_err}')
    return dict(result, static_before=before, static_after=after, new_static_errors=after - before)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')
