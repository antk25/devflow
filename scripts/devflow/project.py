"""Project-layer setup for DevFlow: what a project needs and how to create the missing parts."""
import json
import re
import subprocess
from pathlib import Path

import yaml

from .documents import WorkflowError, document
from .storage import atomic_write, connect, db_path, identity

ROOT = Path(__file__).resolve().parents[2]
VAULT_DIRS = ('tz', 'research', 'plans', 'changelog', 'notes')
STALE_DENY = ('Bash(gh:*)', 'Bash(gh *)', 'Bash(*gh *)', 'Bash(git push:*)', 'Bash(git push *)', 'Bash(*git push*)')


def registry_path(root):
    return Path(root) / '.claude/data/projects.json'


def _read(path):
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    return data if isinstance(data, dict) else {}


def _hook_commands(data):
    commands = set()
    for event, groups in (data.get('hooks') or {}).items():
        for group in groups or []:
            for hook in group.get('hooks') or []:
                command = hook.get('command')
                if command:
                    commands.add((event, command))
    return commands


def _permissions(data, kind):
    return [p for p in (data.get('permissions') or {}).get(kind) or [] if isinstance(p, str)]


def settings_drift(actual, example):
    """Report what the example has and the actual file lacks; reads only."""
    wanted, have = _read(example), _read(actual)
    have_commands = _hook_commands(have)
    hooks = [f'{e} {c}' for e, c in sorted(_hook_commands(wanted))
             if not any(e == he and Path(c).name in h for he, h in have_commands)]
    allow = [p for p in _permissions(wanted, 'allow') if p not in _permissions(have, 'allow')]
    deny = [p for p in _permissions(wanted, 'deny') if p not in _permissions(have, 'deny')]
    extra_deny = [p for p in _permissions(have, 'deny') if p in STALE_DENY]
    return {'hooks': hooks, 'allow': allow, 'deny': deny, 'extra_deny': extra_deny}


def _meta(text, source):
    doc = document_text(text, source)
    for key in ('project', 'vault'):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            raise WorkflowError(f'{source} needs a non-empty {key} in frontmatter')
    return doc


def guard_probe(actual):
    """Run each registered guard hook on a harmless command; return the ones that fail."""
    probe = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'true'}})
    broken = []
    for event, command in sorted(_hook_commands(_read(actual))):
        if event != 'PreToolUse' or 'devflow-cli.sh guard' not in command:
            continue
        try:
            result = subprocess.run(command, shell=True, input=probe, capture_output=True, text=True, timeout=5)
            ok = result.returncode == 0 and not result.stdout.strip()
        except subprocess.TimeoutExpired:
            ok = False
        if not ok:
            broken.append(command)
    return broken


def document_text(text, source):
    match = re.match(r'\A---\n(.*?)\n---(?:\n|$)', text, re.S)
    if not match:
        raise WorkflowError(f'{source} has no frontmatter')
    meta = yaml.safe_load(match[1])
    if not isinstance(meta, dict):
        raise WorkflowError(f'{source} frontmatter must be a mapping')
    return meta


def _description(text):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == '## What':
            for candidate in lines[i + 1:]:
                if candidate.startswith('## '):
                    break
                if candidate.strip() and not candidate.strip().startswith('<'):
                    return candidate.strip()
            break
    return ''


def project_name(path, name=None):
    agents = Path(path) / 'AGENTS.md'
    if agents.exists():
        try:
            existing = document(agents)['meta'].get('project')
        except (WorkflowError, yaml.YAMLError):
            existing = None
        if isinstance(existing, str) and existing.strip():
            if name and name != existing:
                raise WorkflowError(f'AGENTS.md names the project {existing!r}, not {name!r}')
            return existing
    return name or Path(path).resolve().name


def render_agents(root=ROOT, name='', draft=None):
    if draft is not None:
        text = Path(draft).read_text(encoding='utf-8')
        meta = _meta(text, str(draft))
        if meta['project'] != name:
            raise WorkflowError(f'Draft names the project {meta["project"]!r}, not {name!r}')
        return text
    template = (Path(root) / 'AGENTS.md.template').read_text(encoding='utf-8')
    return template.replace('<project-name>', name).replace('<ProjectName>', name)


def _item(item, status, detail, action=None):
    return {'item': item, 'status': status, 'detail': detail, 'action': action}


def _vault_path(cwd, value):
    vault = Path(value).expanduser()
    if not vault.is_absolute():
        vault = cwd / vault
    return vault.resolve()


