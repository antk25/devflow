"""`devflow bench`: model × phase combos for the pipeline benchmark."""
import json
from pathlib import Path

from .bench_runners import RUNNERS, host_execute, probe
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


def command(args):
    if args.bench_command == 'combos':
        selected = combos(args.names)
        result = {'combos': selected}
        if args.probe:
            result['probes'] = probe_combos(selected)
        return result
    raise WorkflowError(f'unknown bench command: {args.bench_command}')
