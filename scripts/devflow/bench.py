"""`devflow bench`: model × phase combos for the pipeline benchmark."""
import json
import shutil
import subprocess
from pathlib import Path

from . import bench_container as container
from .bench_eval import CACHE_DIR, SETS_DIR, build_set, instances
from .bench_runners import (CLAUDE_ISOLATION, PROBE_TIMEOUT, RUNNERS, WEB_TOOLS, claude_init, claude_probe_command,
                            host_execute, probe)
from .documents import WorkflowError
from .policy import PHASES

ROOT = Path(__file__).resolve().parents[2]
COMBOS_DIR = ROOT / 'bench/combos'


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


def command(args):
    if args.bench_command == 'combos':
        selected = combos(args.names)
        result = {'combos': selected}
        if args.probe:
            result['probes'] = probe_combos(selected)
        return result
    if args.bench_command == 'doctor':
        return doctor(args.instance, keep=args.keep)
    if args.bench_command == 'set' and args.set_command == 'build':
        return build_set(args.name, args.dataset, args.language, args.per_repo, count=args.count, split=args.split,
                         workers=args.workers)
    raise WorkflowError(f'unknown bench command: {args.bench_command}')
