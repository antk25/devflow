"""`devflow bench`: model × phase combos for the pipeline benchmark."""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from string import Template

from . import bench_container as container
from . import bench_runners as runners
from .bench_eval import CACHE_DIR, SETS_DIR, SWEBENCH_VERSION, build_set, instances
from .bench_runners import (CLAUDE_ISOLATION, PROBE_TIMEOUT, RUNNERS, WEB_TOOLS, claude_init, claude_probe_command,
                            host_execute, probe)
from .documents import WorkflowError, context
from .pi import task_message
from .policy import PHASES
from .storage import connect
from .workflow import approve, interrupt, route, start

ROOT = Path(__file__).resolve().parents[2]
COMBOS_DIR = ROOT / 'bench/combos'
AGENTS_TEMPLATE = ROOT / 'bench/AGENTS.bench.md'
TASK_SLUG = 'bench-task'
# Outside the home directory on purpose: claude picks up CLAUDE.md from every ancestor of its cwd.
SANDBOX_ROOT = Path('/var/tmp/devflow-bench')
BUDGET_USD = {'research': 5.0, 'plan': 5.0, 'implement': 25.0}
PHASE_TIMEOUT = 3600
MAX_PHASES = 40
RUNNING_REASON = 'bench: шаг не записал finish'
GIT_IDENTITY = ['-c', 'user.name=bench', '-c', 'user.email=bench@devflow.local', '-c', 'commit.gpgsign=false']


def load_combo(path):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise WorkflowError(f'combo {path}: {exc}') from exc
    if not isinstance(data, dict):
        raise WorkflowError(f'combo {path}: expected an object')
    combo = {'name': str(data.get('name') or path.stem)}
    for phase in PHASES:
        spec = data.get(phase)
        if not isinstance(spec, dict):
            raise WorkflowError(f'combo {combo["name"]}: phase {phase} is missing')
        runner, model, effort = spec.get('runner'), spec.get('model'), spec.get('effort')
        if runner not in RUNNERS:
            raise WorkflowError(f'combo {combo["name"]}: {phase}: unknown runner {runner!r}; expected one of {", ".join(RUNNERS)}')
        if not model or not isinstance(model, str):
            raise WorkflowError(f'combo {combo["name"]}: {phase}: model is required')
        if runner == 'pi' and '/' not in model.strip('/'):
            raise WorkflowError(f'combo {combo["name"]}: {phase}: pi model must be provider/id, got {model!r}')
        if not effort or not isinstance(effort, str):
            raise WorkflowError(f'combo {combo["name"]}: {phase}: effort is required')
        combo[phase] = {'runner': runner, 'model': model, 'effort': effort}
    return combo


def combos(names=None, directory=COMBOS_DIR):
    """Combos by name from `directory` (a name may also be a path to a JSON file), or all of them."""
    if not names:
        paths = sorted(Path(directory).glob('*.json'))
        if not paths:
            raise WorkflowError(f'no combos in {directory}')
        return [load_combo(p) for p in paths]
    result = []
    for name in names:
        path = Path(name) if name.endswith('.json') or '/' in name else Path(directory) / f'{name}.json'
        if not path.is_file():
            raise WorkflowError(f'unknown combo: {name}')
        result.append(load_combo(path))
    return result


def load_set(name, directory=SETS_DIR):
    """`bench/sets/<name>.json`: {name, adapter, dataset, split, swebench, instances: [id…]}; instance order is kept."""
    path = Path(directory) / f'{name}.json'
    if not path.is_file():
        raise WorkflowError(f'unknown set: {name}')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as exc:
        raise WorkflowError(f'set {path}: {exc}') from exc
    missing = [k for k in ('name', 'adapter', 'dataset', 'split', 'swebench', 'instances') if k not in data]
    if missing or not isinstance(data['instances'], list):
        raise WorkflowError(f'set {name}: missing {", ".join(missing) or "instances list"}')
    return data


def probe_combos(selected, execute=None):
    """Every distinct runner × model × effort of the combos, probed once."""
    execute = execute or host_execute
    seen = {}
    for combo in selected:
        for phase in PHASES:
            spec = combo[phase]
            key = (spec['runner'], spec['model'], spec['effort'])
            if key not in seen:
                seen[key] = dict(zip(('runner', 'model', 'effort'), key), **probe(execute, *key))
    return list(seen.values())


def set_of_instance(instance_id, directory=SETS_DIR):
    for path in sorted(Path(directory).glob('*.json')):
        data = load_set(path.stem, directory)
        if instance_id in data['instances']:
            return data
    raise WorkflowError(f'instance {instance_id} is in no set under {directory}')


