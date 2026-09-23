"""Project registry operations; names and paths are data, never Python source."""
import json
from pathlib import Path

from .documents import WorkflowError
from .project import registry_path
from .storage import atomic_write


def load(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != '3.0' or not isinstance(data.get('projects'), dict):
        raise WorkflowError('Unsupported or malformed project registry')
    for name, entry in data['projects'].items():
        if not name or any(c in name for c in '\r\n\t') or not isinstance(entry, dict):
            raise WorkflowError('Invalid project registry entry')
        if not isinstance(entry.get('path'), str) or not Path(entry['path']).is_absolute():
            raise WorkflowError(f'Project {name} needs an absolute path')
    if data.get('active') is not None and data['active'] not in data['projects']:
        raise WorkflowError('Active project is not in the registry')
    return data


def initialize(root):
    path = registry_path(root)
    if path.exists():
        load(path)
        return
    atomic_write(path, json.dumps({'version': '3.0', 'active': 'devflow', 'projects': {
        'devflow': {'path': str(root), 'description': 'DevFlow workflow orchestration'}}}, indent=2) + '\n')


def select(path, name):
    data = load(path)
    if name not in data['projects']:
        raise WorkflowError(f'Unknown project: {name}')
    data['active'] = name
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def register(path, name, project_path, description=''):
    path = Path(path)
    data = load(path) if path.exists() else {'version': '3.0', 'active': None, 'projects': {}}
    project_path = Path(project_path).resolve()
    entry = data['projects'].get(name)
    if entry:
        if Path(entry['path']).resolve() != project_path:
            raise WorkflowError(f'Project name {name} is already registered for {entry["path"]}')
        return data
    data['projects'][name] = {'path': str(project_path), 'description': description}
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    return data
