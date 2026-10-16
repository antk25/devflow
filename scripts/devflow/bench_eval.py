"""Set adapters: `swebench` (dataset instances, gold run in the harness, set building) and `references`
(closed devflow tasks: spec, approved research and plan, the commit the task started from)."""
import json
import os
import re
import shlex
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import jev
from .documents import WorkflowError, artifact, context, document, plan_steps
from .storage import db_path
from .workflow import plan_coverage

ROOT = Path(__file__).resolve().parents[2]
SETS_DIR = ROOT / 'bench/sets'
HELPER = ROOT / 'bench/swebench_helper.py'
CACHE_DIR = Path('~/.local/share/devflow/bench').expanduser()
DATASETS_DIR = CACHE_DIR / 'datasets'
HARNESS_DIR = CACHE_DIR / 'harness'
SWEBENCH_VERSION = '5.0.2'
REFERENCES_DIR = CACHE_DIR / 'references'
# The common runner image of reference tasks: python + git, no SWE-bench image behind them.
REFERENCES_IMAGE = 'python:3.12-bookworm'
TASK_SLUG = 'bench-task'
JUDGE_TIMEOUT = 60
REFERENCES_TEST_CMD = '.venv/bin/python -m pytest -q'
REFERENCE_SLUGS = ('df-10-project-init-sync', 'df-12-jev-coverage-check', 'df-13-jev-plan-check', 'df-14-bash-guard',
                   'df-15-side-fixes', 'df-16-timesheet', 'df-17-jira-accounts')
LANGUAGE_PARSERS = {'php': ('parse_log_phpunit',), 'go': ('parse_log_gotest',), 'ts': ('parse_log_vitest', 'parse_log_jest'),
                    'js': ('parse_log_calypso', 'parse_log_chart_js', 'parse_log_p5js', 'parse_log_marked', 'parse_log_react_pdf')}
# Screenshots of Multimodal issues stay links in the task text: the sandbox network is closed, nobody fetches them.
IMAGE_LIMITATION = 'скриншоты из issue — только ссылки в тексте ТЗ; сеть к ним из песочницы закрыта'
TEST_OUTPUT = re.compile(r"^: '>>>>> Start Test Output'\n(.*?)\n: '>>>>> End Test Output'", re.S | re.M)
PRE_TEST = re.compile(r"^EOF_\d+\n(.*?)^: '>>>>> Start Test Output'", re.S | re.M)


def host_execute(cmd, cwd=None, timeout=None):
    return subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)


def uv_command(script_args):
    return ['uv', 'run', '--with', f'swebench=={SWEBENCH_VERSION},datasets', 'python', '-I', *script_args]


def test_cmd(eval_script):
    """The test command of a harness eval script: the lines between the test-output markers, without the `| cat`,
    preceded by the build lines some scripts run between the test patch and the tests (`make build` and the like)."""
    match = TEST_OUTPUT.search(eval_script or '')
    if not match:
        return None
    pre = PRE_TEST.search(eval_script)
    build = [line.strip() for line in (pre.group(1) if pre else '').splitlines() if line.strip()]
    lines = []
    for line in match.group(1).splitlines():
        line = re.sub(r'\s*\|\s*cat$', '', line.strip())
        if line.startswith('(') and line.endswith(')'):
            line = line[1:-1]
        lines.append(line)
    return ' && '.join(build + ['\n'.join(lines)])


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


def set_instances(data, ids, execute=None, directory=DATASETS_DIR, references_dir=REFERENCES_DIR):
    """Instances of a loaded set by its adapter, in the common schema."""
    adapter = data.get('adapter')
    if adapter == 'swebench':
        return instances(data['dataset'], data['split'], ids, execute, directory)
    if adapter == 'references':
        return reference_instances(data['dataset'], ids, references_dir)
    raise WorkflowError(f"set {data.get('name')}: unknown adapter {adapter!r}")


def connect_readonly(ctx):
    """The real state database of `ctx`, opened read-only; the snapshot never writes there."""
    path, _ = db_path(ctx)
    if not path.is_file():
        raise WorkflowError(f'State database is missing: {path}')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def approved_document(db, slug, phase):
    """The latest approved `phase` document of `slug`: `{revision, approved_at, content}` or None."""
    row = db.execute('SELECT a.revision, a.approved_at, r.content FROM approvals a JOIN artifacts r '
                     'ON r.slug=a.slug AND r.phase=a.phase AND r.revision=a.revision '
                     'WHERE a.slug=? AND a.phase=? ORDER BY a.approved_at DESC LIMIT 1', (slug, phase)).fetchone()
    return dict(row) if row else None


