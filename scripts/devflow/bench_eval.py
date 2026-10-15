"""SWE-bench set adapter: dataset instances, gold run in the harness, set building."""
import json
import re
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


def diff_stats(patch, gold=None):
    """Size of a patch from its text: files, added/removed lines, test files touched; `size_ratio` — lines changed
    against the gold patch (None without a gold patch or when it changes nothing)."""
    files, added, removed, tests = set(), 0, 0, set()
    for line in (patch or '').splitlines():
        if line.startswith('diff --git '):
            path = line.split(' b/', 1)[-1]
            files.add(path)
            if re.search(r'(^|/)tests?/|Test\.php$|_test\.go$|\.test\.[jt]sx?$', path):
                tests.add(path)
        elif line.startswith('+') and not line.startswith('+++'):
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


def pending_pairs(records, self_check=False):
    """Last `pair_end` of every pair without an `eval` line (`self_check` line for the self-check), with the pair's
    `task` from its `pair_start`."""
    kind = 'self_check' if self_check else 'eval'
    tasks, ends, done = {}, {}, set()
    for r in records:
        if r.get('type') == 'pair_start':
            tasks[r['pair']] = r['task']
        elif r.get('type') == 'pair_end':
            ends[r['pair']] = dict(r, task=tasks[r['pair']])
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


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')
