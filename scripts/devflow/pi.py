"""Everything DevFlow knows about pi as a process: system-prompt addition, model selection, phase runs.

Model for a phase run: `--model` > policy (`route.launch.pi.model`) > `PI_*` env > pi default."""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .documents import WorkflowError, artifact, document
from .policy import PHASES
from .workflow import interrupt, route, start

PI_SETTINGS = Path.home() / '.pi/agent/settings.json'
AGENTS = Path(__file__).resolve().parents[2] / 'agents'
INACTIVE = ('needs_init', 'invalid', 'migration_required', 'completed')
PRECONDITIONS = {'research': ('research',), 'plan': ('plan', 'plan_outdated'), 'implement': ('ready',)}
RUNNING_WARNING = ('phase did not record finish; run is still running — inspect git status and the changelog, then '
                   'devflow finish/resume/interrupt; do not run phase run implement again')
TOOLS = {'Read': ('read',), 'Grep': ('grep',), 'Glob': ('find', 'ls'), 'Bash': ('bash',),
         'Write': ('write',), 'Edit': ('edit',)}
BRIDGE_WARNING = ('claude-bridge запрещён в pi; выберите --model provider/id или прямой anthropic/*')
SHARED_INSTRUCTIONS = Path.home() / '.claude/devflow-instructions.md'
EXTENSION = Path(__file__).resolve().parents[2] / 'pi/extensions/devflow.ts'


def shared_instructions(path):
    try:
        text = Path(path).read_text(encoding='utf-8').strip()
        if not text:
            raise ValueError('пустой файл')
        return text
    except (OSError, ValueError) as exc:
        raise WorkflowError(f'Общие инструкции недоступны: {path}: {exc}; запустите ./install.sh')


def ensure_pi_model(model, settings_path):
    if model:
        provider, separator, model_id = model.partition('/')
        if not separator or not model_id or any(c in provider for c in '*?[]'):
            raise WorkflowError('Укажите точную модель pi как provider/id[:thinking], без шаблона провайдера')
    else:
        path = Path(settings_path)
        try:
            settings = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(settings, dict):
                raise ValueError('expected an object')
            provider = settings.get('defaultProvider')
        except FileNotFoundError:
            provider = None
        except (OSError, ValueError) as exc:
            raise WorkflowError(f'Cannot read pi settings {path}: {exc}')
    if isinstance(provider, str) and provider.lower() == 'claude-bridge':
        raise WorkflowError(BRIDGE_WARNING)


def settings_path(env):
    return Path(env['PI_CODING_AGENT_DIR']) / 'settings.json' if env.get('PI_CODING_AGENT_DIR') else PI_SETTINGS


def extension_path(env):
    installed = Path(env.get('PI_CODING_AGENT_DIR', Path.home() / '.pi/agent')) / 'extensions/devflow.ts'
    if installed.exists():
        if installed.resolve() != EXTENSION.resolve():
            raise WorkflowError(f'CONFLICT pi extension: {installed}; запустите ./install.sh')
        # pi deduplicates paths, not symlink targets: use the discovery path, not the source path.
        return installed
    return EXTENSION


def task_key(active):
    """Jira key (slug prefix) of the most advanced active task, or None."""
    for folder in ('plans', 'research', 'tz'):
        for item in active.get(folder, ()):
            if item.get('status') in INACTIVE:
                continue
            m = re.match(r'([a-z]+-\d+)', item['name'].lower())
            if m:
                return m[1].upper()
    return None


def preamble(ctx, active, handoff):
    parts = ['PROJECT_RESTORE', json.dumps({k: str(v) for k, v in ctx.items()}, ensure_ascii=False, indent=2),
             'OBSIDIAN_CONTEXT', json.dumps(active, ensure_ascii=False, indent=2)]
    if handoff:
        parts += [f"HANDOFF {handoff['path']}", handoff['body'].strip()]
    return '\n'.join(parts) + '\n'


def model_arg(env, override=None):
    if override:
        return override
    provider, model = env.get('PI_PROVIDER'), env.get('PI_MODEL')
    if not provider or not model:
        return None
    level = env.get('PI_REASONING_LEVEL')
    return f'{provider}/{model}' + (f':{level}' if level else '')


def model_env(model):
    """PI_* variables for `provider/id[:level]`, so phase processes inherit the session's model."""
    provider, _, rest = model.partition('/')
    if not provider or not rest:
        return {}
    model_id, _, level = rest.partition(':')
    env = {'PI_PROVIDER': provider, 'PI_MODEL': model_id}
    if level:
        env['PI_REASONING_LEVEL'] = level
    return env


