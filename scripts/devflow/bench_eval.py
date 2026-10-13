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
