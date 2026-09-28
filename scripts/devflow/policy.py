"""Model/effort policy: host × phase × complexity → {model, effort}, read from a user-editable JSON."""
import json
import os
from pathlib import Path

from .documents import WorkflowError

REQUIRED = ('claude', 'pi', 'limits')
ALIASES = {'claude-opus-': 'opus', 'claude-fable-': 'fable', 'claude-sonnet-': 'sonnet', 'claude-haiku-': 'haiku'}


def policy_path():
    return Path(os.environ.get('DEVFLOW_MODEL_POLICY', str(Path.home() / '.claude/devflow/model-policy.json')))


def load(path):
    if not path.exists():
        return None
    try:
        policy = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise WorkflowError(f'Model policy is not valid JSON: {path}: {e}')
    missing = [k for k in REQUIRED if not isinstance(policy, dict) or k not in policy]
    if missing:
        raise WorkflowError(f'Model policy {path} lacks keys: ' + ', '.join(missing))
    return policy


def resolve(policy, host, phase, complexity=None, exhausted=False):
    phases = policy.get(host)
    if not isinstance(phases, dict) or phase not in phases:
        raise WorkflowError(f'Model policy has no entry for {host}/{phase}')
    columns = phases[phase]
    if 'default' not in columns:
        raise WorkflowError(f'Model policy {host}/{phase} has no default column')
    if exhausted and 'fallback' in columns:
        column = 'fallback'
    elif complexity == 'high' and 'high' in columns:
        column = 'high'
    else:
        column = 'default'
    entry = columns[column]
    return {'model': entry['model'], 'effort': entry['effort'], 'column': column}


def alias(model_id):
    for prefix, name in ALIASES.items():
        if model_id.startswith(prefix):
            return name
    return None


def pi_model(entry):
    return entry['model'] + (':' + entry['effort'] if entry.get('effort') else '')


def launch(phase, complexity=None, exhausted=False):
    """`policy` + `launch` fields for `route`; empty dict when no policy file is installed."""
    path = policy_path()
    policy = load(path)
    if policy is None:
        return {'policy': None}
    claude = resolve(policy, 'claude', phase, complexity, exhausted)
    pi = resolve(policy, 'pi', phase, complexity, exhausted)
    return {'policy': str(path),
            'launch': {'claude': {'id': claude['model'], 'effort': claude['effort'], 'model': None},
                       'pi': {'model': pi_model(pi)}}}