def plan_items(path, name, root=ROOT, draft=None, create_agents=True):
    """Ordered checklist of the project layer; reads only, actions are closures."""
    cwd = Path(path).resolve()
    agents = cwd / 'AGENTS.md'
    items = []
    if (cwd / '.git').exists():
        items.append(_item('git', 'attention', 'в каталоге есть .git: личные файлы (.devflow/, AGENTS.md) попадут в репозиторий, проверь .gitignore'))
    if agents.exists():
        text = agents.read_text(encoding='utf-8')
        try:
            meta = _meta(text, 'AGENTS.md')
        except (WorkflowError, yaml.YAMLError) as exc:
            items.append(_item('agents_md', 'attention', f'AGENTS.md не читается: {exc}'))
            return items
        agents_item = _item('agents_md', 'skipped', 'уже есть, не изменяется')
    elif create_agents:
        text = render_agents(root, name, draft)
        meta = _meta(text, 'draft' if draft else 'AGENTS.md.template')
        source = 'из черновика' if draft else 'из AGENTS.md.template'
        agents_item = _item('agents_md', 'create', source, lambda: atomic_write(agents, text))
    else:
        items.append(_item('agents_md', 'attention', 'AGENTS.md отсутствует; подключи проект через /project init'))
        return items
    vault = _vault_path(cwd, meta['vault'])
    if not vault.parent.exists():
        items.append(_item('vault', 'attention', f'родитель vault не существует (диск не смонтирован?): {vault.parent}'))
        return items
    for folder in VAULT_DIRS:
        target = vault / folder
        if target.is_dir():
            items.append(_item(f'vault:{folder}', 'skipped', str(target)))
        else:
            items.append(_item(f'vault:{folder}', 'create', str(target), lambda t=target: t.mkdir(parents=True, exist_ok=True)))
    items.append(agents_item)
    ctx = {'project': name, 'cwd': cwd, 'vault': vault}
    if (cwd / '.devflow/project.json').exists():
        items.append(_item('identity', 'skipped', str(cwd / '.devflow/project.json')))
        database = db_path(ctx)[0]
        if database.exists():
            items.append(_item('database', 'skipped', str(database)))
        else:
            items.append(_item('database', 'attention', f'идентичность есть, базы нет: {database}; восстанови её из резервной копии или запусти devflow init --fresh-state'))
            return items
    else:
        items.append(_item('identity', 'create', str(cwd / '.devflow/project.json'), lambda: identity(ctx, create=True)))
        items.append(_item('database', 'create', 'новая база состояния', lambda: connect(ctx, create=True, fresh=True).close()))
    from .registry import load, register  # registry imports registry_path from here
    registry = registry_path(root)
    entry = (load(registry)['projects'] if registry.exists() else {}).get(name)
    if entry and Path(entry['path']).resolve() == cwd:
        items.append(_item('registry', 'skipped', f'{name} уже в реестре'))
    elif entry:
        items.append(_item('registry', 'attention', f'имя {name} занято другим путём: {entry["path"]}'))
    else:
        items.append(_item('registry', 'create', f'{name} → {registry}',
                           lambda: register(registry, name, cwd, _description(text))))
    return items


def apply(items):
    report, failed = [], False
    for item in items:
        entry = {k: v for k, v in item.items() if k != 'action'}
        if item['status'] == 'create':
            if failed:
                entry['status'], entry['detail'] = 'attention', 'не выполнено: остановлено после ошибки'
            else:
                try:
                    item['action']()
                    entry['status'] = 'created'
                except (WorkflowError, OSError, ValueError) as exc:
                    entry['status'], entry['detail'], failed = 'attention', str(exc), True
        report.append(entry)
    return report


def init(path, name=None, root=ROOT, draft=None, dry_run=False):
    cwd = Path(path).resolve()
    if not cwd.is_dir():
        raise WorkflowError(f'Project directory does not exist: {cwd}')
    name = project_name(cwd, name)
    registry = registry_path(root)
    if registry.exists():
        from .registry import load
        entry = load(registry)['projects'].get(name)
        if entry and Path(entry['path']).resolve() != cwd:
            raise WorkflowError(f'Project name {name} is already registered for {entry["path"]}')
    items = plan_items(cwd, name, root, draft)
    if dry_run:
        items = [{k: v for k, v in item.items() if k != 'action'} for item in items]
    else:
        items = apply(items)
    return {'project': name, 'path': str(cwd), 'items': items}


def sync(names=(), root=ROOT, all_projects=False, dry_run=False):
    """Check every named registry project against the project layer; never generates AGENTS.md."""
    from .registry import load
    registry = load(registry_path(root))['projects']
    if all_projects:
        names = list(registry)
    elif not names:
        raise WorkflowError('project sync needs project names or --all')
    unknown = [n for n in names if n not in registry]
    if unknown:
        raise WorkflowError(f'Not in registry: {", ".join(unknown)}')
    reports = []
    for name in names:
        path = Path(registry[name]['path'])
        if not path.is_dir():
            items = [_item('path', 'attention', f'каталог проекта не существует: {path}')]
        else:
            try:
                project_name(path, name)
                items = plan_items(path, name, root, create_agents=False)
            except WorkflowError as exc:
                items = [_item('agents_md', 'attention', str(exc))]
        if dry_run:
            items = [{k: v for k, v in item.items() if k != 'action'} for item in items]
        else:
            items = apply(items)
        reports.append({'project': name, 'path': str(path), 'items': items})
    return reports