def commit_before(repo, until, branch='main', execute=None):
    """The last commit of `branch` not later than `until` (ISO time): where the task started."""
    proc = (execute or host_execute)(['git', '-C', str(repo), 'log', '-1', '--format=%H', f'--until={until}', branch], timeout=60)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise WorkflowError(f'git log {branch} --until {until} in {repo}: {(proc.stderr or "").strip()[-300:] or "no commit"}')
    return proc.stdout.strip()


def snapshot_references(name, ctx, slugs=REFERENCE_SLUGS, commits=None, branch='main', execute=None, sets_dir=SETS_DIR,
                        references_dir=REFERENCES_DIR):
    """`devflow bench set snapshot <name>`: for every slug the spec from the vault, the latest approved research and plan
    from the state database (read-only) and the commit of `branch` at the research approval (`commits` overrides it);
    the documents go to `<references_dir>/<name>/<slug>.json`, the set to bench/sets/<name>.json."""
    commits = commits or {}
    db = connect_readonly(ctx)
    target = Path(references_dir) / name
    target.mkdir(parents=True, exist_ok=True)
    details = {}
    try:
        for slug in slugs:
            tz = artifact(ctx['vault'], 'tz', slug)
            if tz is None:
                raise WorkflowError(f'{slug}: no tz document in {ctx["vault"] / "tz"}')
            research, plan = approved_document(db, slug, 'research'), approved_document(db, slug, 'plan')
            for phase, doc in (('research', research), ('plan', plan)):
                if doc is None:
                    raise WorkflowError(f'{slug}: no approved {phase} in the state database')
            commit = commits.get(slug) or commit_before(ctx['cwd'], research['approved_at'], branch, execute)
            (target / f'{slug}.json').write_text(json.dumps(
                {'slug': slug, 'repo': str(ctx['cwd']), 'commit': commit, 'tz': tz['raw'], 'research': research, 'plan': plan},
                ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            details[slug] = {'commit': commit, 'commit_source': 'manual' if slug in commits else 'git log --until',
                             'research_revision': research['revision'], 'research_approved_at': research['approved_at'],
                             'plan_revision': plan['revision'], 'plan_approved_at': plan['approved_at']}
    finally:
        db.close()
    result = {'name': name, 'adapter': 'references', 'dataset': name, 'split': 'references', 'swebench': None,
              'source': str(ctx['cwd']), 'branch': branch, 'image': REFERENCES_IMAGE,
              'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'instances': list(slugs), 'details': details}
    sets_dir = Path(sets_dir)
    sets_dir.mkdir(parents=True, exist_ok=True)
    path = sets_dir / f'{name}.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return dict(result, path=str(path), references=str(target))


def reference_instances(name, ids, references_dir=REFERENCES_DIR):
    """Reference tasks in the instance schema: the spec body is the problem statement, `source` + `base_commit`
    say where the repository comes from, `reference` keeps the approved research and plan for the judge."""
    directory = Path(references_dir) / name
    loaded = {}
    for slug in ids:
        path = directory / f'{slug}.json'
        if not path.is_file():
            raise WorkflowError(f'{name}: no reference snapshot for {slug}; run devflow bench set snapshot {name}')
        data = json.loads(path.read_text(encoding='utf-8'))
        tz = data['tz']
        match = re.match(r'\A---\n.*?\n---(?:\n|$)', tz, re.S)
        loaded[slug] = {'instance_id': slug, 'repo': 'devflow', 'source': data['repo'], 'base_commit': data['commit'],
                        'problem_statement': tz[match.end():] if match else tz, 'patch': '', 'test_patch': '',
                        'test_cmd': REFERENCES_TEST_CMD, 'image': REFERENCES_IMAGE, 'FAIL_TO_PASS': [], 'PASS_TO_PASS': [],
                        'reference': {'research': data['research'], 'plan': data['plan']}}
    return loaded


def by_language(items, language):
    parsers = LANGUAGE_PARSERS.get(language)
    if not parsers:
        raise WorkflowError(f'unknown language {language!r}; expected one of {", ".join(LANGUAGE_PARSERS)}')
    return [item for item in items if item.get('log_parser') in parsers]


def image_links(item):
    """Screenshot links of the issue text (Multimodal `image_assets`), empty for the other datasets."""
    assets = item.get('image_assets') or {}
    if isinstance(assets, str):
        assets = json.loads(assets)
    return list(assets.get('problem_statement') or [])


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
    screenshots = {item['instance_id']: len(image_links(item)) for item in picked}
    result = {'name': name, 'adapter': 'swebench', 'dataset': dataset, 'split': split, 'language': language,
              'swebench': data.get('swebench', SWEBENCH_VERSION),
              'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'limitations': [IMAGE_LIMITATION] if any(screenshots.values()) else [],
              'instances': [item['instance_id'] for item in picked],
              'details': {item['instance_id']: {'repo': item['repo'], 'created_at': item['created_at'],
                                                'image': item['image'], 'gold_resolved': True,
                                                **({'screenshots': screenshots[item['instance_id']]}
                                                   if screenshots[item['instance_id']] else {})} for item in picked},
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


def validate_plan(path):
    """`devflow validate` of the candidate plan: ok with its step count, or the error text."""
    try:
        return {'ok': True, 'steps': len(plan_steps(document(path))), 'error': None}
    except WorkflowError as exc:
        return {'ok': False, 'steps': None, 'error': str(exc)}


def judge_context(sandbox):
    """A copy of the sandbox context with `jev: true`, next to the vault, never in the task repository."""
    cwd = Path(sandbox) / 'judge'
    cwd.mkdir(exist_ok=True)
    (cwd / 'AGENTS.md').write_text(f"---\nproject: bench\nvault: {Path(sandbox) / 'vault'}\njev: true\n---\n", encoding='utf-8')
    return context(cwd)


def coverage(sandbox, threshold):
    """Jev `check_plan` of the candidate: `noul` per research requirement, without a journal event."""
    result = plan_coverage(judge_context(sandbox), TASK_SLUG, threshold)
    noul = [r['noul'] for r in result['requirements']]
    return {'status': result['status'], 'reason': result['reason'], 'model': result['model'], 'noul': noul,
            'flagged': sum(1 for r in result['requirements'] if r['flagged']), 'min': min(noul) if noul else None}


def judge(reference, candidate):
    """The approved plan against the candidate plan with three `noul` questions; `reason` instead of `noul` when Jev
    cannot answer. Only the plans go in: the three questions are about the plan, and two research documents on top
    would push most reference tasks over the Jev input limit."""
    state = {'reference': jev.mask(reference['plan']['content']), 'candidate': jev.mask(candidate['plan'])}
    questions = jev.judge_questions()
    size = len(json.dumps({'state': state, 'questions': questions}, ensure_ascii=False))
    if size > jev.INPUT_LIMIT:
        return {'model': None, 'noul': None, 'reason': f'документы больше лимита: {size} символов'}
    out = jev.decide(state, questions, timeout=JUDGE_TIMEOUT)
    if 'error' in out:
        return {'model': None, 'noul': None, 'reason': out['error']}
    noul = {q['key']: (out['answers'].get(q['key']) or {}).get('noul') for q in questions}
    missing = [k for k, v in noul.items() if not isinstance(v, (int, float))]
    if missing:
        return {'model': out['model'], 'noul': None, 'reason': f"в ответе нет noul для {', '.join(missing)}"}
    return {'model': out['model'], 'noul': noul, 'reason': None}


def judge_run(records, instances, append, threshold=None):
    """`judge` lines for every finished pair of a references run without one: `validate` of the candidate plan,
    Jev coverage of the candidate's own research by its plan, and the reference-against-candidate judge."""
    threshold = float(os.environ.get('DEVFLOW_JEV_PLAN_THRESHOLD', '0.95')) if threshold is None else threshold
    results = []
    for end in pending_pairs(records, kind='judge'):
        record = {'type': 'judge', 'at': now(), 'pair': end['pair'], 'attempt': end.get('attempt', 1), 'task': end['task'],
                  'validate': None, 'coverage': None, 'judge': None, 'reason': None}
        vault = Path(end['sandbox'] or '') / 'vault'
        plan_path = vault / 'plans' / f'{TASK_SLUG}.md'
        reference = instances[end['task']].get('reference')
        if not plan_path.is_file():
            record['reason'] = f'no plan at {plan_path}'
        elif not reference:
            record['reason'] = f"{end['task']}: no reference documents"
        else:
            record['validate'] = validate_plan(plan_path)
            record['coverage'] = coverage(vault.parent, threshold)
            record['judge'] = judge(reference, {'plan': plan_path.read_text(encoding='utf-8')})
        append(record)
        results.append(record)
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