def warns_claude_bridge(model_arg, settings_path=PI_SETTINGS):
    if model_arg:
        return model_arg.startswith('claude-bridge/')
    try:
        return json.loads(Path(settings_path).read_text(encoding='utf-8')).get('defaultProvider') == 'claude-bridge'
    except (OSError, ValueError, AttributeError):
        return False


def agent_body(phase):
    path = AGENTS / f'{phase}.md'
    if phase not in PHASES or not path.is_file():
        raise WorkflowError(f'Unknown phase: {phase}')
    doc = document(path)
    tools = []
    for name in str(doc['meta'].get('tools', '')).split(','):
        for tool in TOOLS.get(name.strip(), ()):
            if tool not in tools:
                tools.append(tool)
    return doc['body'].strip() + '\n', tools


def task_message(phase, ctx, state, step=None, run=None, note=None):
    lines = [f'DevFlow Phase — {phase}.', '', f"cwd: {ctx['cwd']}", f"slug: {state['slug']}",
             f"vault: {ctx['vault']}"]
    for key in ('research_revision', 'plan_revision', 'research_path', 'plan_path'):
        if state.get(key):
            lines.append(f"{key}: {state[key]}")
    tz = artifact(ctx['vault'], 'tz', state['slug'])
    if tz:
        lines.append(f"tz: {tz['path']}")
    if run:
        lines += ['', f"run_id: {run['run_id']}", f"step: {run['step']}" + (f" (n={state['n']})" if state.get('n') else ''),
                  f"plan_revision: {run['revision']}"]
    if note:
        lines += ['', 'Замечание пользователя:', note.strip()]
    return '\n'.join(lines) + '\n'


def build_command(body_file, tools, model_arg, message, options=('--no-session',)):
    return ['pi', '-p', *options, '--append-system-prompt', str(body_file), '--tools', ','.join(tools),
            *(['--model', model_arg] if model_arg else []), message]


def run_phase(ctx, db, slug, phase, step=None, note=None, model=None, env=None):
    env = dict(os.environ if env is None else env)
    current = route(ctx, db, slug)
    at_own_gate = current['state'] == 'approval_required' and current.get('phase') == phase
    if current['state'] not in PRECONDITIONS.get(phase, ()) and not at_own_gate:
        raise WorkflowError(f"Phase {phase} cannot run from state {current['state']}")
    body, tools = agent_body(phase)
    if not shutil.which('pi', path=env.get('PATH')):
        raise WorkflowError('pi CLI is missing from PATH')
    from_policy = current.get('launch', {}).get('pi', {}).get('model')
    chosen = model_arg(env, model or from_policy)
    source = 'override' if model else 'policy' if from_policy else 'env' if chosen else 'default'
    ensure_pi_model(chosen, settings_path(env))
    shared_instructions(Path(env.get('DEVFLOW_INSTRUCTIONS', SHARED_INSTRUCTIONS)))
    extension = extension_path(env)
    run = None
    if phase == 'implement':
        step = step or current['step']
        if step not in current['frontier']:
            raise WorkflowError(f'Step {step} is not on the frontier: ' + ', '.join(current['frontier']))
        run = start(ctx, db, current['slug'], step, current['revision'])
        if step != current['step']:
            current = dict(current, n=None)
    with tempfile.NamedTemporaryFile('w', suffix='.md', prefix='devflow-' + phase + '-', delete=False,
                                     encoding='utf-8') as fh:
        fh.write(body)
    body_file = Path(fh.name)
    try:
        proc = subprocess.run(build_command(body_file, tools, chosen, task_message(phase, ctx, current, step, run, note),
                                             options=('--no-session', '--extension', str(extension))),
                              stdin=subprocess.DEVNULL, cwd=ctx['cwd'], env=env, capture_output=True, text=True)
    except OSError as exc:
        if run:
            interrupt(db, run['run_id'], f'pi failed to launch: {exc}')
        raise WorkflowError(f'pi failed to launch: {exc}')
    finally:
        body_file.unlink(missing_ok=True)
    after = route(ctx, db, current['slug'])
    result = {'phase': phase, 'slug': current['slug'], 'model': chosen, 'model_source': source, 'exit_code': proc.returncode,
              'report': proc.stdout, 'stderr': proc.stderr, 'route': after}
    if run:
        result['run_id'] = run['run_id']
        if after['state'] == 'running':
            result['warning'] = RUNNING_WARNING
    return result
