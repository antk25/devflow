"""Everything DevFlow knows about pi as a process: system-prompt addition and model selection."""
import json
import re
from pathlib import Path

PI_SETTINGS = Path.home() / '.pi/agent/settings.json'
INACTIVE = ('needs_init', 'invalid', 'migration_required', 'completed')

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