def git_apply(repo, patch):
    proc = subprocess.run(['git', '-C', str(repo), 'apply', '--whitespace=nowarn'], input=patch,
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise WorkflowError(f'git apply failed: {(proc.stderr or "").strip()[-500:]}')


def gold_check(instance, workdir, execute, apply=None, timeout=1800):
    """The gold patch in a host copy of the repository: tests fail before it and pass after it, run in the task container."""
    apply = apply or git_apply
    name = f'devflow-bench-doctor-{instance["instance_id"]}'
    repo = container.checkout(instance['image'], Path(workdir) / 'repo', execute)
    container.start(name, instance['image'], repo, execute=execute)
    try:
        run = container.executor(name, repo, execute=execute)
        apply(repo, instance['test_patch'])
        before = container.shell(run, instance['test_cmd'], timeout)
        apply(repo, instance['patch'])
        after = container.shell(run, instance['test_cmd'], timeout)
        offline = container.shell(run, container.OFFLINE_SCRIPT, 60)
    finally:
        container.stop(name, execute)
    return {'before': before, 'after': after, 'offline': offline}


def doctor(instance_id, execute=None, probe_execute=None, workdir=None, keep=False):
    """Checks of the host-runner setup for one task; every check is {check, ok, detail}."""
    execute = execute or container.docker_execute
    probe_execute = probe_execute or host_execute
    data = set_of_instance(instance_id)
    instance = instances(data['dataset'], data['split'], [instance_id])[instance_id]
    checks = []
    try:
        internal = container.ensure_network(execute)
        checks.append({'check': 'network', 'ok': internal, 'detail': f'{container.NETWORK} internal={internal}'})
    except RuntimeError as exc:
        checks.append({'check': 'network', 'ok': False, 'detail': str(exc)})
    for result in probe_combos(combos(), probe_execute):
        checks.append({'check': f"probe {result['runner']} {result['model']} {result['effort']}", 'ok': result['ok'],
                       'detail': result['model_actual'] if result['ok'] else result['error_text']})
    proc = probe_execute(claude_probe_command('claude-sonnet-5-5', 'low', output_format='stream-json') + ['--verbose'],
                         PROBE_TIMEOUT)
    init = claude_init(proc.stdout) or {}
    tools = init.get('tools') or []
    leaked = [t for t in WEB_TOOLS if t in tools]
    checks.append({'check': 'claude web tools', 'ok': bool(tools) and not leaked,
                   'detail': f'init tools: {len(tools)}, web: {leaked or "none"}, mcp: {init.get("mcp_servers")}, '
                             f'skills: {init.get("skills")}, memory: {init.get("memory_paths")}'})
    workdir = Path(workdir or CACHE_DIR / 'work' / f'doctor-{instance_id}')
    try:
        result = gold_check(instance, workdir, execute)
    except (WorkflowError, RuntimeError, subprocess.TimeoutExpired) as exc:
        checks.append({'check': 'gold', 'ok': False, 'detail': str(exc)})
    else:
        before, after, offline = result['before'], result['after'], result['offline']
        checks.append({'check': 'offline', 'ok': offline.returncode != 0,
                       'detail': f'github.com from the container: exit {offline.returncode} {(offline.stderr or "").strip()[-200:]}'})
        checks.append({'check': 'gold', 'ok': before.returncode != 0 and after.returncode == 0,
                       'detail': f'tests before gold: exit {before.returncode}; after gold: exit {after.returncode}; '
                                 f'{(after.stdout or "").strip().splitlines()[-1:] or ""}'})
    finally:
        if not keep and workdir.exists():
            shutil.rmtree(workdir)
    return {'instance': instance_id, 'runner_mode': container.RUNNER_MODE, 'claude_isolation': CLAUDE_ISOLATION,
            'ok': all(c['ok'] for c in checks), 'checks': checks}


def pair_id(pair):
    return f"{pair['task']}__{pair['combo']}__r{pair['replica']}"


def git(repo, *args):
    proc = subprocess.run(['git', '-C', str(repo), *GIT_IDENTITY, *args], capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise WorkflowError(f'git {args[0]} failed in {repo}: {(proc.stderr or "").strip()[-500:]}')
    return proc.stdout.strip()


def task_document(instance):
    return (f"---\ncreated: {datetime.date.today().isoformat()}\nproject: bench\ntype: tz\n"
            f"task: {instance['instance_id']}\n---\n\n# {instance['instance_id']}\n\n"
            f"{instance['problem_statement'].strip()}\n\n"
            "Внешних ссылок и Jira у задачи нет: вход — только это ТЗ.\n")


@contextmanager
def state_env(state):
    """`DEVFLOW_STATE_DIR` pointed at the sandbox while a database is opened; the variable is restored after."""
    saved = os.environ.get('DEVFLOW_STATE_DIR')
    os.environ['DEVFLOW_STATE_DIR'] = str(state)
    try:
        yield
    finally:
        if saved is None:
            del os.environ['DEVFLOW_STATE_DIR']
        else:
            os.environ['DEVFLOW_STATE_DIR'] = saved


def init_state(repo, state):
    """`devflow init` of the sandbox repository with its database under `state`, never under the real root."""
    with state_env(state):
        connect(context(repo), create=True).close()


def container_name(pair):
    return f'devflow-bench-{pair_id(pair)}'


def make_sandbox(root, pair, instance, execute=None):
    """`<root>/<pair_id>/` with `repo/` (the image's /testbed on a single base commit), `vault/`, `state/`, `home/`;
    an existing directory is replaced. Returns the paths and `base`, the sha of the base commit."""
    execute = execute or container.docker_execute
    sb_dir = Path(root).expanduser().resolve() / pair_id(pair)
    if sb_dir.exists():
        shutil.rmtree(sb_dir)
    sb = {'dir': sb_dir, 'repo': sb_dir / 'repo', 'vault': sb_dir / 'vault', 'state': sb_dir / 'state', 'home': sb_dir / 'home',
          'pair': pair_id(pair)}
    container.checkout(instance['image'], sb['repo'], execute)
    for folder in ('tz', 'research', 'plans', 'changelog', 'notes'):
        (sb['vault'] / folder).mkdir(parents=True)
    sb['state'].mkdir()
    sb['home'].mkdir()
    shutil.rmtree(sb['repo'] / '.git', ignore_errors=True)
    git(sb['repo'], 'init', '-q')
    (sb['repo'] / '.git/info').mkdir(exist_ok=True)
    (sb['repo'] / '.git/info/exclude').write_text('AGENTS.md\n.devflow/\n', encoding='utf-8')
    test_cmd = instance['test_cmd']
    if container.RUNNER_MODE == 'host':
        test_cmd = f"docker exec -w {sb['repo']} {container_name(pair)} sh -c {json.dumps(test_cmd)}"
    agents = Template(AGENTS_TEMPLATE.read_text(encoding='utf-8')).substitute(
        vault=sb['vault'], instance_id=instance['instance_id'], repo=instance.get('repo', ''), test_cmd=test_cmd)
    (sb['repo'] / 'AGENTS.md').write_text(agents, encoding='utf-8')
    (sb['vault'] / 'tz' / f'{TASK_SLUG}.md').write_text(task_document(instance), encoding='utf-8')
    git(sb['repo'], 'add', '-A')
    git(sb['repo'], 'commit', '-q', '-m', 'base')
    sb['base'] = git(sb['repo'], 'rev-parse', 'HEAD')
    init_state(sb['repo'], sb['state'])
    return sb


def sandbox(set_name, instance_id, root=None, execute=None):
    """A sandbox of the task for manual debugging, with its task container started."""
    execute = execute or container.docker_execute
    data = load_set(set_name)
    if instance_id not in data['instances']:
        raise WorkflowError(f'instance {instance_id} is not in set {set_name}')
    instance = instances(data['dataset'], data['split'], [instance_id])[instance_id]
    pair = {'task': instance_id, 'combo': 'manual', 'replica': 1}
    sb = make_sandbox(Path(root or SANDBOX_ROOT / 'sandbox'), pair, instance, execute)
    name = container_name(pair)
    container.start(name, instance['image'], sb['dir'], execute=execute)
    return {**{k: str(v) for k, v in sb.items()}, 'container': name, 'slug': TASK_SLUG,
            'route': f'DEVFLOW_STATE_DIR={sb["state"]} devflow --cwd {sb["repo"]} route {TASK_SLUG}',
            'tests': f'docker exec -w {sb["repo"]} {name} sh -c {json.dumps(instance["test_cmd"])}'}


def pairs(tasks, combo_names):
    """`{task, combo, replica}` interleaved by task: t1×A, t1×B, t1×A′, t2×A …; a repeated combo name is the next replica."""
    replicas = {}
    order = []
    for name in combo_names:
        replicas[name] = replicas.get(name, 0) + 1
        order.append((name, replicas[name]))
    return [{'task': task, 'combo': name, 'replica': replica} for task in tasks for name, replica in order]


def open_questions(research_path):
    """Number of `- [ ]` items in the `Open questions` section of the research document."""
    try:
        text = Path(research_path).read_text(encoding='utf-8')
    except OSError:
        return 0
    match = re.search(r'^##+\s*Open questions[^\n]*\n(.*?)(?=^##\s|\Z)', text, re.S | re.M | re.I)
    return len(re.findall(r'^\s*- \[ \]', match.group(1), re.M)) if match else 0


def append(journal, record):
    journal = Path(journal)
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + '\n')
        fh.flush()
        os.fsync(fh.fileno())


def read(journal):
    try:
        lines = Path(journal).read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def extract_patch(repo, base):
    """Everything since the base commit — the agent's commits, uncommitted edits and new files — through a
    throwaway index, so `.git/info/exclude` (AGENTS.md, .devflow/) still applies."""
    index = Path(repo) / '.git' / 'bench-index'
    env = dict(os.environ, GIT_INDEX_FILE=str(index))
    try:
        for args in (['read-tree', 'HEAD'], ['add', '-A']):
            proc = subprocess.run(['git', '-C', str(repo), *GIT_IDENTITY, *args], env=env, capture_output=True, text=True, timeout=600)
            if proc.returncode != 0:
                raise WorkflowError(f'git {args[0]} failed in {repo}: {(proc.stderr or "").strip()[-500:]}')
        proc = subprocess.run(['git', '-C', str(repo), 'diff', '--cached', '--binary', base], env=env,
                              capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise WorkflowError(f'git diff failed in {repo}: {(proc.stderr or "").strip()[-500:]}')
        return proc.stdout
    finally:
        index.unlink(missing_ok=True)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def fingerprint(state):
    return (state['state'], state.get('research_revision'), state.get('plan_revision'), state.get('run_id'), state.get('step'))


def drive(sb, combo, execute, journal, limits=None, attempt=1):
    """The autodriver of one pair: walks `route`, runs phases through `execute`, approves research and plan as they are,
    starts implement steps. Writes only `phase` lines to the journal and nothing outside `sb`."""
    limits = dict(limits or {})
    budgets = {**BUDGET_USD, **(limits.get('budget') or {})}
    timeout = limits.get('timeout', PHASE_TIMEOUT)
    ctx = context(sb['repo'])
    with state_env(sb['state']):
        db = connect(ctx)
    result = {'outcome': None, 'phases': 0, 'steps': 0, 'open_questions': None, 'error_text': None}
    stalls = 0
    try:
        while result['phases'] < limits.get('max_phases', MAX_PHASES):
            current = route(ctx, db, TASK_SLUG)
            state = current['state']
            if state in ('completed', 'blocked'):
                result['outcome'] = state
                return result
            if state == 'approval_required':
                if current['phase'] == 'research':
                    result['open_questions'] = open_questions(current['artifact'])
                approve(ctx, db, TASK_SLUG, current['phase'], current['revision'])
                continue
            if state == 'running':
                interrupt(db, current['run_id'], RUNNING_REASON)
                continue
            if state in ('research', 'plan', 'plan_outdated'):
                phase, run, step = current['phase'], None, None
            elif state == 'ready':
                phase, step = 'implement', current['step']
                run = start(ctx, db, TASK_SLUG, step, current['revision'])
                result['steps'] += 1
            else:
                result.update(outcome='error', error_text=f'unexpected state {state}')
                return result
            spec = combo[phase]
            phase_result = runners.run_phase(execute, spec['runner'], phase, spec, task_message(phase, ctx, current, step, run),
                                             sb, timeout, budgets.get(phase))
            result['phases'] += 1
            after = route(ctx, db, TASK_SLUG)
            metrics = phase_result['metrics']
            append(journal, {'type': 'phase', 'at': now(), 'pair': sb.get('pair'), 'attempt': attempt, 'phase': phase,
                             'step': step, 'runner': spec['runner'], 'model_req': spec['model'], 'effort_req': spec['effort'],
                             **{k: v for k, v in metrics.items() if k not in ('runner', 'is_error', 'subtype', 'result')},
                             'error': phase_result['error'], 'error_text': phase_result['error_text'],
                             'route_after': after['state']})
            if phase_result['error']:
                result.update(outcome={'api': 'paused'}.get(phase_result['error'], phase_result['error']),
                              error_text=phase_result['error_text'])
                return result
            if metrics.get('model_actual') and metrics['model_actual'] != spec['model']:
                result.update(outcome='model_mismatch',
                              error_text=f"requested {spec['model']}, got {metrics['model_actual']}")
                return result
            if fingerprint(after) == fingerprint(current):
                stalls += 1
                if stalls >= 2:
                    result.update(outcome='stalled', error_text=f'state {state} unchanged after two phases')
                    return result
            else:
                stalls = 0
        result.update(outcome='stalled', error_text='phase limit reached')
        return result
    except WorkflowError as exc:
        result.update(outcome='error', error_text=str(exc))
        return result
    finally:
        db.close()


def version_of(cmd):
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        return (proc.stdout or proc.stderr).strip().splitlines()[0]
    except (OSError, IndexError, subprocess.TimeoutExpired):
        return None


def run_start_record(name, data, selected, selected_pairs):
    agents = {phase: hashlib.sha256((ROOT / 'agents' / f'{phase}.md').read_bytes()).hexdigest()[:16] for phase in PHASES}
    return {'type': 'run_start', 'at': now(), 'run': name, 'set': data['name'], 'combos': [c['name'] for c in selected],
            'pairs': [pair_id(p) for p in selected_pairs], 'runner_mode': container.RUNNER_MODE,
            'devflow': version_of(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD']), 'agents_sha256': agents,
            'claude': version_of(['claude', '--version']), 'pi': version_of(['pi', '--version']),
            'swebench': data.get('swebench', SWEBENCH_VERSION)}


def run_dir(name):
    return context(ROOT)['vault'] / 'bench/runs' / name


def run_pair(pair, combo, instance, sb_root, journal, execute=None, limits=None, attempt=1):
    """One pair end to end: sandbox, task container, autodriver, patch, `pair_start`/`pair_end` lines."""
    execute = execute or container.docker_execute
    sb = make_sandbox(sb_root, pair, instance, execute)
    append(journal, {'type': 'pair_start', 'at': now(), 'pair': sb['pair'], 'attempt': attempt, 'task': pair['task'],
                     'combo': combo['name'], 'replica': pair['replica'], 'sandbox': str(sb['dir']), 'base': sb['base']})
    name = container_name(pair)
    container.start(name, instance['image'], sb['dir'], execute=execute)
    try:
        runner = container.runner_executor(name, sb['repo'], {'DEVFLOW_STATE_DIR': str(sb['state'])})
        outcome = drive(sb, combo, runner, journal, limits, attempt)
        patch = extract_patch(sb['repo'], sb['base'])
    finally:
        container.stop(name, execute)
    patch_path = Path(journal).parent / 'patches' / f"{sb['pair']}.diff"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text(patch, encoding='utf-8')
    record = {'type': 'pair_end', 'at': now(), 'pair': sb['pair'], 'attempt': attempt, **outcome,
              'patch': str(patch_path), 'patch_bytes': len(patch.encode('utf-8'))}
    append(journal, record)
    return record


def run(name, set_name, combo_names, tasks=None, yes=False, root=None, journal_dir=None, execute=None, limits=None):
    """`devflow bench run`: without `yes` only the pairs; with `yes` every pair in order, journal in the devflow vault."""
    data = load_set(set_name)
    selected = combos(combo_names)
    by_name = {c['name']: c for c in selected}
    task_ids = data['instances'][:tasks] if tasks else data['instances']
    selected_pairs = pairs(task_ids, [c['name'] for c in selected])
    directory = Path(journal_dir) if journal_dir else run_dir(name)
    journal = directory / 'journal.jsonl'
    result = {'run': name, 'journal': str(journal), 'pairs': [pair_id(p) for p in selected_pairs]}
    if not yes:
        return dict(result, state='dry_run')
    loaded = instances(data['dataset'], data['split'], task_ids)
    if not read(journal):
        append(journal, run_start_record(name, data, selected, selected_pairs))
    sb_root = Path(root or SANDBOX_ROOT) / name
    done = []
    for pair in selected_pairs:
        done.append(run_pair(pair, by_name[pair['combo']], loaded[pair['task']], sb_root, journal, execute, limits))
    return dict(result, state='done', pairs_done=len(done), outcomes={r['pair']: r['outcome'] for r in done})


def command(args):
    if args.bench_command == 'combos':
        selected = combos(args.names)
        result = {'combos': selected}
        if args.probe:
            result['probes'] = probe_combos(selected)
        return result
    if args.bench_command == 'doctor':
        return doctor(args.instance, keep=args.keep)
    if args.bench_command == 'sandbox':
        return sandbox(args.set, args.instance)
    if args.bench_command == 'run':
        return run(args.name, args.set, args.combo, tasks=args.tasks, yes=args.yes, root=args.root)
    if args.bench_command == 'set' and args.set_command == 'build':
        return build_set(args.name, args.dataset, args.language, args.per_repo, count=args.count, split=args.split,
                         workers=args.workers)
    raise WorkflowError(f'unknown bench command: {args.bench_command}')
