#!/usr/bin/env python3
"""Validate the selection before updating active, then start the Claude driver or pi."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from devflow import pi
from devflow.cli import active
from devflow.documents import WorkflowError, context, handoff_latest
from devflow.project import registry_path
from devflow.registry import load, select
from devflow.storage import connect


def main():
    root = Path(__file__).resolve().parent.parent
    registry = registry_path(root)
    p = argparse.ArgumentParser(description='Choose a project and launch DevFlow')
    p.add_argument('project', nargs='?')
    p.add_argument('--current', '-c', action='store_true')
    p.add_argument('--agent', choices=['claude', 'pi'], default='claude')
    p.add_argument('--model', help='claude: overrides DEVFLOW_MODEL; pi: provider/id[:thinking]')
    args = p.parse_args()
    if args.current and args.project:
        p.error('Use a project name or --current, not both')
    if not registry.exists():
        raise WorkflowError(f'Project registry missing: {registry}. Run ./install.sh first.')
    data = load(registry)
    selected = args.project or (data.get('active') if args.current else None)
    if args.current and not selected:
        raise WorkflowError('No active project; select a project by name')
    if selected is None:
        gum = os.environ.get('GUM') or shutil.which('gum') or shutil.which('gum', path=str(Path.home() / 'bin'))
        if not gum:
            raise WorkflowError('gum is missing; use ./start.sh <project>')
        names = sorted(data['projects'], key=lambda n: (n != data.get('active'), n))
        if not names:
            raise WorkflowError('Project registry is empty')
        choice = subprocess.run([gum, 'choose', '--header', 'Select project:'],
                                input='\n'.join(names) + '\n', text=True, capture_output=True)
        if choice.returncode:
            if choice.stderr:
                print(choice.stderr, file=sys.stderr, end='')
            print('Cancelled.')
            return 0
        selected = choice.stdout.rstrip('\r\n')
    if selected not in data['projects']:
        raise WorkflowError(f'Unknown project {selected!r}. Available: ' + ', '.join(data['projects']))
    path = Path(data['projects'][selected]['path'])
    if not path.is_dir():
        raise WorkflowError(f'Project directory is missing: {path}')
    if args.agent == 'pi':
        executable, argv = pi_command(path, args.model)
    else:
        executable = shutil.which('claude')
        if not executable:
            raise WorkflowError('Claude CLI is missing from PATH')
        if not (path / 'AGENTS.md').exists():
            print(f'{path} has no AGENTS.md. Run /project init {path} inside Claude Code, '
                  f'or: devflow project init {path}')
            if input('Launch without DevFlow project context? [y/N] ').lower() not in ('y', 'yes'):
                return 0
        else:
            ctx = context(path)
            connect(ctx, create=True).close()
        model = args.model or os.environ.get('DEVFLOW_MODEL', 'claude-fable-5-1')
        argv = [executable, '--model', model]
    previous = data.get('active')
    os.chdir(path)
    select(registry, selected)
    print(f'Launching {args.agent} for {selected}: {path}', flush=True)
    try:
        os.execv(executable, argv)
    except OSError:
        # exec failed before the process was replaced; restore this launcher's selection.
        from devflow.storage import atomic_write
        latest = load(registry)
        if latest.get('active') == selected:
            latest['active'] = previous
            atomic_write(registry, json.dumps(latest, ensure_ascii=False, indent=2) + '\n')
        raise


def pi_command(path, model):
    """pi in the project directory with the DevFlow context appended; writes nothing into the project."""
    executable = shutil.which('pi')
    if not executable:
        raise WorkflowError('pi CLI is missing from PATH')
    model = pi.model_arg(os.environ, model)
    if pi.warns_claude_bridge(model):
        print('WARNING: pi would run on claude-bridge (Claude); pass --model provider/id or set '
              'PI_PROVIDER/PI_MODEL', file=sys.stderr)
    argv = [executable] + (['--model', model] if model else [])
    if not (path / 'AGENTS.md').exists():
        print(f'WARNING: {path} has no AGENTS.md; launching pi without DevFlow context', file=sys.stderr)
        return executable, argv
    ctx = context(path)
    db = None
    if (path / '.devflow/project.json').exists():
        db = connect(ctx)
    try:
        items = active(ctx, db)
    finally:
        if db:
            db.close()
    key = pi.task_key(items)
    handoff = handoff_latest(ctx['vault'], key) if key else None
    with tempfile.NamedTemporaryFile('w', prefix='devflow-pi-', suffix='.md', delete=False,
                                     dir=tempfile.gettempdir(), encoding='utf-8') as f:
        f.write(pi.preamble(ctx, items, handoff))
    return executable, argv + ['--append-system-prompt', f.name]


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (WorkflowError, OSError, ValueError, EOFError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
