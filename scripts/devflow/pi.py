"""Everything DevFlow knows about pi as a process: system-prompt addition, model selection, phase runs."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .documents import WorkflowError, artifact, document
from .workflow import route

PI_SETTINGS = Path.home() / '.pi/agent/settings.json'
AGENTS = Path(__file__).resolve().parents[2] / 'agents'
INACTIVE = ('needs_init', 'invalid', 'migration_required', 'completed')
PHASES = ('research', 'plan')
PRECONDITIONS = {'research': ('research',), 'plan': ('plan', 'plan_outdated')}
TOOLS = {'Read': ('read',), 'Grep': ('grep',), 'Glob': ('find', 'ls'), 'Bash': ('bash',),
         'Write': ('write',), 'Edit': ('edit',)}
BRIDGE_WARNING = ('WARNING: pi will run on claude-bridge — that is Claude; set PI_PROVIDER/PI_MODEL or '
                  'defaultProvider in ~/.pi/agent/settings.json to a non-Claude model')

RULES = """DEVFLOW_RULES
- Состояние задачи двигай только через CLI `devflow` (route, start, finish, interrupt, resume, approve);
  никогда не редактируй `.devflow/` и SQLite напрямую.
- Никогда и ни в каком виде не вызывай `claude` (ни бинарь, ни `claude-bridge`) — эта сессия существует,
  потому что лимиты Claude исчерпаны.
- `devflow approve` — только после явной реплики пользователя «одобряю»/«approve» в этой сессии.
  Своё же исследование или план агент не одобряет.
- Если `devflow route` отдаёт `running`, шаг оборвался (лимит или закрытая сессия). Сначала инспекция:
  `git status`, diff, changelog шага `changelog/<дата>-<slug>.md`, тесты. Затем по уже имеющимся
  доказательствам — `devflow finish <run_id> --status done|partial`, `resume` или `interrupt`.
  Новый `devflow phase run … implement` для того же шага не запускай никогда.
"""


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
    parts.append(RULES.rstrip())
    return '\n'.join(parts) + '\n'


def model_arg(env, override=None):
    if override:
        return override
    provider, model = env.get('PI_PROVIDER'), env.get('PI_MODEL')
    if not provider or not model:
        return None
    level = env.get('PI_REASONING_LEVEL')
    return f'{provider}/{model}' + (f':{level}' if level else '')


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


def build_command(body_file, tools, model_arg, message):
    return ['pi', '-p', '--no-session', '--append-system-prompt', str(body_file), '--tools', ','.join(tools),
            *(['--model', model_arg] if model_arg else []), message]


def run_phase(ctx, db, slug, phase, step=None, note=None, model=None, env=None):
    env = dict(os.environ if env is None else env)
    current = route(ctx, db, slug)
    if current['state'] not in PRECONDITIONS.get(phase, ()):
        raise WorkflowError(f"Phase {phase} cannot run from state {current['state']}")
    body, tools = agent_body(phase)
    chosen = model_arg(env, model)
    if warns_claude_bridge(chosen, PI_SETTINGS):
        print(BRIDGE_WARNING, file=sys.stderr)
    with tempfile.NamedTemporaryFile('w', suffix='.md', prefix='devflow-' + phase + '-', delete=False,
                                     encoding='utf-8') as fh:
        fh.write(body)
    body_file = Path(fh.name)
    try:
        proc = subprocess.run(build_command(body_file, tools, chosen, task_message(phase, ctx, current, step, None, note)),
                              stdin=subprocess.DEVNULL, cwd=ctx['cwd'], env=env, capture_output=True, text=True)
    finally:
        body_file.unlink(missing_ok=True)
    return {'phase': phase, 'slug': current['slug'], 'model': chosen, 'exit_code': proc.returncode,
            'report': proc.stdout, 'stderr': proc.stderr, 'route': route(ctx, db, current['slug'])}
